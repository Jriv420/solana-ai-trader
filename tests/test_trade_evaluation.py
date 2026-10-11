import json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import database.store as db
from database.store import Store
from paper.paper_trader import PaperTrader
from intelligence import trade_evaluation as evaluation,policy_trials as trials

class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.patch=patch.object(db,'DB',Path(self.tmp.name)/'db');self.patch.start()
        self.book=Store('shadow_trades');self.trader=PaperTrader(self.book)
        self.t={'mint':'test','symbol':'T','timestamp':time.time(),'price_usd':1,'sol_price_usd':100,'market_cap_usd':40000,'research':{'features':{'activity_volume':'unknown'},'security':{'danger':False}}}
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def buy(self):return self.trader.buy(self.t,.1,{'entry_evidence':self.t})
    def test_partial_profit_does_not_count_as_winning_position(self):
        self.buy();self.trader.sell(self.book.open()[0],dict(self.t,price_usd=2),'profit',.25)
        m=evaluation.summary('shadow_trades')['metrics']
        self.assertEqual(m['completed_positions'],0);self.assertIsNone(m['win_rate_pct'])
        self.trader.sell(self.book.open()[0],dict(self.t,price_usd=.1),'gap')
        p=evaluation.positions('shadow_trades')[0]
        self.assertEqual(p['legs'],2);self.assertAlmostEqual(p['amount_sol'],.1)
        self.assertLess(p['net_pnl_sol'],0)
        m=self.book.paper_metrics();self.assertEqual(m['win_rate_pct'],0);self.assertEqual(m['fill_win_rate_pct'],50)
        self.assertEqual(m['position_metrics']['completed_positions'],1)
    def test_dataset_preserves_entry_evidence_and_links_final_outcome(self):
        p=self.buy();records=evaluation.dataset('shadow_trades')
        self.assertEqual(len(records),1);self.assertEqual(records[0]['trade_id'],p['id']);self.assertIsNone(records[0]['observed_outcome'])
        self.trader.sell(self.book.open()[0],dict(self.t,price_usd=2),'profit')
        records=evaluation.dataset('shadow_trades');entry=next(r for r in records if r['kind']=='entry')
        self.assertEqual(entry['decision']['evidence']['market']['price_usd'],1)
        self.assertTrue(entry['observed_outcome']['complete']);self.assertGreater(entry['observed_outcome']['net_pnl_sol'],0)
        self.assertEqual(evaluation.dataset('trades'),[])
    def states(self):
        with db.store.conn() as c:rows=c.execute('SELECT policy,payload_json FROM policy_trials').fetchall()
        return {r['policy']:json.loads(r['payload_json']) for r in rows}
    def sample(self,price,stamp):
        with patch.object(trials.time,'time',return_value=stamp):trials.observe(dict(self.t,price_usd=price,timestamp=stamp))
    def test_forward_trials_costs_partials_and_no_balance_mutation(self):
        p=self.buy();balance=self.trader.balance_sol();stamp=p['entry_time']+1
        self.sample(2,stamp);s=self.states()
        self.assertTrue(s['rule_reference']['complete']);self.assertFalse(s['partial_runner']['complete'])
        self.assertEqual(s['partial_runner']['remaining'],.5)
        self.sample(2,stamp);self.assertEqual(self.states()['partial_runner']['samples'],1)
        self.sample(.1,stamp+1);s=self.states()
        self.assertTrue(s['partial_runner']['complete']);self.assertEqual(s['partial_runner']['last_action'],'hard stop')
        fill=p['context']['paper_fill'];expected=fill['quantity']*(2+.1)*.5*(1-fill['slippage_bps']/10000)/100*(1-fill['fee_bps']/10000)-.1
        self.assertAlmostEqual(s['partial_runner']['net_pnl_sol'],expected)
        self.assertEqual(self.trader.balance_sol(),balance);self.assertEqual(len(self.book.all()),1)
        self.assertEqual(trials.summary('shadow_trades')['policies'][0]['paired_positions'],0)
        self.trader.sell(self.book.open()[0],dict(self.t,price_usd=.1),'gap')
        report=trials.summary('shadow_trades');self.assertEqual(report['policies'][0]['paired_positions'],1)
        self.assertEqual(report['policies'][0]['status'],'collecting_evidence')
    def test_stale_samples_do_not_invent_a_fill_or_limit_gap_loss(self):
        p=self.buy();now=time.time()
        trials.observe(dict(self.t,timestamp=now-121,price_usd=.1));self.assertEqual(self.states()['rule_reference']['samples'],0)
        self.sample(.1,p['entry_time']+1);self.assertLess(self.states()['rule_reference']['net_pnl_sol'],-.08)
    def test_legacy_is_excluded_from_costed_win_rate(self):
        p=self.book.create_trade({'mint':'old','symbol':'OLD','entry_price_usd':1,'amount_sol':.1,'entry_time':1,'context':{}})
        self.book.close_trade(p['id'],2,2,100,.1,'legacy')
        m=evaluation.summary('shadow_trades')['metrics'];self.assertEqual(m['legacy_completed_positions'],1);self.assertIsNone(m['win_rate_pct'])
    def test_dataset_api_requires_login_and_selects_account(self):
        import app
        from fastapi.testclient import TestClient
        self.buy()
        with patch.dict('os.environ',{'NEXUS_PASSWORD':'test-pass'}):
            client=TestClient(app.app,base_url='https://testserver')
            self.assertEqual(client.get('/api/learning/decisions').status_code,401)
            import dashboard_auth
            client.cookies.set(dashboard_auth.COOKIE,dashboard_auth.session('test-pass'))
            self.assertEqual(len(client.get('/api/learning/decisions?account=aggressive').json()['records']),1)
            self.assertEqual(client.get('/api/learning/decisions?account=original').json()['records'],[])
            self.assertEqual(client.get('/api/learning/decisions?account=invalid').status_code,422)
            client.close()
