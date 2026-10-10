import os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import app
import database.store as db
from database.store import Store
from dashboard_auth import session,valid_session,_attempts

class DashboardAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=patch.object(db,'DB',Path(self.temp.name)/'db.sqlite3');self.db.start()
        Store().ensure_observations()
        self.env=patch.dict(os.environ,{'NEXUS_PASSWORD':'test-pass'});self.env.start();_attempts.clear()
        self.client=TestClient(app.app,base_url='https://testserver')
    def tearDown(self):
        self.client.close();self.env.stop();self.db.stop();self.temp.cleanup()
    def test_login_then_protected_page_without_basic_popup(self):
        response=self.client.get('/',follow_redirects=False)
        self.assertEqual(response.status_code,303);self.assertEqual(response.headers['location'],'/login')
        self.assertIn('Dashboard password',self.client.get('/login').text)
        self.assertEqual(self.client.get('/api/trades').status_code,401)
        response=self.client.post('/login',data={'password':'test-pass'},follow_redirects=False)
        self.assertEqual(response.status_code,303)
        cookie=response.headers['set-cookie'];self.assertIn('HttpOnly',cookie);self.assertIn('Secure',cookie);self.assertIn('SameSite=strict',cookie)
        self.assertEqual(self.client.get('/api/trades').status_code,200)
        self.assertIn('NEXUS',self.client.get('/').text)
        self.assertEqual(self.client.post('/api/connections/check',headers={'origin':'https://evil.test'}).status_code,403)
        self.assertEqual(self.client.post('/api/connections/check').status_code,403)
    def test_wrong_password_cross_origin_and_rate_limit(self):
        self.assertEqual(self.client.post('/login',data={'password':'test-pass'},headers={'origin':'https://evil.test'}).status_code,403)
        for i in range(10):
            response=self.client.post('/login',data={'password':'wrong'},follow_redirects=False)
            self.assertEqual(response.headers['location'],'/login?error=password')
        response=self.client.post('/login',data={'password':'wrong'},follow_redirects=False)
        self.assertEqual(response.headers['location'],'/login?error=rate')
    def test_signed_expiring_cookie_and_password_rotation(self):
        token=session('test-pass',now=1000)
        self.assertTrue(valid_session(token,'test-pass',now=1001))
        for value,password,now in ((token+'x','test-pass',1001),(token,'rotated',1001),(token,'test-pass',50000),(token,'test-pass',999),(None,'test-pass',1001)):
            self.assertFalse(valid_session(value,password,now))
