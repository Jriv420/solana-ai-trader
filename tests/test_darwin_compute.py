import asyncio,json,unittest,tempfile
from pathlib import Path
import database.store as db
from dataclasses import replace
from unittest.mock import patch
import httpx
from config.settings import settings
from intelligence import darwin
class DarwinCompute(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=patch.object(db,'DB',Path(self.tmp.name)/'db');self.db.start()
    def tearDown(self):self.db.stop();self.tmp.cleanup()
    def response(self,answer=None,**extra):
        return dict({'model':'reported-model','choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer or {'score':70,'action':'sell_10','reason':'Profit protection'})}}]},**extra)
    def test_native_payload_and_routed_identity(self):
        body=darwin.request_body('Review',{'task':'paper_exit','mint':'A'})
        self.assertEqual(body['model'],'darwin');self.assertIn('messages',body);self.assertNotIn('data',body)
        result=darwin.normalize_response(self.response(),{'x-darwin-model':'gpu/model','x-darwin-rung':'2'})
        self.assertEqual(result['actual_model'],'gpu/model');self.assertEqual(result['routing_rung'],'2');self.assertEqual(result['action'],'sell_10')
    def test_incomplete_invalid_and_tool_responses_rejected(self):
        for answer in ({'score':float('nan'),'action':'hold','reason':'x'},{'score':True,'action':'hold','reason':'x'},{'score':70,'action':'invented','reason':'x'},{'score':70,'action':'hold','reason':''}):
            with self.assertRaises(ValueError):darwin.normalize_response(self.response(answer))
        r=self.response();r['choices'][0]['finish_reason']='length'
        with self.assertRaises(ValueError):darwin.normalize_response(r)
        r=self.response();r['choices'][0]['message']['tool_calls']=[{}]
        with self.assertRaises(ValueError):darwin.normalize_response(r)
    async def test_real_wire_format_and_no_credit_cooldown(self):
        original=httpx.AsyncClient;requests=[]
        def handler(request):
            requests.append(request);return httpx.Response(402,json={'error':'No credits'})
        with patch.object(darwin,'settings',replace(settings,darwin_api_key='test-private-key',darwin_endpoint='https://test/v1/chat/completions')),patch.object(darwin,'_blocked_until',0),patch.object(darwin,'_semaphore',asyncio.Semaphore(1)),patch.object(darwin.httpx,'AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),trust_env=False,**kw)):
            with self.assertRaises(darwin.ReviewPaused) as e:await darwin.ask_darwin('test',{'connection_test':True})
            self.assertEqual(e.exception.status,'darwin_credits_required')
            with self.assertRaises(darwin.ReviewPaused) as e:await darwin.ask_darwin('test',{})
            self.assertEqual(e.exception.status,'cooldown');self.assertEqual(len(requests),1)
            from datetime import datetime,timezone
            self.assertEqual(db.store.ai_request_count('darwin_http',datetime.now(timezone.utc).date().isoformat()),1)
            self.assertEqual(requests[0].headers['authorization'],'Bearer test-private-key');self.assertIn('messages',json.loads(requests[0].content))
