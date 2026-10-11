import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import database.store as db
from database.store import Store
from database.research import research
from intelligence import activity
from intelligence.narrative import context
from intelligence.risk_ai import score_contextual_risk
import app
MINT='So11111111111111111111111111111111111111112'
class ActivityTests(unittest.TestCase):
    def test_collapse_feedback_persists_once_and_is_supplied_as_unverified_example(self):
        activity.ensure();activity.ensure()
        with db.store.conn() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) n FROM activity_labels WHERE mint=?',(activity.SUPMKT,)).fetchone()['n'],1)
        self.assertEqual(activity.latest(activity.SUPMKT)['volume'],'suspected')
        c=activity.context(MINT,{}, {}, {})
        self.assertEqual(c['volume_class'],'unknown')
        self.assertEqual(c['reviewed_examples'][0]['mint'],activity.SUPMKT)
        self.assertIn('does not establish zero buyers',c['reviewed_examples'][0]['limitations'])
        activity.save(activity.SUPMKT,{'volume':'unknown','engagement':'unknown','note':'New review'})
        activity.ensure();self.assertEqual(activity.latest(activity.SUPMKT)['note'],'New review')
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=patch.object(db,'DB',Path(self.temp.name)/'db.sqlite');self.db.start()
        Store().ensure_observations();research.ensure();activity._cache.clear()
    def tearDown(self):self.db.stop();self.temp.cleanup()
    def test_labels_are_per_contract_unverified_and_replaceable(self):
        activity.save(MINT,{'volume':'suspected','engagement':'suspected','note':'Bots'})
        self.assertEqual(activity.latest(MINT)['provenance'],'user_reported_unverified')
        self.assertEqual(activity.latest('11111111111111111111111111111111')['volume'],'unknown')
        c=context(MINT,{'price_usd':1})
        self.assertEqual(c['features']['activity_volume'],'user_suspected')
        self.assertEqual(c['activity']['engagement_class'],'user_suspected')
        baseline=score_contextual_risk({'liquidity_usd':50000})['score']
        self.assertEqual(score_contextual_risk({'liquidity_usd':50000,'research':{'features':c['features']}})['score'],baseline)
        activity.save(MINT,{'volume':'unknown','engagement':'genuine','note':'Updated review'})
        self.assertEqual(context(MINT,{})['activity']['engagement_class'],'user_genuine')
    def test_no_comments_and_aggregate_counts_never_verify_fake_volume(self):
        t={'volume_5m_usd':500000,'liquidity_usd':10000,'buys_5m':500,'sells_5m':500}
        c=activity.context(MINT,t,{},{});self.assertEqual(c['volume_class'],'market_anomaly');self.assertEqual(c['engagement_class'],'unknown')
        self.assertEqual(activity.context(MINT,{}, {}, {})['volume_class'],'unknown')
        self.assertEqual(activity.context(MINT,t,{}, {'provider_flags':[{'name':'insider'}]})['volume_class'],'coordination_indicator')
        self.assertEqual(c['coverage']['distinct_buyer_analysis'],'not_connected')
    def test_forward_labels_and_distinct_coin_comparison(self):
        for i in range(2):
            mint=MINT[:-1]+str(i+1)
            f={'activity_volume':'unknown','activity_engagement':'unknown'}
            research.snapshot({'mint':mint,'price_usd':1,'timestamp':100},f,now=100)
            research.snapshot({'mint':mint,'price_usd':2,'timestamp':3700},f,now=3700)
            activity.save(mint,{'volume':'suspected','engagement':'suspected'})
            f={'activity_volume':'user_suspected','activity_engagement':'user_suspected'}
            research.snapshot({'mint':mint,'price_usd':2,'timestamp':3800},f,now=3800)
            research.snapshot({'mint':mint,'price_usd':1,'timestamp':7400},f,now=7400)
        rows=activity.comparison()['groups'];groups={r['volume']:r for r in rows}
        self.assertEqual(groups['unknown']['distinct_coins'],2);self.assertEqual(groups['unknown']['median_return_pct'],100)
        self.assertEqual(groups['user_suspected']['distinct_coins'],2);self.assertEqual(groups['user_suspected']['median_return_pct'],-50)
    def test_paper_results_use_entry_evidence_and_isolate_accounts(self):
        a={'volume_class':'user_suspected','engagement_class':'unknown'}
        book=Store('shadow_trades')
        t=book.create_trade({'mint':MINT,'symbol':'TEST','entry_price_usd':1,'amount_sol':.05,'entry_time':100,'context':{'paper_fill':{'version':1},'entry_evidence':{'research':{'activity':a}}}})
        book.close_trade(t['id'],1.2,200,20,.01,'test')
        activity.save(MINT,{'volume':'genuine','engagement':'genuine'})
        groups=activity.comparison()['paper_results']
        self.assertEqual(len(groups),1);self.assertEqual(groups[0]['account'],'Aggressive momentum')
        self.assertEqual(groups[0]['volume'],'user_suspected');self.assertAlmostEqual(groups[0]['net_pnl_sol'],.01)
        self.assertEqual(groups[0]['win_rate_pct'],100)

    def test_api_requires_login_origin_valid_contract_and_bounded_enums(self):
        with patch.dict('os.environ',{'NEXUS_PASSWORD':'test-pass'}),TestClient(app.app,base_url='https://testserver') as client:
            path='/api/research/'+MINT+'/activity'
            self.assertEqual(client.post(path,json={'volume':'suspected'}).status_code,401)
            client.post('/login',data={'password':'test-pass'})
            self.assertEqual(client.post(path,json={'volume':'suspected'},headers={'origin':'https://evil.test'}).status_code,403)
            headers={'origin':'https://testserver'}
            self.assertEqual(client.post(path,json={'volume':'scam'},headers=headers).status_code,422)
            self.assertEqual(client.post('/api/research/bad/activity',json={},headers=headers).status_code,400)
            self.assertEqual(client.post(path,json={'source_url':'javascript:alert(1)'},headers=headers).status_code,400)
            self.assertEqual(client.post(path,json={'volume':'suspected','note':'Bots'},headers=headers).status_code,200)
            self.assertEqual(client.get('/api/research/'+MINT).json()['activity']['user_review']['note'],'Bots')
