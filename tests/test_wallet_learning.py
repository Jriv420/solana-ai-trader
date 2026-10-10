import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
import app
import database.store as db
from database.wallet_registry import wallet_registry
from data import wallet_discovery as discovery
from data import tracked_wallets
from intelligence.wallet_learning import evaluate_evidence,normalize_transaction
A='11111111111111111111111111111111'
B='A1TMhSGzQxMr1TboBKtgixKz1sS6REASMxPo1qsyTSJd'
MINT='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'

class TradeEvidence(unittest.TestCase):
    def event(self,kind,mint='coin',quantity='10',sol='1'):
        return dict(kind=kind,mint=mint,quantity=quantity,sol=sol)
    def test_profit_requires_samples_and_multiple_tokens(self):
        one=evaluate_evidence([self.event('buy'),self.event('sell',sol='2')])
        self.assertFalse(one['qualified']);self.assertEqual(one['estimated_pnl_sol'],1)
        events=[]
        for i in range(12):events += [self.event('buy',mint=str(i%3)),self.event('sell',mint=str(i%3),sol='2')]
        learned=evaluate_evidence(events)
        self.assertTrue(learned['qualified']);self.assertEqual(learned['matched_sells'],12)
        losses=evaluate_evidence([self.event('buy'),self.event('sell',sol='.5')])
        self.assertEqual(losses['estimated_pnl_sol'],-.5)
    def test_transfers_and_unknown_cost_basis_do_not_count_as_profit(self):
        result=evaluate_evidence([self.event('sell',sol='99'),self.event('buy'),{'kind':'invalidate','mints':['coin']},self.event('sell',sol='100')])
        self.assertEqual(result['matched_sells'],0);self.assertIsNone(result['estimated_pnl_sol'])
    def test_partial_sells_apportion_cost(self):
        result=evaluate_evidence([self.event('buy',quantity='10',sol='2'),self.event('sell',quantity='5',sol='1.5'),self.event('sell',quantity='5',sol='.5')])
        self.assertEqual(result['estimated_pnl_sol'],0);self.assertEqual(result['win_rate_pct'],50)
    def test_normalizer_excludes_failed_or_ambiguous_swaps(self):
        tx={'signature':'s','parserStatus':'OK','parsed':{'transactionStatus':'OK','blockTime':1,'slot':1,'summary':{'type':'swap'},'feePayer':A,'fee':5000,'nativeTransfers':[{'fromUserAccount':A,'toUserAccount':B,'amount':1000000000}],'tokenTransfers':[{'fromUserAccount':B,'toUserAccount':A,'rawTokenAmount':10000000,'decimals':6,'mint':MINT}]}}
        event=normalize_transaction(tx,A);self.assertEqual(event['kind'],'buy');self.assertEqual(event['sol'],'1.000005')
        tx['parsed']['summary']['type']='transfer';self.assertEqual(normalize_transaction(tx,A)['kind'],'invalidate')
        tx['parsed']['transactionStatus']='ERROR';self.assertIsNone(normalize_transaction(tx,A))

class RegistryAndDiscovery(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.patch=patch.object(db,'DB',Path(self.tmp.name)/'registry.sqlite3');self.patch.start()
        db.Store().ensure_observations();wallet_registry.ensure()
        from database.research import research
        research.ensure()
        from data.social_data import ensure
        ensure()
    async def asyncTearDown(self):self.patch.stop();self.tmp.cleanup()
    async def test_whale_is_not_marked_profitable_and_disable_persists(self):
        wallet_registry.add(A);wallet_registry.position(A,MINT,'100000',30000)
        row=wallet_registry.list()[0];self.assertTrue(row['whale']);self.assertTrue(row['tracking']);self.assertFalse(row['profitable'])
        wallet_registry.disable(A);wallet_registry.add(A)
        self.assertFalse(wallet_registry.list()[0]['tracking'])
        wallet_registry.add(A,'Manual label',True);self.assertTrue(wallet_registry.list()[0]['tracking'])
        with patch.object(tracked_wallets,'settings',SimpleNamespace(tracked_wallets_json='[]')):
            self.assertEqual(tracked_wallets.configured_wallets()[0]['address'],A)
    async def test_discovery_excludes_program_owned_holders(self):
        def response(request):
            method=json.loads(request.content)['method']
            if method=='getTokenLargestAccounts':result={'value':[{'address':A},{'address':B}]}
            else:
                params=json.loads(request.content)['params']
                if params[1]['encoding']=='jsonParsed':
                    result={'value':[{'data':{'parsed':{'info':{'owner':w,'mint':MINT,'tokenAmount':{'amount':'100000000000','decimals':6}}}}} for w in (A,B)]}
                else:result={'value':[{'owner':discovery.SYSTEM,'executable':False},{'owner':MINT,'executable':False}]}
            return httpx.Response(200,json={'result':result})
        original=httpx.AsyncClient
        with patch.object(discovery,'settings',SimpleNamespace(solana_rpc_url='https://rpc.test')),patch.object(discovery.httpx,'AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(response),trust_env=False,**kw)):
            await discovery.discover_holders({'mint':MINT,'price_usd':1})
        self.assertEqual([w['address'] for w in wallet_registry.list()],[A])
    async def test_history_learning_deduplicates_and_marks_parser_failures(self):
        wallet_registry.add(A)
        def tx(signature,buy,timestamp):
            return {'signature':signature,'parserStatus':'OK','parsed':{'transactionStatus':'OK','blockTime':timestamp,'slot':timestamp,'summary':{'type':'swap'},'feePayer':A,'fee':0,'nativeTransfers':[{'fromUserAccount':A if buy else B,'toUserAccount':B if buy else A,'amount':1000000000 if buy else 2000000000}],'tokenTransfers':[{'fromUserAccount':B if buy else A,'toUserAccount':A if buy else B,'rawTokenAmount':10000000,'decimals':6,'mint':MINT}]}}
        items=[tx('sell',False,2),tx('buy',True,1)]
        original=httpx.AsyncClient
        def handler(request):return httpx.Response(200,json={'data':items})
        config=SimpleNamespace(helius_api_key='test',wallet_min_matched_sells=10)
        with patch.object(discovery,'settings',config),patch.object(discovery.httpx,'AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),trust_env=False,**kw)):
            await discovery.learn_wallet(A);await discovery.learn_wallet(A)
            profile=wallet_registry.list()[0]['profile']
            self.assertEqual(profile['matched_sells'],1);self.assertEqual(profile['estimated_pnl_sol'],1)
            self.assertEqual(len(wallet_registry.events(A)),2)
            items.insert(0,{'signature':'unparsed','parserStatus':'ERROR'})
            await discovery.learn_wallet(A)
            self.assertEqual(wallet_registry.list()[0]['profile']['data_status'],'incomplete')
            self.assertFalse(wallet_registry.list()[0]['profitable'])
    async def test_authenticated_frontend_add_and_disable(self):
        with patch.dict(os.environ,{'NEXUS_PASSWORD':'test'}),TestClient(app.app) as client,patch.object(tracked_wallets,'settings',SimpleNamespace(tracked_wallets_json='[]')):
            self.assertEqual(client.post('/api/wallets',json={'address':A}).status_code,401)
            saved=client.post('/api/wallets',json={'address':A,'label':'Pinned'},auth=('nexus','test'));self.assertEqual(saved.status_code,200)
            self.assertTrue(client.get('/api/wallets',auth=('nexus','test')).json()['items'][0]['manual'])
            self.assertEqual(client.post('/api/wallets',json={'address':B},auth=('nexus','test'),headers={'Origin':'https://other.test'}).status_code,403)
            self.assertEqual(client.delete('/api/wallets/'+A,auth=('nexus','test')).status_code,200)
            self.assertFalse(wallet_registry.list()[0]['tracking'])

if __name__=='__main__':unittest.main()
