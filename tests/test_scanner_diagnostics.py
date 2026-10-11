import unittest,tempfile,time
from pathlib import Path
from unittest.mock import patch
from dataclasses import replace
import database.store as db
from database.store import Store
from data import security_research as security
from paper import shadow
from config.settings import settings
from config.settings import daily_loss_limit_enabled
MINT='So11111111111111111111111111111111111111112'
OTHER='11111111111111111111111111111111'

class ScannerDiagnostics(unittest.TestCase):
    def test_testing_override_cannot_disable_live_limit(self):
        with patch.dict('os.environ',{'PAPER_DAILY_LOSS_LIMIT_ENABLED':'false'}):
            self.assertFalse(daily_loss_limit_enabled(replace(settings,paper_mode=True)))
            self.assertTrue(daily_loss_limit_enabled(replace(settings,paper_mode=False)))
    def test_daily_loss_override_keeps_history_and_allows_eligibility_check(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(db,'DB',Path(tmp)/'db'),patch.dict('os.environ',{'PAPER_DAILY_LOSS_LIMIT_ENABLED':'false'}):
            Store();book=Store('shadow_trades');now=time.time()
            with patch.object(shadow,'BOOK',book),patch.object(shadow,'initialize',return_value={'ends_at':now+3600}),patch.object(shadow,'settings',replace(settings,paper_mode=True)),patch.object(book,'daily_realized',return_value=-.16),patch.object(shadow,'eligible',return_value=(False,'security pending or danger')) as eligible:
                state=shadow.step([{'token':{'mint':MINT}}],process_exits=False)
                self.assertEqual(state['entry_pause_reasons'],[]);self.assertFalse(state['daily_loss_limit_enabled'])
                self.assertEqual(state['daily_realized_sol'],-.16);eligible.assert_called_once()
                self.assertEqual(state['blockers']['security pending or danger'],1)
    def item(self,mint,**kw):
        return {'last_seen':1000,'token':dict(mint=mint,timestamp=1000,liquidity_usd=10000,volume_5m_usd=5000,price_change_5m_pct=10,buys_5m=20,sells_5m=10,**kw)}
    def test_cached_head_does_not_stall_due_retry(self):
        cache={MINT:{'status':'ok','checked_at':800},OTHER:{'status':'unavailable','checked_at':900}}
        with patch.object(security.research,'security',side_effect=lambda m:cache[m]):
            self.assertEqual(security.next_check([self.item(MINT),self.item(OTHER)],now=1000),OTHER)
    def test_due_momentum_and_open_position_priority(self):
        a=self.item(MINT);a['token']['price_change_5m_pct']=0
        b=self.item(OTHER)
        with patch.object(security.research,'security',return_value={'status':'pending'}):
            self.assertEqual(security.next_check([a,b],now=1000),OTHER)
            self.assertEqual(security.next_check([a,b],{MINT},now=1000),MINT)
            b['last_seen']=100
            self.assertEqual(security.next_check([a,b],now=1000),MINT)
    def test_daily_loss_pause_is_visible_even_with_no_candidates(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(db,'DB',Path(tmp)/'db'):
            Store();book=Store('shadow_trades');now=time.time()
            with patch.object(shadow,'BOOK',book),patch.object(shadow,'initialize',return_value={'ends_at':now+3600}),patch.object(shadow,'settings',replace(settings,paper_mode=True)),patch.object(book,'daily_realized',return_value=-.16):
                state=shadow.step([],process_exits=False)
                self.assertTrue(state['active']);self.assertIn('Daily realized loss limit reached (0.15 SOL)',state['entry_pause_reasons'])
                self.assertEqual(state['daily_realized_sol'],-.16)
                self.assertGreater(state['daily_limit_resets_at'],now)
                self.assertEqual(state['paper_buys'],0)
