import asyncio,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import database.store as db
from database.store import Store
from paper.paper_trader import PaperTrader
from paper import accounts
from intelligence.trade_evaluation import shared_lessons

class PaperAccounts(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.patch=patch.object(db,'DB',Path(self.tmp.name)/'db');self.patch.start()
  self.original=Store('trades');self.aggressive=Store('shadow_trades')
  self.token={'mint':'example','symbol':'TEST','price_usd':1,'sol_price_usd':100,'timestamp':time.time()}
 def tearDown(self):self.patch.stop();self.tmp.cleanup()
 def test_stop_is_independent_persistent_and_exits_still_fill(self):
  original=PaperTrader(self.original);aggressive=PaperTrader(self.aggressive)
  position=aggressive.buy(self.token,.05,{});self.assertIsNotNone(position)
  accounts.set_enabled('aggressive',False)
  self.assertFalse(accounts.enabled('shadow_trades'));self.assertTrue(accounts.enabled('trades'))
  self.assertIsNone(aggressive.buy(dict(self.token,mint='other'),.05,{}))
  self.assertIsNotNone(original.buy(dict(self.token,mint='original'),.05,{}))
  position=self.aggressive.open()[0]
  self.assertTrue(aggressive.sell(position,self.token,'hard stop'))
  accounts.ensure();self.assertFalse(accounts.enabled('shadow_trades'))
  accounts.set_enabled('aggressive',True)
  self.assertIsNotNone(aggressive.buy(dict(self.token,mint='restarted'),.05,{}))
 def test_shared_lessons_retain_account_source_and_ignore_future_and_open(self):
  for book,mint,when in [(self.original,'original',time.time()-1),(self.aggressive,'aggressive',time.time()-1),(self.original,'future',time.time()+100)]:
   p=book.create_trade({'mint':mint,'entry_price_usd':1,'amount_sol':.1,'entry_time':time.time()-100,'context':{'paper_fill':{'version':1}}})
   book.close_trade(p['id'],1.1,when,10,.01,'test')
  lesson=shared_lessons();self.assertEqual({x['book'] for x in lesson['positions']},{'trades','shadow_trades'})
  self.assertNotIn('future',{x['mint'] for x in lesson['positions']})
 def test_invalid_controls_rejected(self):
  with self.assertRaises(ValueError):accounts.set_enabled('live',True)
  with self.assertRaises(ValueError):accounts.set_enabled('original','false')

 def test_api_controls_require_login_and_reject_cross_origin(self):
  from fastapi.testclient import TestClient
  import app
  from dataclasses import replace
  import os
  with patch.dict(os.environ,{'NEXUS_PASSWORD':'test-control-password'}),patch.object(app,'settings',replace(app.settings,paper_mode=True)):
   client=TestClient(app.app)
   path='/api/paper-accounts/aggressive/control'
   self.assertEqual(client.post(path,json={'entries_enabled':False}).status_code,401)
   response=client.post(path,json={'entries_enabled':False},auth=('nexus','test-control-password'))
   self.assertEqual(response.status_code,200);self.assertFalse(response.json()['account_controls']['aggressive']['entries_enabled'])
   self.assertTrue(response.json()['account_controls']['original']['entries_enabled'])
   response=client.post(path,json={'entries_enabled':True},auth=('nexus','test-control-password'),headers={'origin':'https://foreign.example'})
   self.assertEqual(response.status_code,403);self.assertFalse(accounts.enabled('shadow_trades'))
