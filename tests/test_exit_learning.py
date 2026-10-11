import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import database.store as db
from database.store import Store
from intelligence import exit_learning as review
class ExitReview(unittest.TestCase):
    def test_samples_and_accounts_do_not_rewrite_pnl(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(db,'DB',Path(tmp)/'db'):
            a=Store();b=Store('shadow_trades');now=time.time()
            for book in (a,b):
                p=book.create_trade({'mint':'test','symbol':'T','entry_price_usd':1,'amount_sol':.05,'entry_time':now-50})
                book.close_trade(p['id'],1,now-10,0,0,'trailing stop')
            self.assertEqual(review.mints(),['test'])
            review.observe({'mint':'test','price_usd':2,'timestamp':now-1})
            review.observe({'mint':'test','price_usd':.5,'timestamp':now})
            review.observe({'mint':'test','price_usd':100,'timestamp':now-200})
            x=review.review('trades',1)
            self.assertEqual(x['samples'],2);self.assertEqual(x['peak_after_exit_pct'],100);self.assertEqual(x['low_after_exit_pct'],-50)
            self.assertEqual(b.all()[0]['exit_review']['samples'],2);self.assertEqual(a.realized(),0)
            with patch.object(review.time,'time',return_value=now+3700):
                review.observe({'mint':'test','price_usd':10,'timestamp':now+3700})
                self.assertEqual(review.review('trades',1)['samples'],2);self.assertTrue(review.review('trades',1)['complete'])
    def test_runner_feedback_is_hindsight_not_entry_evidence(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(db,'DB',Path(tmp)/'db'):
            self.assertTrue(review.context(review.RUNNER)['user_feedback']['moonbag_candidate'])
            self.assertIsNone(review.context('other')['user_feedback'])
