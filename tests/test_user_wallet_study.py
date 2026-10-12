import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import database.store as db
from intelligence import user_wallet_study as study
class PersonalWalletStudy(unittest.TestCase):
 def event(self,n,kind,q=1,sol=1,mint='A',**kw):return dict(signature=str(n),timestamp=n*3600,kind=kind,quantity=str(q),sol=str(sol),mint=mint,**kw)
 def test_partial_profit_then_losing_remainder_is_grouped(self):
  a=study.evaluate([self.event(1,'buy',10,1),self.event(2,'sell',5,2),self.event(3,'sell',5,.2)])
  self.assertEqual(a['completed_positions'],1);self.assertEqual(a['matched_sales'],2)
  self.assertAlmostEqual(a['net_realized_sol_completed'],1.2)
  self.assertEqual(a['recent_completed'][0]['holding_seconds'],7200)
  self.assertAlmostEqual(a['recent_completed'][0]['last_sale_below_highest_own_fill_pct'],90)
 def test_transfer_or_unknown_history_invalidates_inventory(self):
  events=[self.event(1,'buy',10,1),self.event(2,'invalidate',mints=['A']),self.event(3,'sell',10,20)]
  a=study.evaluate(events);self.assertEqual(a['matched_sales'],0);self.assertEqual(a['completed_positions'],0)
  a=study.evaluate([self.event(1,'buy'),self.event(2,'invalidate_all'),self.event(3,'sell')]);self.assertEqual(a['matched_sales'],0)
 def test_repeated_buys_and_open_positions_not_completed_wins(self):
  a=study.evaluate([self.event(1,'buy'),self.event(2,'buy'),self.event(3,'sell',2,1)])
  self.assertEqual(a['repeated_buy_positions'],1);self.assertEqual(a['completed_win_rate_pct'],0)
  a=study.evaluate([self.event(1,'buy')]);self.assertIsNone(a['completed_win_rate_pct']);self.assertEqual(a['unresolved_positions'],1)
 def test_cursor_persists_and_no_model_retraining_claim(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(db,'DB',Path(tmp)/'db'),patch.dict('os.environ',{'STUDY_WALLET':'8ZENXDiMX8H2qnPVzmb4DjwTaAT16XULiU4U2Vp9Xqa'}):
   study.ensure();s=study.state();study.save(dict(s,cursor='older',pages=1,status='importing'))
   self.assertEqual(study.state()['cursor'],'older');self.assertIn('No automatic copying',study.summary()['scope'])
