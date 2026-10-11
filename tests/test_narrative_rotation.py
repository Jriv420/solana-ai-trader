import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch,AsyncMock
import database.store as db
from database.store import Store
from paper.paper_trader import PaperTrader
from strategy.exit import should_exit
from data import narrative_trends as trends
from config.settings import settings
from dataclasses import replace
class Rotation(unittest.IsolatedAsyncioTestCase):
    async def test_meta_membership_is_exact_not_a_name_match(self):
        def response(payload):
            return type('R',(),{'raise_for_status':lambda s:None,'json':lambda s:payload})()
        replies=[response([{'slug':'elon'}]),response({'name':'Elon','pairs':[{'chainId':'solana','baseToken':{'address':'leader','symbol':'ELON'},'marketCap':3000000,'priceChange':{'h1':10}},{'chainId':'solana','baseToken':{'address':'small','symbol':'SPACEX'},'marketCap':40000}]})]
        import httpx
        client=httpx.AsyncClient
        with patch.object(client,'get',AsyncMock(side_effect=replies)) as call,patch('httpx.AsyncClient',side_effect=lambda **kw:client(trust_env=False,**kw)),patch.dict(trends.STATE,{'checked_at':0,'status':'not_checked','themes':[]}):
            await trends.refresh();await trends.refresh()
            self.assertEqual(call.await_count,2)
            self.assertTrue(trends.context({'mint':'small','market_cap_usd':40000,'age_minutes':5})['small_cap_rotation_candidate'])
            self.assertFalse(trends.context({'mint':'copy','symbol':'SPACEX','market_cap_usd':40000,'age_minutes':5})['small_cap_rotation_candidate'])
            self.assertFalse(trends.context({'mint':'small','market_cap_usd':40000,'market_cap_is_fdv':True,'age_minutes':5})['small_cap_rotation_candidate'])
    async def test_partial_fill_preserves_cash_quantity_and_account_isolation(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(db,'DB',Path(tmp)/'db'):
            a=Store();b=Store('shadow_trades');trader=PaperTrader(b)
            t={'mint':'test','symbol':'T','timestamp':time.time(),'price_usd':1,'sol_price_usd':100,'market_cap_usd':40000,'research':{'narrative_rotation':{'small_cap_rotation_candidate':True}}}
            p=trader.buy(t,.1,{});p=b.open()[0];quantity=p['context']['paper_fill']['quantity'];initial=trader.balance_sol()
            high=dict(t,price_usd=2)
            d=should_exit(p,high);self.assertEqual(d['fraction'],.5)
            self.assertTrue(trader.sell(p,high,d['reason'],fraction=.5))
            self.assertFalse(trader.sell(p,high,d['reason'],fraction=.5))
            remaining=b.open()[0];closed=[r for r in b.all() if r['status']=='closed'][0]
            self.assertAlmostEqual(remaining['amount_sol'],.05);self.assertAlmostEqual(remaining['context']['paper_fill']['quantity'],quantity/2)
            self.assertAlmostEqual(trader.balance_sol(),initial+.05+closed['pnl_sol']);self.assertEqual(a.all(),[])
            self.assertFalse(should_exit(remaining,high)['exit'])
            self.assertTrue(trader.sell(remaining,high,'test final'));self.assertEqual(len(b.open()),0)
            self.assertAlmostEqual(trader.balance_sol(),settings.paper_starting_sol+b.realized())
    async def test_hard_stops_and_normal_full_exits_still_apply(self):
        p={'entry_price_usd':1,'entry_time':time.time(),'context':{'paper_narrative_scaleout':True}}
        t={'price_usd':.7,'timestamp':time.time()}
        self.assertEqual(should_exit(p,t)['reason'],'hard stop')
        p['context']={};t['price_usd']=2
        self.assertEqual(should_exit(p,t)['reason'],'take profit');self.assertNotIn('fraction',should_exit(p,t))
        with patch('strategy.exit.settings',replace(settings,paper_mode=False)):
            t['research']={'narrative_rotation':{'small_cap_rotation_candidate':True}}
            self.assertNotIn('fraction',should_exit(p,t))
