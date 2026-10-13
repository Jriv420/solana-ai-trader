import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import database.store as db
from database.store import Store
class CurrentMarketTests(unittest.TestCase):
 def test_current_snapshot_does_not_replace_execution_caps(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(db,'DB',Path(tmp)/'db'):
   book=Store('shadow_trades');book.ensure_observations()
   t=book.create_trade({'mint':'coin','entry_price_usd':1,'amount_sol':.1,'entry_time':time.time()-100,'market_cap_usd':26800,'context':{}})
   book.close_trade(t['id'],1.5,time.time()-50,50,.05,'take profit',40700)
   book.record_observation({'token':{'mint':'coin','market_cap_usd':60000,'market_cap_is_fdv':True,'timestamp':time.time()}})
   row=book.position_history()[0]
   self.assertEqual(row['current_market']['market_cap_usd'],60000);self.assertTrue(row['current_market']['cap_is_fdv'])
   self.assertEqual(row['entry_market_cap_usd'],26800);self.assertEqual(row['position_history']['average_sell_market_cap_usd'],40700)
   book.record_observation({'token':{'mint':'coin','market_cap_usd':70000}})
   self.assertIsNone(book.position_history()[0]['current_market'])
