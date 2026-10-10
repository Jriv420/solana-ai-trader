import asyncio,json,os,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
from datetime import datetime,timezone,timedelta
import database.store as db
from database.store import Store
from database.wallet_registry import wallet_registry
from database.research import research
from paper.paper_trader import paper_trader
from strategy.token_filter import evaluate_token
from strategy.sizing import position_size_sol
from strategy.exit import should_exit
from intelligence.wallet_ai import score_wallet_context
from intelligence import decision_engine as engine
from data.social_data import summarize,ensure
import app
from fastapi.testclient import TestClient
MINT='So11111111111111111111111111111111111111112'
WALLET='11111111111111111111111111111111'

class IntelligenceWiring(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.patch=patch.object(db,'DB',Path(self.tmp.name)/'db.sqlite3');self.patch.start()
        db.Store().ensure_observations();wallet_registry.ensure();research.ensure();ensure();engine._CACHE.clear();engine.CONNECTIONS.clear()
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def token(self):return {'mint':MINT,'price_usd':1,'sol_price_usd':100,'timestamp':time.time(),'liquidity_usd':50000,'age_minutes':1,'buys_5m':10,'sells_5m':2,'volume_5m_usd':20000,'volume_1h_usd':40000}
    def test_revival_passes_on_real_surge_not_age_alone(self):
        t=self.token();t['age_minutes']=20000
        result=evaluate_token(t);self.assertTrue(result['pass']);self.assertEqual(result['mode'],'revival')
        t.update(volume_5m_usd=100,volume_1h_usd=1000);self.assertFalse(evaluate_token(t)['pass'])
        t.update(volume_5m_usd=6000,volume_1h_usd=100000,wallet_context={'qualified_holders':1});self.assertTrue(evaluate_token(t)['pass'])
        t['research']={'security':{'status':'unavailable'}};self.assertFalse(evaluate_token(t)['pass'])
    def test_qualified_reputation_and_fresh_position_drive_wallet_score(self):
        wallet_registry.add(WALLET,manual=True);wallet_registry.position(WALLET,MINT,'100',30000)
        whale=score_wallet_context(self.token());self.assertEqual(whale['qualified_holders'],0);self.assertLess(whale['score'],50)
        wallet_registry.profile(WALLET,{'qualified':True,'data_status':'ok','score':80,'matched_sells':12})
        learned=score_wallet_context(self.token());self.assertEqual(learned['qualified_holders'],1);self.assertGreaterEqual(learned['score'],70)
        wallet_registry.position(WALLET,MINT,'0',0);self.assertEqual(score_wallet_context(self.token())['tracked_holders'],0)
        wallet_registry.position(WALLET,MINT,'100',100)
        with db.store.conn() as c:c.execute('UPDATE wallet_positions SET checked_at=?',(time.time()-901,))
        self.assertEqual(score_wallet_context(self.token())['tracked_holders'],0)
    def test_paper_costs_and_sol_price_change_are_accounted(self):
        t=self.token();trade=paper_trader.buy(t,.1,{})
        position=db.store.open()[0];self.assertAlmostEqual(position['entry_price_usd'],1.01)
        self.assertTrue(paper_trader.sell(position,t,'test'))
        closed=db.store.all()[0];self.assertLess(closed['pnl_sol'],0);self.assertEqual(db.store.paper_metrics()['cost_model_trades'],1)
        self.assertFalse(paper_trader.sell(position,t,'repeat'))
        trade=paper_trader.buy(t,.1,{});position=db.store.open()[0];t['sol_price_usd']=200
        paper_trader.sell(position,t,'SOL doubled');self.assertLess(db.store.all()[0]['pnl_pct'],-50)
    def test_no_overspend_and_no_missing_sol_price_fill(self):
        self.assertEqual(position_size_sol(100,0),0);self.assertLessEqual(position_size_sol(100,.00006),.00006)
        t=self.token();t['sol_price_usd']=None;self.assertIsNone(paper_trader.buy(t,.1,{}))
        t=self.token();t['timestamp']=time.time()-121;self.assertIsNone(paper_trader.buy(t,.1,{}))
    def test_daily_loss_uses_only_current_utc_day(self):
        now=time.time();old=db.store.create_trade({'mint':MINT,'entry_price_usd':1,'amount_sol':1,'entry_time':now-90000})
        db.store.close_trade(old['id'],.1,now-90000,-90,-.9,'old')
        new=db.store.create_trade({'mint':MINT,'entry_price_usd':1,'amount_sol':1,'entry_time':now})
        db.store.close_trade(new['id'],.8,now,-20,-.2,'today')
        self.assertAlmostEqual(db.store.daily_realized(now),-.2);self.assertAlmostEqual(db.store.realized(),-1.1)
    def test_trailing_peak_persists_and_stale_prices_do_not_exit(self):
        t=self.token();p=paper_trader.buy(t,.1,{});db.store.mark_peak(p['id'],1.4);position=db.store.open()[0]
        t['price_usd']=1.1;self.assertEqual(should_exit(position,t)['reason'],'trailing stop')
        t['timestamp']=time.time()-121;self.assertFalse(should_exit(position,t)['exit'])
    def test_x_mint_matching_and_sampling_do_not_confirm_endorsement(self):
        now=time.time();created=datetime.fromtimestamp(now-1,timezone.utc).isoformat().replace('+00:00','Z')
        config=SimpleNamespace(x_kol_ids=('kol',))
        data={'meta':{'next_token':'more'},'data':[{'id':'1','author_id':'kol','text':MINT+' interesting','created_at':created},{'id':'2','author_id':'other','text':'Same ticker different coin','created_at':created}]}
        with patch('data.social_data.settings',config):result=summarize(data,MINT,now)
        self.assertEqual(result['mentions_5m'],1);self.assertEqual(result['known_influencers'],['kol']);self.assertTrue(result['sample_truncated']);self.assertNotIn('endorsement',result)
    def test_model_fallback_skips_invalid_response_and_redacts_errors(self):
        token=self.token()
        with patch.object(engine,'ask_jev',new=AsyncMock(return_value={'score':float('nan')})),patch.object(engine,'ask_laya',new=AsyncMock(return_value={'score':80})),patch.object(engine,'ask_darwin',new=AsyncMock()) as darwin:
            result=asyncio.run(engine.evaluate_fast(token));self.assertEqual(result['provider'],'laya');darwin.assert_not_awaited()
        engine._CACHE.clear()
        token.update(liquidity_usd=100000,volume_5m_usd=500000,price_change_5m_pct=20)
        with patch.object(engine,'ask_jev',new=AsyncMock(side_effect=RuntimeError('secret-key'))),patch.object(engine,'ask_laya',new=AsyncMock(side_effect=RuntimeError('secret-key'))),patch.object(engine,'ask_darwin',new=AsyncMock(return_value={'score':85})):
            result=asyncio.run(engine.evaluate_fast(token));self.assertEqual(result['provider'],'darwin');self.assertNotIn('secret-key',json.dumps(engine.CONNECTIONS))
        self.assertEqual(engine._score({'score':1}),1)
        self.assertEqual(engine._score({'score':80,'confidence':.8}),80)
    def test_connection_summary_does_not_expose_keys(self):
        with patch.dict(os.environ,{'NEXUS_PASSWORD':'test','RAILWAY_VOLUME_MOUNT_PATH':self.tmp.name}),TestClient(app.app) as client:
            response=client.get('/api/connections',auth=('nexus','test'));self.assertEqual(response.status_code,200)
            result=response.json();self.assertTrue(result['storage']['railway_volume_detected']);self.assertNotIn('api_key',json.dumps(result));self.assertEqual(client.get('/api/connections').status_code,401)

if __name__=='__main__':unittest.main()
