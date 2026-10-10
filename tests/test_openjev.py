import asyncio,unittest
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from intelligence import jev
from intelligence.decision_engine import _score

class OpenJev(unittest.TestCase):
    def test_trial_market_evidence_does_not_require_wallets(self):
        normal=jev.request_body({},[])
        trial=jev.request_body({'paper_risk_trial':{'active':True}},[])
        self.assertIn('optional',trial['questions']['setup']['criteria'][3])
        self.assertEqual(normal['questions']['setup']['criteria'],jev.LEVELS)
        self.assertEqual(len(trial['questions']['setup']['criteria']),len(jev.LEVELS))

    def test_native_question_map_and_score_normalization(self):
        body=jev.request_body({'volume':50},['Missing information remains unknown.'])
        self.assertEqual(body['model'],'openjev')
        self.assertEqual(body['questions']['setup']['type'],'score')
        self.assertEqual(len(body['questions']['setup']['criteria']),5)
        result=jev.normalize_response({'answers':{'setup':{'type':'score','score':3,'confidence':.99}}})
        self.assertEqual(result['score'],75);self.assertEqual(_score(result),75)
        self.assertEqual(jev.normalize_response({'answers':{'setup':{'type':'score','score':0,'confidence':1}}})['score'],0)
    def test_malformed_and_nonfinite_answers_are_rejected(self):
        for value in ({},{'error':'bad'},{'answers':{'setup':{'type':'noul','noul':1}}}):
            with self.assertRaises(ValueError):jev.normalize_response(value)
        for score in (True,float('nan'),float('inf'),-1,5,'3'):
            with self.assertRaises(ValueError):jev.normalize_response({'answers':{'setup':{'type':'score','score':score}}})
    def test_http_contract_and_rate_limit_cooldown(self):
        calls=[]
        def handler(request):
            import json
            calls.append(request);self.assertEqual(request.headers['Authorization'],'Bearer test-key')
            self.assertIsInstance(json.loads(request.content)['questions'],dict)
            if len(calls)==1:return httpx.Response(200,json={'answers':{'setup':{'type':'score','score':2}}})
            return httpx.Response(429,headers={'Retry-After':'120'})
        original=httpx.AsyncClient;transport=httpx.MockTransport(handler)
        async def exercise():
            with patch.object(jev,'settings',SimpleNamespace(jev_api_key='test-key',jev_endpoint='https://api.openjev.sh/v1/systemone',jev_timeout_ms=10000)),patch.object(jev,'_semaphore',asyncio.Semaphore(1)),patch.object(jev,'_blocked_until',0),patch.object(jev.httpx,'AsyncClient',side_effect=lambda **kw:original(transport=transport,**kw)):
                self.assertEqual((await jev.ask_jev({},[]))['score'],50)
                with self.assertRaises(httpx.HTTPStatusError):await jev.ask_jev({},[])
                with self.assertRaises(RuntimeError):await jev.ask_jev({},[])
                self.assertEqual(len(calls),2)
        asyncio.run(exercise())
