import asyncio,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
import httpx
import database.store as db
from intelligence import gemini_review as ai,decision_engine as engine

def response(score=75,finish='STOP'):
    return {'modelVersion':'gemini-3.5-flash-lite','candidates':[{'finishReason':finish,'content':{'parts':[
        {'thought':True,'text':'ignore internal thinking'},
        {'text':json.dumps({'score':score,'reason':'Wallet evidence remains incomplete.'})}]}}]}

class GeminiReview(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.dbpatch=patch.object(db,'DB',Path(self.tmp.name)/'test.sqlite3');self.dbpatch.start()
        self.config=SimpleNamespace(gemini_api_key='private-test-key',gemini_model='gemini-3.5-flash-lite',
            gemini_endpoint='https://generativelanguage.googleapis.com/v1beta/models/',gemini_timeout_ms=15000,
            gemini_daily_request_limit=2,openai_api_key='also-configured')
        self.configpatch=patch.object(ai,'settings',self.config);self.configpatch.start()
        ai._reviews.clear();engine._CACHE.clear()
    def tearDown(self):self.configpatch.stop();self.dbpatch.stop();self.tmp.cleanup()
    def test_blocked_incomplete_nonfinite_and_tool_answers_rejected(self):
        self.assertEqual(ai.normalize_response(response(0))['score'],0)
        for score in (True,-1,101,'50',float('nan')):
            with self.assertRaises(ValueError):ai.normalize_response(response(score))
        for data in ({'promptFeedback':{'blockReason':'SAFETY'}},response(finish='MAX_TOKENS'),{}):
            with self.assertRaises(ValueError):ai.normalize_response(data)
        data=response();data['candidates'][0]['content']['parts'].append({'functionCall':{}})
        with self.assertRaises(ValueError):ai.normalize_response(data)
        with self.assertRaises(ai.ReviewPaused):ai.request_body({'note':'x'*12001})
    def test_header_contract_cache_spacing_and_persistent_cap(self):
        calls=[];original=httpx.AsyncClient
        def handler(request):
            calls.append(request);body=json.loads(request.content)
            self.assertEqual(request.headers['x-goog-api-key'],'private-test-key')
            self.assertNotIn('private-test-key',str(request.url));self.assertNotIn('tools',body)
            self.assertEqual(body['generationConfig']['responseMimeType'],'application/json')
            self.assertEqual(body['generationConfig']['maxOutputTokens'],1000)
            self.assertIn('systemInstruction',body)
            return httpx.Response(200,json=response())
        async def exercise():
            with patch.object(ai,'_semaphore',asyncio.Semaphore(1)),patch.object(ai,'_blocked_until',0),patch.object(ai.httpx,'AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),**kw)):
                await ai.ask_gemini({'mint':'coin'})
                self.assertTrue((await ai.ask_gemini({'mint':'coin'}))['cached'])
                with self.assertRaises(ai.ReviewPaused) as exc:await ai.ask_gemini({'connection_test':True})
                self.assertEqual(exc.exception.status,'cooldown')
                ai._blocked_until=0;await ai.ask_gemini({'connection_test':True})
                ai._blocked_until=0
                with self.assertRaises(ai.ReviewPaused) as exc:await ai.ask_gemini({'mint':'other'})
                self.assertEqual(exc.exception.status,'daily_limit_reached');self.assertEqual(len(calls),2)
                self.assertEqual(ai.usage()['requests_today'],2)
        asyncio.run(exercise())
    def test_quota_error_redacted_and_no_immediate_retry(self):
        original=httpx.AsyncClient;calls=[]
        def handler(request):calls.append(request);return httpx.Response(429,json={'error':{'message':'private-test-key'}})
        async def exercise():
            with patch.object(ai,'_semaphore',asyncio.Semaphore(1)),patch.object(ai,'_blocked_until',0),patch.object(ai.httpx,'AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),**kw)):
                self.assertIsNone(await engine.provider_result('gemini',{}))
                self.assertEqual(engine.CONNECTIONS['gemini']['status'],'provider_quota_or_capacity')
                self.assertIsNone(await engine.provider_result('gemini',{}))
                self.assertEqual(len(calls),1);self.assertNotIn('private-test-key',json.dumps(engine.CONNECTIONS))
        asyncio.run(exercise())
    def test_gemini_preferred_and_no_paid_openai_fallback(self):
        async def exercise():
            with patch('config.settings.settings',self.config),patch.object(engine,'ask_jev',AsyncMock(return_value={'score':80})),patch.object(engine,'ask_gemini',AsyncMock(return_value={'score':40})) as review,patch.object(engine,'ask_openai',AsyncMock()) as paid:
                result=await engine.evaluate_fast({'mint':'coin'})
                self.assertEqual(result['score'],40);self.assertIn('gemini_review',result);paid.assert_not_awaited()
                engine._CACHE.clear();review.side_effect=ai.ReviewPaused('provider_quota_or_capacity')
                self.assertEqual((await engine.evaluate_fast({'mint':'coin'}))['score'],80);paid.assert_not_awaited()
        asyncio.run(exercise())
    def test_zero_limit_disables_even_cached_reviews(self):
        self.config.gemini_daily_request_limit=0
        ai._reviews['coin']=(__import__('time').time(),{'score':80})
        with self.assertRaises(ai.ReviewPaused):asyncio.run(ai.ask_gemini({'mint':'coin'}))
