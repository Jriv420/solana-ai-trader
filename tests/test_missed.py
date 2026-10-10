import tempfile,time,unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import database.store as db
from database.missed import missed
from strategy.paper_exception import eligible,decide
from config.settings import settings

class MissedTests(unittest.TestCase):
    def test_first_rejection_and_losers_preserved(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(db,'DB',Path(folder)/'test.sqlite'):
            missed.ensure();now=time.time()
            token={'mint':'winner','price_usd':100,'timestamp':now,'volume_5m_usd':100}
            missed.observe(token,['wallet score below threshold'],now)
            token.update(price_usd=200,timestamp=now+300,volume_5m_usd=999)
            missed.observe(token,['other reason'],now+300)
            loser=dict(token,mint='loser',price_usd=100,timestamp=now)
            missed.observe(loser,['wallet score below threshold'],now)
            loser.update(price_usd=50,timestamp=now+300);missed.observe(loser,[],now+300)
            data=missed.summary();self.assertEqual(len(data['surges']),1)
            self.assertEqual(data['surges'][0]['at_rejection']['volume_5m_usd'],100)
            self.assertEqual(data['by_reason'][0]['distinct_coins'],2)
            self.assertEqual(data['by_reason'][0]['surged_50_pct'],50)
            self.assertEqual(data['by_reason'][0]['fell_30_pct'],50)
            self.assertEqual(missed.mints(now+400),['winner','loser'])
            self.assertEqual(missed.mints(now+90000),[])
    def test_unknown_security_and_rules_cannot_override(self):
        token={'research':{'security':{'status':'ok','danger':False}},'price_usd':1,'liquidity_usd':50000,'volume_5m_usd':5000,'buys_5m':20,'sells_5m':5}
        f={'reasons':['revival threshold']};e={'reasons':['wallet threshold']}
        with patch('strategy.paper_exception.settings',replace(settings,paper_mode=True)):
            self.assertTrue(decide(token,f,e,{'provider':'jev','score':75},35)['allowed'])
            self.assertFalse(decide(token,f,e,{'provider':'deterministic-fallback','score':100},35)['allowed'])
            self.assertFalse(decide(token,f,e,{'provider':'jev','score':75},100)['allowed'])
            for security in ({'status':'pending'},{'status':'ok','danger':True}):
                self.assertFalse(eligible(dict(token,research={'security':security}),f))
            self.assertTrue(eligible(dict(token,identity_check={'status':'ambiguous'}),f))
            self.assertFalse(eligible(dict(token,liquidity_usd=10),f))
        with patch('strategy.paper_exception.settings',replace(settings,paper_mode=False)):self.assertFalse(eligible(token,f))
