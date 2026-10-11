import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import database.store as db
from database.store import Store
from database.research import research
from data import bundle_research as bundles
from intelligence.narrative import context

MINT = 'MLn86AfgezEPPKd4SNQZ5txM7SVSDTDGEyYhnpNpump'
OTHER = 'So11111111111111111111111111111111111111112'
CLIENT = httpx.AsyncClient


class BundleResearch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = patch.object(db, 'DB', Path(self.tmp.name) / 'test.sqlite3')
        self.db.start()
        Store().ensure_observations()
        research.ensure()

    def tearDown(self):
        self.db.stop()
        self.tmp.cleanup()

    def report(self, **kwargs):
        return dict(mint=MINT, status='bundled', bundledPct=12.7,
                    creatorBundlePct=12.7, otherBundlesPct=0, estimate=False,
                    risk='high', insidersHoldPct=15, flaggedHoldPct=18,
                    reportAt=time.time(), **kwargs)

    def request(self, response):
        transport = httpx.MockTransport(lambda request: response(request))
        with patch.object(bundles.httpx, 'AsyncClient', side_effect=lambda **kw: CLIENT(transport=transport, trust_env=False, **kw)):
            asyncio.run(bundles.check_batch([MINT, MINT]))

    def test_evidence_persists_and_reaches_decisions_without_clearing_rugcheck(self):
        self.request(lambda r: httpx.Response(200, json={'tokens': [self.report()]}, request=r))
        data = context(MINT)
        self.assertEqual(data['bundle']['launch_report']['bundledPct'], 12.7)
        self.assertEqual(data['features']['launch_bundle_group'], '5_to_20')
        self.assertTrue(data['features']['bundle_indicator'])
        self.assertEqual(data['security']['status'], 'pending')
        self.assertFalse(data['features']['rug_danger'])
        self.assertEqual(bundles.cached(MINT)['report'], bundles.BASE + '/' + MINT)
        research.snapshot({'mint': MINT, 'price_usd': 1, 'timestamp': time.time()}, data['features'])
        with db.store.conn() as c:
            row = c.execute('SELECT features_json FROM research_cases').fetchone()
        self.assertIn('5_to_20', row['features_json'])

    def test_unscanned_errors_and_mismatched_mints_never_clear(self):
        report = self.report();report.update(status='unscanned', bundledPct=0)
        self.request(lambda r: httpx.Response(200, json={'tokens': [report]}, request=r))
        self.assertEqual(bundles.features(bundles.cached(MINT))['launch_bundle_group'], 'unknown')
        self.assertIsNone(bundles.cached(MINT)['bundledPct'])
        report = self.report();report['mint'] = OTHER
        self.request(lambda r: httpx.Response(200, json={'tokens': [report]}, request=r))
        self.assertEqual(bundles.cached(MINT)['status'], 'unavailable')
        self.assertEqual(bundles.cached(OTHER)['status'], 'pending')
        self.request(lambda r: httpx.Response(429, request=r))
        self.assertEqual(bundles.cached(MINT)['failure_type'], 'http_429')
        self.assertFalse(context(MINT)['features']['bundle_indicator'])

    def test_old_holdings_report_is_not_refreshed_by_fetch(self):
        report = self.report();report['reportAt'] = time.time() - 1000
        bundles.save(MINT, bundles.normalize(report, MINT))
        cached = bundles.cached(MINT)
        self.assertEqual(cached['bundledPct'], 12.7)
        self.assertIsNone(cached['insidersHoldPct'])
        self.assertIsNone(cached['risk'])
        self.assertFalse(cached['holdings_fresh'])
        with patch.object(bundles.time, 'time', return_value=time.time() + 700):
            self.assertEqual(bundles.cached(MINT)['status'], 'stale')
            self.assertEqual(bundles.features(bundles.cached(MINT))['launch_bundle_group'], 'unknown')

    def test_bad_numbers_and_external_report_links_are_not_trusted(self):
        report = self.report();report.update(bundledPct=float('nan'), insidersHoldPct=101,
                                            flaggedHoldPct=True, report='https://evil.example')
        result = bundles.normalize(report, MINT)
        for key in ('bundledPct', 'insidersHoldPct', 'flaggedHoldPct'):
            self.assertIsNone(result[key])
        self.assertEqual(result['report'], bundles.BASE + '/' + MINT)


if __name__ == '__main__':
    unittest.main()
