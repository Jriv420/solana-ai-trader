import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch,AsyncMock
import database.store as db
from database.store import Store
from paper.paper_trader import PaperTrader
from paper import protection
class Protection(unittest.IsolatedAsyncioTestCase):
    async def test_gap_exit_uses_observed_price_and_records_samples_without_ai(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(db,'DB',Path(tmp)/'db'):
            a=Store();b=Store('shadow_trades');ta=PaperTrader(a);tb=PaperTrader(b)
            token={'mint':'test','symbol':'T','price_usd':1,'market_cap_usd':440000,'timestamp':time.time(),'sol_price_usd':100}
            tb.buy(token,.1,{});p=b.open()[0]
            b.record_risk_sample(p['id'],token)
            crash=dict(token,price_usd=.2,market_cap_usd=88000,timestamp=time.time())
            with patch.object(protection,'store',a),patch.object(protection,'BOOK',b),patch.object(protection,'paper_trader',ta),patch.object(protection,'TRADER',tb),patch.object(protection,'get_token_snapshot',AsyncMock(return_value=crash)),patch.object(protection,'get_sol_price',AsyncMock(return_value=100)),patch.object(protection,'context',return_value={'security':{'status':'ok','danger':False}}):
                await protection.check_positions()
            self.assertEqual(b.open(),[]);closed=b.all()[0]
            self.assertEqual(closed['exit_reason'],'hard stop');self.assertLess(closed['pnl_pct'],-80)
            self.assertEqual(len(closed['risk_samples']),2);self.assertEqual(a.all(),[])
            # A delayed AI callback cannot sell the already closed position again.
            self.assertFalse(tb.sell(p,token,'AI exit (jev): sell_all'))
            self.assertEqual(len(b.all()),1)
    async def test_missing_price_waits_and_price_checks_do_not_spend_ai_budget(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(db,'DB',Path(tmp)/'db'):
            a=Store();b=Store('shadow_trades');ta=PaperTrader(a);tb=PaperTrader(b)
            t={'mint':'test','price_usd':1,'sol_price_usd':100,'timestamp':time.time()};tb.buy(t,.1,{})
            with patch.object(protection,'store',a),patch.object(protection,'BOOK',b),patch.object(protection,'paper_trader',ta),patch.object(protection,'TRADER',tb),patch.object(protection,'get_token_snapshot',AsyncMock(return_value=None)),patch.object(protection,'get_sol_price',AsyncMock(return_value=100)):
                await protection.check_positions()
            self.assertEqual(len(b.open()),1)
            with db.store.conn() as c:self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name='ai_requests'").fetchone())
