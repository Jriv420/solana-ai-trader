import unittest
import tempfile
from pathlib import Path
import database.store as db
from database.wallet_registry import wallet_registry
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from data import tracked_wallets as tracked

MINT='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
A='11111111111111111111111111111111'
B='A1TMhSGzQxMr1TboBKtgixKz1sS6REASMxPo1qsyTSJd'

def account(owner,amount):
    return {'account':{'data':{'parsed':{'info':{'owner':owner,'mint':MINT,'tokenAmount':{'amount':str(amount),'decimals':6}}}}}}

class TrackedWalletHoldings(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.dbpatch=patch.object(db,'DB',Path(self.tmp.name)/'wallets.sqlite3');self.dbpatch.start()
        wallet_registry.ensure()
        tracked._cache.clear();tracked._inflight.clear()
        self.config=SimpleNamespace(tracked_wallets_json='["'+A+'","'+B+'"]',solana_rpc_url='https://rpc.test')
        self.settings=patch.object(tracked,'settings',self.config);self.settings.start()
    async def asyncTearDown(self):self.settings.stop();self.dbpatch.stop();self.tmp.cleanup()
    def client(self,handler):
        transport=httpx.MockTransport(handler)
        original=httpx.AsyncClient
        return patch.object(tracked.httpx,'AsyncClient',side_effect=lambda **kw:original(transport=transport,trust_env=False,**kw))
    async def test_sum_accounts_exclude_zero_and_cache(self):
        calls=[]
        def handler(request):
            import json
            owner=json.loads(request.content)['params'][0];calls.append(owner)
            values=[account(A,1000000),account(A,250000)] if owner==A else [account(B,0)]
            return httpx.Response(200,json={'result':{'value':values}})
        with self.client(handler):
            result=await tracked.get_tracked_wallet_holders(MINT)
            self.assertEqual(result['status'],'ok');self.assertEqual(len(result['holders']),1)
            self.assertEqual(result['holders'][0]['balance'],'1.25')
            again=await tracked.get_tracked_wallet_holders(MINT)
            self.assertEqual(again,result);self.assertEqual(len(calls),2)
    async def test_partial_failure_not_reported_as_no_holdings(self):
        def handler(request):
            import json
            owner=json.loads(request.content)['params'][0]
            return httpx.Response(200,json={'error':{'message':'rate limited'}} if owner==B else {'result':{'value':[]}})
        with self.client(handler):
            result=await tracked.get_tracked_wallet_holders(MINT)
        self.assertEqual(result['status'],'partial');self.assertEqual(result['checked_count'],1)
        self.assertEqual(result['unavailable_wallets'][0]['address'],B)
    async def test_unconfigured_and_bad_addresses(self):
        self.config.tracked_wallets_json='[]'
        self.assertEqual((await tracked.get_tracked_wallet_holders(MINT))['status'],'not_configured')
        self.config.tracked_wallets_json='["not-a-wallet"]'
        self.assertEqual((await tracked.get_tracked_wallet_holders(MINT))['status'],'invalid_configuration')
        with self.assertRaises(ValueError):await tracked.get_tracked_wallet_holders('invalid-mint')
    async def test_bad_owner_is_failed_check(self):
        def handler(request):return httpx.Response(200,json={'result':{'value':[account('unexpected-owner',1000000)]}})
        with self.client(handler):result=await tracked.get_tracked_wallet_holders(MINT)
        self.assertEqual(result['status'],'unavailable');self.assertEqual(result['holders'],[])

if __name__=='__main__':unittest.main()
