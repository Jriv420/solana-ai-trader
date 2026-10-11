import json,tempfile,time,unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch,AsyncMock
from intelligence import model_team as team,exit_policy
from config.settings import settings
from database.store import Store
import database.store as db
from paper.paper_trader import PaperTrader

class ModelTeam(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=patch.object(db,'DB',Path(self.tmp.name)/'db');self.db.start()
        db.store.ensure_observations();self.book=Store('shadow_trades');team._CACHE.clear();team.STATUS.clear()
        self.cfg=replace(settings,paper_mode=True,jev_api_key='test',jev_endpoint='https://test',gemini_api_key='test',laya_api_key='test',laya_endpoint='https://test',darwin_api_key='test',darwin_endpoint='https://test',openai_api_key='')
        self.patch=patch.object(team,'settings',self.cfg);self.patch.start()
    def tearDown(self):self.patch.stop();self.db.stop();self.tmp.cleanup()
    async def test_all_configured_models_called_and_weighted_scores_recorded(self):
        with patch.object(team,'ask_gemini',AsyncMock(return_value={'score':90,'review':{'reason':'Sourced narrative'}})) as gem,patch.object(team,'ask_laya',AsyncMock(return_value={'score':60,'reason':'Flow risk'})) as laya,patch.object(team,'ask_darwin',AsyncMock(return_value={'score':50,'reason':'Independent risk'})) as darwin,patch.object(team,'ask_jev',AsyncMock(return_value={'score':80,'answers':{'setup':{'confidence':.8}}})) as jev:
            r=await team.entry({'mint':'A','price_usd':1,'research':{'features':{'narrative':'unknown'}}})
            for c in (gem,laya,darwin,jev):c.assert_awaited_once()
            self.assertEqual(r['provider'],'model-team');self.assertAlmostEqual(r['score'],78)
            self.assertEqual(set(r['team']['final']['contributors']),{'jev','gemini','laya','darwin'})
            self.assertEqual(len(jev.call_args.args[0]['peer_reviews']),4)
            self.assertEqual(next(x for x in r['team']['reviews'] if x['provider']=='jev')['confidence'],.8)
            await team.entry({'mint':'A'});self.assertEqual(jev.await_count,1)
    async def test_failed_model_excluded_and_missing_reason_not_invented(self):
        state={'task':'paper_exit','mint':'B','position':{'id':1}}
        with patch.object(team,'ask_laya',AsyncMock(side_effect=RuntimeError('secret credential'))),patch.object(team,'ask_darwin',AsyncMock(return_value={'score':30,'reason':'Risk advisory'})):
            reviews,d=await team.exit_reviews(state,AsyncMock(return_value={'action':'sell_10'}),AsyncMock(return_value={'action':'sell_70','reason':'Weakening flow'}))
        self.assertEqual(d['action'],'sell_30')
        self.assertEqual(d['contributors'],['gemini','jev'])
        self.assertNotIn('secret credential',json.dumps(reviews))
        self.assertEqual(next(x for x in reviews if x['provider']=='jev')['reason_source'],'unavailable')
    def test_compaction_blocks_recursive_growth_and_keeps_core_risk_evidence(self):
        state={'task':'paper_exit','mint':'C','current':{'price_usd':1,'liquidity_usd':5000},'research':{'security':{'status':'ok','danger':True},'notes':'x'*100000},'past_completed_positions':[{'features':{'notes':'y'*5000}}]*20,'previous_decision':{'decision_state':{'text':'z'*100000}}}
        s=team.compact(state);self.assertLess(len(json.dumps(s).encode()),11500)
        self.assertTrue(s['research']['security']['danger']);self.assertEqual(s['current'],state['current']);self.assertNotIn('previous_decision',s)
    async def test_protective_exit_bypasses_all_model_requests(self):
        trader=PaperTrader(self.book);t={'mint':'D','symbol':'D','timestamp':time.time(),'price_usd':1,'sol_price_usd':100,'market_cap_usd':12600}
        trader.buy(t,.1,{})
        with patch.object(team,'exit_reviews',AsyncMock()) as reviews,patch.object(exit_policy,'settings',self.cfg):
            d=await exit_policy.decide(self.book,self.book.open()[0],dict(t,price_usd=.7))
            self.assertEqual(d['reason'],'hard stop');reviews.assert_not_awaited()
            self.assertTrue(trader.sell(self.book.open()[0],dict(t,price_usd=.7),d['reason']))
        audit=self.book.position_history()[0]['position_history']['fills'][0]['execution_audit'];self.assertTrue(audit['risk_override'])
    def test_high_scores_do_not_ignore_majority_wait_recommendations(self):
        reviews=[{'provider':'jev','status':'verified_response','action':'hold','score':90},{'provider':'gemini','status':'verified_response','action':'buy','score':90}]
        d=team.combine(reviews,'entry');self.assertEqual(d['action'],'hold');self.assertLess(d['score'],50)
    async def test_aggressive_runtime_prepares_and_honors_team_review(self):
        from paper import shadow
        mint='EQ46GCkgPctvueFDt2edutfa1hKxsDzo2EZeSMiHpump'
        t={'mint':mint,'symbol':'T','timestamp':time.time(),'price_usd':1,'sol_price_usd':100,'market_cap_usd':12600,'liquidity_usd':10000,'volume_5m_usd':5000,'price_change_5m_pct':10,'buys_5m':50,'sells_5m':10,'research':{'security':{'status':'ok','danger':False}}}
        obs=[{'token':t}]
        with patch.object(shadow,'BOOK',self.book),patch.object(shadow,'TRADER',PaperTrader(self.book)),patch.object(shadow,'initialize',return_value={'started_at':time.time()-1,'ends_at':time.time()+1000}),patch.object(team,'entry',AsyncMock(return_value={'provider':'model-team','score':40,'team':{'reviews':[],'final':{'action':'hold'}}})) as call:
            await shadow.prepare_entries(obs);d=shadow.step(obs,process_exits=False)
            self.assertEqual(d['paper_buys'],0);call.assert_awaited_once();self.assertIn('model team entry evidence below 50',d['blockers'])
            self.assertEqual(call.call_args.args[0]['book'],'shadow_trades')
    def test_continuous_paper_mode_survives_expired_deadline_and_restart(self):
        import os
        from paper import shadow
        import config.settings as config
        with patch.dict(os.environ,{'PAPER_CONTINUOUS':'true','PAPER_TEST_UNTIL':'1'}),patch.object(config,'settings',self.cfg),patch.object(shadow,'settings',self.cfg),patch.object(shadow,'BOOK',self.book),patch.object(shadow,'TRADER',PaperTrader(self.book)):
            self.assertIsNone(shadow.initialize()['ends_at'])
            self.assertIsNone(shadow.initialize()['ends_at'])
            self.assertTrue(shadow.step([],process_exits=False)['active'])
            self.assertTrue(shadow.summary()['continuous'])
    async def test_increased_exit_budget_preserves_existing_daily_counter(self):
        db.store.reserve_ai_request('jev_exit','2000-01-01',1)
        from datetime import datetime,timezone
        day=datetime.now(timezone.utc).date().isoformat()
        with db.store.conn() as c:c.execute('INSERT OR REPLACE INTO ai_requests VALUES(?,?,?)',('jev_exit',day,300))
        with patch.object(team,'settings',replace(self.cfg,jev_exit_daily_limit=6000)):
            r=await team.review('jev',{'task':'paper_exit','mint':'budget','position':{'id':1}},'exit',AsyncMock(return_value={'action':'hold','reason':'Flow stable'}))
        self.assertEqual(r['status'],'verified_response');self.assertEqual(db.store.ai_request_count('jev_exit',day),301)
    async def test_disabled_and_key_without_endpoint_are_never_called(self):
        with patch.object(team,'settings',replace(self.cfg,darwin_endpoint='')),patch.object(team,'ask_darwin',AsyncMock()) as call:
            r=await team.review('darwin',{},'entry');self.assertEqual(r['status'],'not_configured');call.assert_not_awaited()
