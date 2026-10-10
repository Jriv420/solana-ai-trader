import asyncio,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
import httpx
import database.store as db
from intelligence import openai_review as ai,decision_engine as engine

def response(score=75,status='completed'):
    return {'status':status,'model':'test-model','output':[{'type':'message','content':[
        {'type':'output_text','text':json.dumps({'score':score,'reason':'Supplied wallet evidence only.'})}]}]}

class OpenAIReview(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.dbpatch=patch.object(db,'DB',Path(self.tmp.name)/'test.sqlite3');self.dbpatch.start()
        self.config=SimpleNamespace(openai_api_key='private-test-key',openai_model='gpt-5.6-terra',
            openai_endpoint='https://api.openai.com/v1/responses',openai_timeout_ms=15000,openai_daily_request_limit=2)
        self.configpatch=patch.object(ai,'settings',self.config);self.configpatch.start()
        ai._reviews.clear();engine._CACHE.clear()
    def tearDown(self):self.configpatch.stop();self.dbpatch.stop();self.tmp.cleanup()
    def test_strict_response_rejects_refusal_incomplete_and_invalid_scores(self):
        self.assertEqual(engine._score(ai.normalize_response(response(0))),0)
        for value in (True,-1,101,'75',float('nan')):
            with self.assertRaises(ValueError):ai.normalize_response(response(value))
        with self.assertRaises(ValueError):ai.normalize_response(response(status='incomplete'))
        with self.assertRaises(ValueError):ai.normalize_response({'status':'completed','output':[
            {'type':'message','content':[{'type':'refusal'}]}]})
        with self.assertRaises(ai.ReviewPaused):ai.request_body({'note':'x'*12001})
    def test_quota_is_atomic_and_survives_store_recreation(self):
        self.assertTrue(db.Store().reserve_ai_request('openai','2026-10-10',1))
        self.assertFalse(db.Store().reserve_ai_request('openai','2026-10-10',1))
        self.assertEqual(db.Store().ai_request_count('openai','2026-10-10'),1)
        self.assertTrue(db.Store().reserve_ai_request('openai','2026-10-11',1))
        self.assertFalse(db.Store().reserve_ai_request('openai','2026-10-12',0))
    def test_http_contract_caching_and_daily_cap(self):
        calls=[]
        def handler(request):
            calls.append(request);body=json.loads(request.content)
            self.assertEqual(request.headers['Authorization'],'Bearer private-test-key')
            self.assertFalse(body['store']);self.assertEqual(body['max_output_tokens'],1000)
            self.assertTrue(body['text']['format']['strict']);self.assertNotIn('tools',body)
            return httpx.Response(200,json=response())
        original=httpx.AsyncClient
        async def exercise():
            with patch.object(ai,'_semaphore',asyncio.Semaphore(1)),patch.object(ai,'_blocked_until',0),patch.object(ai.httpx,'AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),**kw)):
                await ai.ask_openai({'mint':'coin'})
                self.assertTrue((await ai.ask_openai({'mint':'coin'}))['cached'])
                await ai.ask_openai({'connection_test':True})
                with self.assertRaises(ai.ReviewPaused) as exc:await ai.ask_openai({'mint':'another'})
                self.assertEqual(exc.exception.status,'daily_limit_reached');self.assertEqual(len(calls),2)
        asyncio.run(exercise())
    def test_failures_count_and_cooldown_prevents_retry(self):
        calls=[];original=httpx.AsyncClient
        def handler(request):calls.append(request);return httpx.Response(429,headers={'Retry-After':'120'})
        async def exercise():
            with patch.object(ai,'_semaphore',asyncio.Semaphore(1)),patch.object(ai,'_blocked_until',0),patch.object(ai.httpx,'AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),**kw)):
                with self.assertRaises(httpx.HTTPStatusError):await ai.ask_openai({})
                with self.assertRaises(ai.ReviewPaused):await ai.ask_openai({})
                self.assertEqual(len(calls),1);self.assertEqual(ai.usage()['requests_today'],1)
        asyncio.run(exercise())
    def test_second_opinion_only_lowers_and_failure_preserves_baseline(self):
        state={'mint':'coin'}
        async def exercise():
            with patch('config.settings.settings',self.config),patch.object(engine,'ask_jev',AsyncMock(return_value={'score':80})),patch.object(engine,'ask_openai',AsyncMock(return_value={'score':95})) as review:
                result=await engine.evaluate_fast(state);self.assertEqual(result['score'],80);review.assert_awaited_once()
                engine._CACHE.clear();review.return_value={'score':40}
                self.assertEqual((await engine.evaluate_fast(state))['score'],40)
                engine._CACHE.clear();review.side_effect=ai.ReviewPaused('daily_limit_reached')
                self.assertEqual((await engine.evaluate_fast(state))['score'],80)
                self.assertEqual(engine.CONNECTIONS['openai']['status'],'daily_limit_reached')
            engine._CACHE.clear()
            with patch('config.settings.settings',self.config),patch.object(engine,'ask_jev',AsyncMock(return_value={'score':30})),patch.object(engine,'ask_openai',AsyncMock()) as review:
                self.assertEqual((await engine.evaluate_fast(state))['score'],30);review.assert_not_awaited()
        asyncio.run(exercise())
