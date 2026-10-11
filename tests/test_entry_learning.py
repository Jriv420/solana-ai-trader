import json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from dataclasses import replace
import database.store as db
from database.store import Store
from intelligence import entry_learning as learn
from paper import shadow
from paper.paper_trader import PaperTrader
from config.settings import settings
MINT='So11111111111111111111111111111111111111112'

class EntryLearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=patch.object(db,'DB',Path(self.tmp.name)/'db');self.p.start()
        self.book=Store('shadow_trades');Store();learn._CACHE.clear();self.now=time.time()
        self.token={'mint':MINT,'symbol':'TEST','price_usd':1,'sol_price_usd':100,'timestamp':self.now,'market_cap_usd':572000,'liquidity_usd':10000,'volume_5m_usd':5000,'price_change_5m_pct':10,'buys_5m':20,'sells_5m':10,'research':{'security':{'status':'ok','danger':False},'features':{'launch_bundle_group':'20_plus'}}}
    def tearDown(self):learn._CACHE.clear();self.p.stop();self.tmp.cleanup()
    def completed(self,mint,pct,book=None,at=None,entry=None):
        book=book or self.book;at=self.now-100 if at is None else at
        t=dict(self.token,mint=mint) if entry is None else dict(entry,mint=mint)
        p=book.create_trade({'mint':mint,'symbol':'TEST','entry_price_usd':1,'amount_sol':.1,'entry_time':at-100,'context':{'paper_fill':{'version':1},'entry_evidence':t}})
        book.close_trade(p['id'],1+pct/100,at,pct,.1*pct/100,'test')
        return p
    def bad_history(self):
        for i in range(8):self.completed('coin'+str(i),-80 if i<2 else -10)
    def test_requires_distinct_completed_coins_and_uses_same_account(self):
        for i in range(7):self.completed('coin'+str(i),-80)
        d=learn.assess('shadow_trades',self.token,self.now);self.assertEqual(d['action'],'allow');self.assertEqual(d['matches'][0]['distinct_coins'],7)
        self.completed('coin7',-10);learn._CACHE.clear()
        d=learn.assess('shadow_trades',self.token,self.now);self.assertEqual(d['action'],'avoid')
        self.assertEqual(learn.assess('trades',self.token,self.now)['action'],'allow')
        self.assertEqual(d['matches'][1]['group'],'launch_bundle:20_plus')
    def test_repeated_trades_in_one_coin_are_not_eight_independent_lessons(self):
        for i in range(12):self.completed('onecoin',-80)
        d=learn.assess('shadow_trades',self.token,self.now);self.assertEqual(d['action'],'allow');self.assertEqual(d['matches'][0]['distinct_coins'],1)
    def test_future_outcomes_open_legacy_and_unknown_groups_are_not_learned(self):
        for i in range(8):self.completed('coin'+str(i),-80,at=self.now+10)
        self.assertEqual(learn.assess('shadow_trades',self.token,self.now)['action'],'allow')
        learn._CACHE.clear()
        self.book.create_trade({'mint':'open','entry_price_usd':1,'amount_sol':.1,'entry_time':self.now-100,'context':{'entry_evidence':self.token,'paper_fill':{'version':1}}})
        p=self.book.create_trade({'mint':'old','entry_price_usd':1,'amount_sol':.1,'entry_time':self.now-100,'context':{'entry_evidence':self.token}})
        self.book.close_trade(p['id'],.1,self.now-1,-90,-.09,'legacy')
        self.assertEqual(len(learn.history('shadow_trades',self.now)),0)
        self.assertEqual(learn.groups({'mint':'missing'}),[])
    def test_cohorts_use_immutable_entry_and_can_update_after_new_results(self):
        self.bad_history();self.assertEqual(learn.assess('shadow_trades',self.token,self.now)['action'],'avoid')
        other=dict(self.token,market_cap_usd=10000,research={'features':{},'security':{'danger':False}})
        self.assertEqual(learn.assess('shadow_trades',other,self.now)['action'],'allow')
        for i in range(8):self.completed('coin'+str(i),50,at=self.now-1)
        learn._CACHE.clear();self.assertEqual(learn.assess('shadow_trades',self.token,self.now)['action'],'allow')
    def test_exact_contract_severe_loss_cooldown_expires(self):
        self.completed(MINT,-84)
        d=learn.assess('shadow_trades',self.token,self.now);self.assertEqual(d['action'],'avoid');self.assertIn('24h',d['reason'])
        self.assertEqual(learn.assess('shadow_trades',self.token,self.now+86401)['action'],'allow')
    def test_screen_keeps_skipped_winners_and_realistic_costs_without_trades(self):
        d={'version':learn.VERSION,'action':'avoid','matches':[],'reason':'test'}
        learn.screen('shadow_trades',self.token,d,self.now);learn.screen('shadow_trades',self.token,dict(d,action='allow'),self.now)
        with db.store.conn() as c:self.assertEqual(c.execute('SELECT COUNT(*) n FROM entry_learning_trials').fetchone()['n'],1)
        stamp=self.now+3601;t=dict(self.token,timestamp=stamp,price_usd=2,sol_price_usd=200)
        learn.observe(t,stamp);learn.observe(t,stamp)
        report=learn.summary('shadow_trades');self.assertEqual(report['outcomes']['avoid']['samples'],1)
        fee=settings.paper_fee_bps/10000;slip=settings.paper_slippage_bps/10000
        expected=100*((1-slip)/(1+slip)*(1-fee)/(1+fee)-1)
        self.assertAlmostEqual(report['recent'][0]['outcome']['net_return_pct'],expected)
        self.assertEqual(self.book.all(),[]);self.assertEqual(PaperTrader(self.book).balance_sol(),settings.paper_starting_sol)
    def test_missing_or_stale_marks_never_become_fictitious_outcomes(self):
        d={'action':'allow','matches':[]};learn.screen('shadow_trades',self.token,d,self.now)
        learn.observe(dict(self.token,timestamp=self.now+3601),self.now+3800)
        learn.observe(dict(self.token,timestamp=self.now+4300),self.now+4300)
        self.assertIsNone(learn.summary('shadow_trades')['recent'][0]['outcome'])
    def test_shadow_entries_actually_avoid_learned_losses_without_bypassing_security(self):
        self.bad_history();trader=PaperTrader(self.book)
        with patch.object(shadow,'BOOK',self.book),patch.object(shadow,'TRADER',trader),patch.object(shadow,'settings',replace(settings,paper_mode=True)),patch.object(shadow,'initialize',return_value={'ends_at':self.now+3600}):
            # No ongoing loss limit interference: compare the learned gate before any entry budget checks.
            with patch.object(self.book,'daily_realized',return_value=0):
                result=shadow.step([{'token':self.token}],process_exits=False)
            self.assertEqual(result['paper_buys'],0);self.assertTrue(any('entry learning' in k for k in result['blockers']))
            self.assertEqual(learn.summary('shadow_trades')['recent'][0]['decision']['action'],'avoid')
            bad=dict(self.token,research={'security':{'status':'ok','danger':True}})
            with patch.object(learn,'safe_assess') as call:
                shadow.step([{'token':bad}],process_exits=False);call.assert_not_called()
    def test_learning_failure_waits_instead_of_bypassing_it(self):
        with patch.object(learn,'assess',side_effect=RuntimeError('private')):
            d=learn.safe_assess('shadow_trades',self.token)
        self.assertEqual(d['action'],'wait');self.assertNotIn('private',str(d))
    def test_original_entry_exception_cannot_bypass_learning_and_ai_receives_memory(self):
        import asyncio,app
        from unittest.mock import AsyncMock
        from contextlib import ExitStack
        decision={'action':'avoid','matches':[],'reason':'Loss pattern'}
        with ExitStack() as stack:
            stack.enter_context(patch.object(app,'settings',replace(settings,paper_mode=True)))
            stack.enter_context(patch.object(app,'get_social_snapshot',AsyncMock(return_value={})))
            stack.enter_context(patch.object(app,'narrative_context',return_value={'features':{},'security':{'status':'ok'}}))
            stack.enter_context(patch.object(app.research,'snapshot'))
            stack.enter_context(patch.object(app.missed,'observe'))
            stack.enter_context(patch.object(app,'score_wallet_context',return_value={'score':100,'status':'ok'}))
            stack.enter_context(patch.object(app,'evaluate_token',return_value={'pass':False,'mode':'new','reasons':['ordinary filter']}))
            stack.enter_context(patch.object(app,'exception_eligible',return_value=True))
            fast=stack.enter_context(patch.object(app,'evaluate_fast',AsyncMock(return_value={'provider':'jev','score':90})))
            stack.enter_context(patch.object(app,'score_social_context',return_value={'score':50}))
            stack.enter_context(patch.object(app,'score_contextual_risk',return_value={'score':20}))
            stack.enter_context(patch.object(app,'should_enter',return_value={'enter':False,'combined_score':80,'reasons':[]}))
            stack.enter_context(patch.object(app,'exception_decide',return_value={'allowed':True}))
            stack.enter_context(patch.object(app,'choose_route',return_value='paper'))
            stack.enter_context(patch.object(learn,'safe_assess',return_value=decision))
            record=stack.enter_context(patch.object(learn,'safe_screen'))
            buy=stack.enter_context(patch.object(app.paper_trader,'buy'))
            result=asyncio.run(app.analyze(self.token))
        self.assertFalse(result['entry']['enter']);self.assertIn('entry learning: Loss pattern',result['entry']['reasons'])
        buy.assert_not_called();record.assert_called_once()
        self.assertEqual(fast.await_args.args[0]['entry_learning']['action'],'avoid')
