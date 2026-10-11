import json,tempfile,time,unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch,AsyncMock
import database.store as db
from database.store import Store
from config.settings import settings
from paper.paper_trader import PaperTrader
from intelligence import exit_policy as ai,jev,gemini_review,model_team

class AdaptiveExits(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=patch.object(db,'DB',Path(self.tmp.name)/'db');self.db.start()
        self.book=Store('shadow_trades');db.store.ensure_observations();self.trader=PaperTrader(self.book)
        self.config=patch.object(ai,'settings',replace(settings,paper_mode=True,jev_api_key='test',jev_endpoint='https://test',gemini_api_key=''));self.config.start();self.team_config=patch.object(model_team,'settings',ai.settings);self.team_config.start();model_team._CACHE.clear()
        self.t={'mint':'test','symbol':'T','timestamp':time.time(),'price_usd':1,'sol_price_usd':100,'market_cap_usd':40000,'research':{'features':{'narrative':'unknown'},'security':{'status':'ok','danger':False}}}
        self.trader.buy(self.t,.1,{'entry_evidence':self.t})
    def tearDown(self):self.team_config.stop();self.config.stop();self.db.stop();self.tmp.cleanup()
    async def test_hold_above_profit_target_and_cached_partial_is_never_replayed(self):
        high=dict(self.t,price_usd=2,market_cap_usd=80000)
        with patch.object(ai,'ask_jev',AsyncMock(return_value={'action':'hold','reason':'Fresh buy flow supports waiting.'})) as call:
            d=await ai.decide(self.book,self.book.open()[0],high);self.assertFalse(d['exit']);call.assert_awaited_once()
            d=await ai.decide(self.book,self.book.open()[0],high);self.assertFalse(d['exit']);self.assertEqual(call.await_count,1)
        p=self.book.open()[0];past=p['exit_decision']['checked_at']
        with patch.object(ai.time,'time',return_value=past+121),patch.object(ai,'ask_jev',AsyncMock(return_value={'action':'sell_25','reason':'Take some profit, retain upside.'})):
            token=dict(high,timestamp=past+121)
            d=await ai.decide(self.book,p,token);self.assertEqual(d['fraction'],.25)
            self.assertTrue(self.trader.sell(p,token,d['reason'],d['fraction']))
            remaining=self.book.open()[0];self.assertAlmostEqual(remaining['amount_sol'],.075)
            self.assertTrue(remaining['exit_decision']['consumed'])
            self.assertFalse((await ai.decide(self.book,remaining,token))['exit'])
            self.assertFalse(self.book.consume_exit_decision(p['id'],remaining['exit_decision']['id']))
        # A new review may partially sell again, preserving cost basis and quantity.
        remaining=self.book.open()[0];at=remaining['exit_decision']['checked_at']+121
        with patch.object(ai.time,'time',return_value=at),patch.object(ai,'ask_jev',AsyncMock(return_value={'action':'sell_50','reason':'Flow deteriorated; reduce exposure.'})):
            token=dict(high,timestamp=at);d=await ai.decide(self.book,remaining,token)
            self.assertTrue(self.trader.sell(remaining,token,d['reason'],d['fraction']))
            self.assertAlmostEqual(self.book.open()[0]['amount_sol'],.0375)
            rows=self.book.all();self.assertAlmostEqual(sum(r['amount_sol'] for r in rows),.1)
            self.assertAlmostEqual(sum(r['context']['paper_fill']['quantity'] for r in rows),.1/(1+settings.paper_fee_bps/10000)*100/(1+settings.paper_slippage_bps/10000))
            captured=ai.evidence(self.book,self.book.open()[0],token)
            self.assertEqual(len(captured['past_completed_positions']),0)  # Two profitable partial fills do not make a completed winning position.
    async def test_small_repeated_trims_and_large_trim_apply_to_remainder(self):
        for action,fraction,expected in [('sell_10',.1,.09),('sell_10',.1,.081),('sell_70',.7,.0243)]:
            p=self.book.open()[0];at=max(time.time(),(p.get('exit_decision') or {}).get('checked_at',0)+121)
            token=dict(self.t,price_usd=2,timestamp=at)
            with patch.object(ai.time,'time',return_value=at),patch.object(ai,'ask_jev',AsyncMock(return_value={'action':action,'reason':'Protect profit with upside retained.'})):
                d=await ai.decide(self.book,p,token)
                self.assertEqual(d['fraction'],fraction)
                self.assertTrue(self.trader.sell(p,token,d['reason'],fraction))
                self.assertAlmostEqual(self.book.open()[0]['amount_sol'],expected)
                self.assertFalse((await ai.decide(self.book,self.book.open()[0],token))['exit'])
        self.assertAlmostEqual(sum(r['amount_sol'] for r in self.book.all()),.1)

    def test_position_history_keeps_partial_fills_and_weighted_average(self):
        p=self.book.open()[0]
        self.assertTrue(self.trader.sell(p,dict(self.t,price_usd=4,market_cap_usd=160000),'trim',.25))
        remaining=self.book.open()[0]
        self.assertTrue(self.trader.sell(remaining,dict(self.t,price_usd=1,market_cap_usd=40000),'final'))
        h=self.book.position_history(limit=1)[0]['position_history']
        self.assertEqual(len(h['fills']),2)
        self.assertAlmostEqual(h['original_amount_sol'],.1)
        self.assertEqual(h['remaining_amount_sol'],0)
        self.assertAlmostEqual(h['average_sell_market_cap_usd'],70000)
        self.assertAlmostEqual(h['realized_net_pnl_sol'],sum(x['pnl_sol'] for x in self.book.all()))
        self.assertGreater(h['realized_net_pnl_sol'],0)
        self.assertLess(h['fills'][-1]['pnl_sol'],0)
        self.assertEqual(len(self.book.position_history()),1)
        # Account boundaries remain intact, and missing caps never become invented averages.
        self.assertEqual(Store('trades').position_history(),[])
        with self.book.conn() as c:c.execute('UPDATE shadow_trades SET exit_market_cap_usd=NULL WHERE id=?',(h['fills'][0]['id'],))
        self.assertIsNone(self.book.position_history()[0]['position_history']['average_sell_market_cap_usd'])

    def test_calculated_metrics_include_costs_and_handle_missing_prices(self):
        p=dict(self.book.open()[0],peak_price_usd=2.5)
        m=ai.calculated_metrics(p,dict(self.t,price_usd=2))
        self.assertAlmostEqual(m['price_gain_from_entry_pct'],100*(2/p['entry_price_usd']-1))
        self.assertAlmostEqual(m['drawdown_from_recorded_peak_pct'],-20)
        self.assertLess(m['estimated_net_return_pct'],m['price_gain_from_entry_pct'])
        self.assertIsNone(ai.calculated_metrics(p,dict(self.t,price_usd=float('nan')))['price_gain_from_entry_pct'])
        self.assertNotIn('estimated_net_return_pct',ai.calculated_metrics(p,dict(self.t,sol_price_usd=0)))

    async def test_protective_limits_override_ai_and_stale_prices_do_not_call_ai(self):
        with patch.object(ai,'ask_jev',AsyncMock()) as call:
            self.assertEqual((await ai.decide(self.book,self.book.open()[0],dict(self.t,price_usd=.7)))['reason'],'hard stop')
            self.assertFalse((await ai.decide(self.book,self.book.open()[0],dict(self.t,timestamp=time.time()-121)))['exit'])
            self.assertTrue((await ai.decide(self.book,self.book.open()[0],dict(self.t,research={'security':{'status':'ok','danger':True}})))['exit'])
            call.assert_not_awaited()
    async def test_provider_unavailable_uses_named_fallback_and_budget_persists(self):
        with patch.object(ai,'ask_jev',AsyncMock(side_effect=RuntimeError('private secret'))):
            d=await ai.decide(self.book,self.book.open()[0],dict(self.t,price_usd=2))
            self.assertTrue(d['exit']);self.assertEqual(d['source'],'fallback')
            saved=self.book.open()[0]['exit_decision'];self.assertNotIn('private secret',str(saved));self.assertIn('RuntimeError',str(saved))
            self.assertEqual(saved['action'],'sell_all')
        from datetime import datetime,timezone
        self.assertEqual(db.store.ai_request_count('jev_exit',datetime.now(timezone.utc).date().isoformat()),1)
    def test_action_contract_is_distinct_from_entry_score(self):
        body=jev.request_body({'task':'paper_exit'},[]);self.assertIn('exit',body['questions']);self.assertEqual(body['questions']['exit']['type'],'choice');self.assertEqual(set(body['questions']['exit']['criteria']),{'hold','sell_25','sell_all'}|{'sell_'+str(n) for n in range(10,100,10)})
        self.assertEqual(jev.normalize_response({'answers':{'exit':{'type':'choice','choice':'sell_50'}}})['action'],'sell_50')
        for n in (True,1.5,'unknown',None):
            with self.assertRaises(ValueError):jev.normalize_response({'answers':{'exit':{'type':'choice','choice':n}}})
        body=gemini_review.request_body({'task':'paper_exit','mint':'test'})
        self.assertEqual(body['generationConfig']['responseSchema']['required'],['action','reason'])
        data={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps({'action':'hold','reason':'Incomplete narrative; flow stable.'})}]}}]}
        self.assertEqual(gemini_review.normalize_response(data,exit_mode=True)['action'],'hold')
        with self.assertRaises(ValueError):gemini_review.normalize_response(data)
    async def test_gemini_exit_cache_is_separate_by_task_and_account(self):
        import asyncio,httpx
        original=httpx.AsyncClient;calls=[]
        def handler(request):
            body=json.loads(request.content);calls.append(body)
            is_exit='sell_all' in body['generationConfig']['responseSchema']['properties'].get('action',{}).get('enum',[])
            answer={'action':'hold','reason':'Buy flow persists.'} if is_exit else {'score':75,'reason':'Entry evidence.'}
            return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(answer)}]}}]})
        cfg=replace(settings,gemini_api_key='test',gemini_daily_request_limit=5)
        with patch.object(gemini_review,'settings',cfg),patch.object(gemini_review,'_reviews',{}),patch.object(gemini_review,'_blocked_until',0),patch.object(gemini_review,'_semaphore',asyncio.Semaphore(1)),patch.object(gemini_review.httpx,'AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),trust_env=False,**kw)):
            await gemini_review.ask_gemini({'mint':'test'})
            gemini_review._blocked_until=0
            state={'task':'paper_exit','mint':'test','book':'shadow_trades','position':{'id':1}}
            self.assertEqual((await gemini_review.ask_gemini(state))['action'],'hold')
            self.assertTrue((await gemini_review.ask_gemini(state))['cached'])
            gemini_review._blocked_until=0
            await gemini_review.ask_gemini(dict(state,book='trades'))
            self.assertEqual(len(calls),3)
    async def test_aggressive_manager_uses_ai_full_sale(self):
        from paper import shadow
        with patch.object(shadow,'BOOK',self.book),patch.object(shadow,'TRADER',self.trader),patch.object(ai,'ask_jev',AsyncMock(return_value={'action':'sell_all','reason':'Buy flow failed.'})):
            await shadow.manage_exits([{'token':self.t}])
            self.assertEqual(self.book.open(),[])
            self.assertIn('AI exit (model-team)',self.book.all()[0]['exit_reason'])
