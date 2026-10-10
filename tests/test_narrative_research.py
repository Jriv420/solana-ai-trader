import os
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,AsyncMock
from fastapi.testclient import TestClient
import app
import database.store as db
from database.store import Store
from database.research import research
from intelligence.narrative import context,record_transaction
from intelligence.risk_ai import score_contextual_risk
from data.security_research import normalize_report,check_token
from strategy.token_filter import evaluate_token
MINT='So11111111111111111111111111111111111111112'
WALLET='11111111111111111111111111111111'

class NarrativeResearch(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.patch=patch.object(db,'DB',Path(self.tmp.name)/'db.sqlite3');self.patch.start()
        Store().ensure_observations();research.ensure()
        from database.missed import missed
        missed.ensure()
        from database.wallet_registry import wallet_registry
        wallet_registry.ensure()
        from data.social_data import ensure
        ensure()
        self.env=patch.dict(os.environ,{'NEXUS_PASSWORD':'test'});self.env.start();self.client=TestClient(app.app)
    def tearDown(self):
        self.client.close();self.env.stop();self.patch.stop();self.tmp.cleanup()
    def token(self,price,now):return {'mint':MINT,'price_usd':price,'timestamp':now,'liquidity_usd':50000,'age_minutes':1}
    def test_timing_crossings_are_sampled_and_horizon_bounded(self):
        now=time.time();features={'narrative':'timing-test'}
        for elapsed,price in ((0,100),(60,160),(120,60),(300,80)):
            research.snapshot(self.token(price,now+elapsed),features,now+elapsed)
        timing=research.learning(features,'5m')['timing']
        self.assertEqual(timing['median_seconds_to_gain_50'],60)
        self.assertEqual(timing['median_seconds_to_loss_30'],120)
        other=dict(self.token(100,now),mint='LATER')
        research.snapshot(other,features,now)
        other.update(price_usd=110,timestamp=now+300);research.snapshot(other,features,now+300)
        other.update(price_usd=160,timestamp=now+600);research.snapshot(other,features,now+600)
        self.assertEqual(research.learning(features,'5m')['timing']['gain_50_observations'],1)
    def claim(self,**extra):
        value={'wallet':WALLET,'identity':'alleged','endorsement':'speculative','subject':'Narrative person'};value.update(extra)
        return self.client.post('/api/research/'+MINT+'/claims',json=value,auth=('nexus','test'))
    def test_claim_security_and_verified_source_requirement(self):
        self.assertEqual(self.client.get('/api/research/'+MINT).status_code,401)
        self.assertEqual(self.claim(identity='verified').status_code,400)
        self.assertEqual(self.claim(source_url='javascript:alert(1)').status_code,400)
        self.assertEqual(self.claim(identity='verified',endorsement='confirmed',source_url='https://x.com/person/status/1').status_code,200)
        self.assertEqual(context(MINT)['features']['narrative'],'reviewed_confirmed')
        self.assertEqual(context(MINT)['claims'][0]['provenance'],'user_reviewed')
        response=self.client.post('/api/research/'+MINT+'/claims',json={'wallet':WALLET},auth=('nexus','test'),headers={'Origin':'https://evil.example'})
        self.assertEqual(response.status_code,403)
    def test_transfer_does_not_become_buy_identity_or_endorsement(self):
        item={'signature':'s','parserStatus':'OK','parsed':{'transactionStatus':'OK','blockTime':time.time(),'summary':{'type':'transfer'},'tokenTransfers':[{'mint':MINT,'toUserAccount':WALLET,'fromUserAccount':'sender','rawTokenAmount':100,'decimals':0}]}}
        record_transaction(item,WALLET);record_transaction(item,WALLET)
        data=context(MINT)
        self.assertEqual(len(data['events']),1);self.assertEqual(data['features']['acquisition'],'received_transfer');self.assertEqual(data['features']['narrative'],'unknown')
        self.assertEqual(data['claims'],[])
    def test_large_transfer_and_denial_remain_speculative(self):
        self.claim(endorsement='denied',source_url='https://x.com/person/status/1')
        research.check(MINT,{'status':'ok','risks':[],'supply_raw':1000})
        research.event({'signature':'a','wallet':WALLET,'mint':MINT,'timestamp':time.time(),'kind':'received_transfer','raw_quantity':'100','quantity':'100'})
        data=context(MINT);self.assertTrue(data['features']['large_received_transfer']);self.assertEqual(data['claims'][0]['endorsement'],'denied')
        self.assertGreater(score_contextual_risk(dict(self.token(1,time.time()),research=data))['score'],score_contextual_risk(self.token(1,time.time()))['score'])
    def test_forward_only_outcomes_preserve_dip_after_rebound(self):
        features={'narrative':'speculative'};now=time.time()
        research.snapshot(self.token(100,now),features,now)
        research.snapshot(self.token(50,now+100),features,now+100)
        research.snapshot(self.token(110,now+300),features,now+300)
        with db.store.conn() as c:r=c.execute('SELECT * FROM research_outcomes').fetchone()
        self.assertAlmostEqual(r['return_pct'],10);self.assertAlmostEqual(r['drawdown_pct'],-50)
        self.assertEqual(research.learning(features,'5m')['distinct_coins'],1)
        research.snapshot(self.token(200,now+3600),{'narrative':'reviewed_confirmed'},now+3600)
        self.assertEqual(research.learning({'narrative':'reviewed_confirmed'})['distinct_coins'],0)
    def test_missing_and_stale_prices_never_fabricate_outcomes(self):
        now=time.time();features={'narrative':'unknown'}
        research.snapshot(self.token(100,now),features,now)
        research.snapshot(self.token(50,now),features,now+3600)
        research.snapshot(self.token(50,now+7200),features,now+7200)
        self.assertEqual(research.learning(features)['distinct_coins'],0)
    def test_distinct_coin_minimum_before_adapting_risk(self):
        now=time.time();features={'narrative':'speculative'}
        for i in range(10):
            t=self.token(100,now);t['mint']=str(i);research.snapshot(t,features,now)
            t.update(price_usd=50,timestamp=now+3600);research.snapshot(t,features,now+3600)
            research.snapshot(t,features,now+3601)
        data=research.learning(features);self.assertEqual(data['distinct_coins'],10);self.assertEqual(data['risk_adjustment'],10)
    def test_rugcheck_failure_is_not_clean_and_blocks_entry(self):
        with self.assertRaises(ValueError):normalize_report({'mint':MINT},MINT)
        bad=normalize_report({'mint':MINT,'risks':[{'name':'Active freeze','level':'danger'}],'token':{'mintAuthority':None,'freezeAuthority':WALLET}},MINT)
        self.assertTrue(bad['danger'])
        t=self.token(1,time.time());t['research']={'security':bad}
        self.assertFalse(evaluate_token(t)['pass'])
        t['research']={'security':{'status':'unavailable'}};self.assertFalse(evaluate_token(t)['pass'])
        research.check(MINT,{'status':'ok','risks':[]})
        with db.store.conn() as c:c.execute('UPDATE research_checks SET checked_at=?',(time.time()-601,))
        self.assertEqual(research.security(MINT)['status'],'stale')
    def test_ai_receives_point_in_time_context_and_unchecked_never_scores(self):
        import asyncio
        token=self.token(1,time.time())
        with patch.object(app,'score_wallet_context',return_value={'score':60,'status':'observed'}),patch.object(app,'evaluate_fast',new=AsyncMock(return_value={'provider':'deterministic-fallback','score':50})) as model:
            result=asyncio.run(app.analyze(token))
            self.assertEqual(result['status'],'rejected');model.assert_not_awaited()
            research.check(MINT,{'status':'ok','risks':[],'danger':False})
            result=asyncio.run(app.analyze(token))
            model.assert_awaited_once();self.assertIn('research',model.call_args.args[0]);self.assertIn('learning',result['token']['research'])
    def test_multiple_transfer_legs_are_netted_and_self_transfers_ignored(self):
        item={'signature':'net','parserStatus':'OK','parsed':{'transactionStatus':'OK','blockTime':time.time(),'summary':{'type':'transfer'},'tokenTransfers':[{'mint':MINT,'toUserAccount':WALLET,'fromUserAccount':'sender','rawTokenAmount':100,'decimals':0},{'mint':MINT,'toUserAccount':WALLET,'fromUserAccount':'sender','rawTokenAmount':50,'decimals':0},{'mint':MINT,'toUserAccount':WALLET,'fromUserAccount':WALLET,'rawTokenAmount':1000,'decimals':0}]}}
        record_transaction(item,WALLET);self.assertEqual(research.events(MINT)[0]['quantity'],'150')
    def test_same_slot_is_indicator_not_verified_bundle(self):
        for i in range(3):research.event({'signature':str(i),'wallet':str(i),'mint':MINT,'timestamp':time.time(),'slot':10,'kind':'buy','quantity':'1'})
        data=context(MINT)
        self.assertEqual(data['bundle']['status'],'indicators_found');self.assertIn('not proof',data['bundle']['scope'])

if __name__=='__main__':unittest.main()
