import os,unittest
from unittest.mock import patch
from dataclasses import replace
from config.settings import settings,trading_settings
from strategy.entry import should_enter
from strategy.sizing import position_size_sol
from strategy.risk import hard_risk_check

class RiskTrialTests(unittest.TestCase):
    def test_expiry_restart_and_paper_only(self):
        with patch.dict(os.environ,{'PAPER_RISK_TRIAL_UNTIL':'200'}):
            self.assertEqual(trading_settings(now=100).min_liquidity_usd,5000)
            self.assertEqual(trading_settings(now=150).max_trade_sol,.1)
            self.assertIs(trading_settings(now=200),settings)
            self.assertIs(trading_settings(replace(settings,paper_mode=False),now=100).paper_mode,False)
            base=replace(settings,max_trade_sol=.01,max_open_positions=1)
            self.assertEqual(trading_settings(base,100).max_trade_sol,.01)
            self.assertEqual(trading_settings(base,100).max_open_positions,1)
    def test_trial_limits_enforced_and_normal_restored(self):
        with patch.dict(os.environ,{'PAPER_RISK_TRIAL_UNTIL':'9999999999'}):
            self.assertLessEqual(position_size_sol(100,10),.1)
            self.assertTrue(should_enter({},90,40,50,50)['enter'])
            self.assertFalse(hard_risk_check(.101,0,0,{'liquidity_usd':6000})['pass'])
            self.assertFalse(hard_risk_check(.02,3,0,{'liquidity_usd':6000})['pass'])
            self.assertFalse(hard_risk_check(.02,0,-.15,{'liquidity_usd':6000})['pass'])
        with patch.dict(os.environ,{'PAPER_RISK_TRIAL_UNTIL':'1'}):
            self.assertFalse(should_enter({},90,40,50,50)['enter'])
            self.assertFalse(hard_risk_check(.02,0,0,{'liquidity_usd':6000})['pass'])

class PaperSizingTests(unittest.TestCase):
    def test_range_caps_and_insufficient_cash(self):
        with patch('strategy.sizing.settings',replace(settings,paper_mode=True,default_buy_sol=.1,max_trade_sol=.1,paper_min_buy_sol=.05)):
            self.assertEqual(position_size_sol(50,1),.05)
            self.assertEqual(position_size_sol(100,1),.1)
            self.assertEqual(position_size_sol(75,1),.075)
            self.assertEqual(position_size_sol(100,.07),.07)
            self.assertEqual(position_size_sol(100,.049),0)
            self.assertEqual(position_size_sol(float('nan'),1),0)
