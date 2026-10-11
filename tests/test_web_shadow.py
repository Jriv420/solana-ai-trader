import tempfile,time,unittest
import httpx
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch,AsyncMock
import database.store as db
from database.store import Store,store
from data import web_research as web
from paper import shadow
from paper.paper_trader import PaperTrader
from config.settings import settings
MINT='So11111111111111111111111111111111111111112'

class NewFeatures(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.dbpatch=patch.object(db,'DB',Path(self.tmp.name)/'test.sqlite');self.dbpatch.start()
        self.primary=Store();web.ensure();shadow.initialize();web._LAST=0;web.STATUS.clear();web.STATUS.update(status='standby',checked_at=None)
    def tearDown(self):self.dbpatch.stop();self.tmp.cleanup()
    async def test_exact_contract_sources_cache_and_attempts(self):
        response=type('Response',(),{'status_code':200,'raise_for_status':lambda self:None,'json':lambda self:{'results':[{'url':'https://example.com','title':'Copy coin','content':'same name'},{'url':'https://example.com/'+MINT,'title':'Lore','content':'Claim, not endorsement'},{'url':'javascript:bad','content':MINT}]}})()
        call=AsyncMock(return_value=response)
        original=httpx.AsyncClient
        with patch.object(web,'settings',replace(settings,tavily_api_key='secret')),patch('httpx.AsyncClient.post',call),patch('httpx.AsyncClient',side_effect=lambda **kw:original(trust_env=False,**kw)):
            a=await web.search(MINT);b=await web.search(MINT)
            self.assertEqual(a,b);self.assertEqual(len(a['sources']),1);self.assertFalse(a['sources'][0]['endorsement_verified']);self.assertEqual(call.await_count,1)
            self.assertEqual(web.usage()['requests_today'],1)
            body=call.call_args.kwargs['json'];self.assertEqual(body['search_depth'],'basic');self.assertFalse(body['auto_parameters'])
    async def test_failed_search_counted_and_daily_cap(self):
        with patch.object(web,'settings',replace(settings,tavily_api_key='secret')),patch('httpx.AsyncClient.post',AsyncMock(side_effect=RuntimeError('secret'))):
            r=await web.search(MINT);self.assertEqual(r['status'],'unavailable');self.assertEqual(web.usage()['requests_today'],1)
            day=web.usage()['day'] if 'day' in web.usage() else __import__('datetime').datetime.now(__import__('datetime').timezone.utc).date().isoformat()
            for _ in range(24):store.reserve_ai_request('tavily',day,25)
            web._LAST=0
            other='11111111111111111111111111111111'
            self.assertEqual((await web.search(other))['request_status'],'budget_paused')
    async def test_monthly_cap(self):
        day=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).date().isoformat()
        store.ai_request_count('tavily',day)
        with store.conn() as c:c.execute('INSERT INTO ai_requests VALUES(?,?,750)',('tavily',day[:7]+'-01'))
        with patch.object(web,'settings',replace(settings,tavily_api_key='secret')),patch('httpx.AsyncClient.post',AsyncMock()) as call:
            self.assertEqual((await web.search(MINT))['request_status'],'budget_paused');call.assert_not_awaited()
    async def test_provider_quota_pauses_new_searches(self):
        original=httpx.AsyncClient
        def handler(request):return httpx.Response(432,json={'error':'quota'})
        with patch.object(web,'settings',replace(settings,tavily_api_key='secret')),patch('httpx.AsyncClient',side_effect=lambda **kw:original(trust_env=False,transport=httpx.MockTransport(handler),**kw)):
            self.assertEqual((await web.search(MINT))['status'],'provider_quota_or_auth_paused')
            web._LAST=0
            self.assertEqual((await web.search('11111111111111111111111111111111'))['request_status'],'provider_quota_or_auth_paused')
            self.assertEqual(web.usage()['requests_today'],1)
    def token(self):return {'mint':MINT,'symbol':'TEST','price_usd':1,'sol_price_usd':100,'timestamp':time.time(),'liquidity_usd':10000,'volume_5m_usd':5000,'price_change_5m_pct':10,'buys_5m':20,'sells_5m':10,'research':{'security':{'status':'ok','danger':False},'bundle':{'status':'indicators_found'}}}
    def test_shadow_isolated_and_same_fill_costs(self):
        t=self.token()
        with patch.object(shadow,'settings',replace(settings,paper_mode=True)):
            result=shadow.step([{'token':t},{'token':t}]);self.assertEqual(result['paper_buys'],1);self.assertEqual(self.primary.open(),[])
            p=shadow.BOOK.open()[0];self.assertEqual(p['context']['paper_fill']['fee_bps'],settings.paper_fee_bps)
            self.assertEqual(shadow.step([{'token':t}])['paper_buys'],0)
            self.assertTrue(shadow.TRADER.sell(p,t,'test'))
            self.assertLess(shadow.BOOK.realized(),0);self.assertEqual(self.primary.realized(),0)
            self.assertEqual(shadow.step([{'token':t}])['paper_buys'],0)
    def test_shadow_security_freshness_and_position_limit(self):
        t=self.token()
        for s in ({'status':'pending'},{'status':'ok','danger':True}):self.assertFalse(shadow.eligible(dict(t,research={'security':s}))[0])
        self.assertFalse(shadow.eligible(dict(t,timestamp=time.time()-130))[0]);self.assertFalse(shadow.eligible(dict(t,price_usd=float('nan')))[0])
        with patch.object(shadow,'settings',replace(settings,paper_mode=True)):
            tokens=[{'token':dict(t,mint=MINT[:-1]+'23456'[i])} for i in range(5)]
            shadow.step(tokens);self.assertEqual(len(shadow.BOOK.open()),3)
    def test_shadow_expiration_and_live_disabled(self):
        t=self.token()
        with store.conn() as c:c.execute('UPDATE shadow_meta SET ends_at=?',(time.time()-1,))
        with patch.object(shadow,'settings',replace(settings,paper_mode=True)):
            self.assertEqual(shadow.step([{'token':t}])['paper_buys'],0)
            self.assertFalse(shadow.summary()['active'])
        with store.conn() as c:c.execute('UPDATE shadow_meta SET ends_at=?',(time.time()+1000,))
        with patch.object(shadow,'settings',replace(settings,paper_mode=False)):
            self.assertEqual(shadow.step([{'token':t}])['paper_buys'],0)
