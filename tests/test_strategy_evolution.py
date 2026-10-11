import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import database.store as db
from intelligence import strategy_evolution as evo, policy_trials as trials, jev


class EvolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = patch.object(db, 'DB', Path(self.tmp.name) / 'db'); self.db.start()
        trials.ensure(); self.baseline = []; self.at = time.time() - 15 * 86400

    def tearDown(self):
        self.db.stop(); self.tmp.cleanup()

    def seed(self, g, count, phase, offset=0, profitable=None):
        for i in range(count):
            root = offset + i + 1; mint = f'{phase}-{root}'
            at = self.at + (i % 7) * 86400 + offset
            b = {'root_id': root, 'mint': mint, 'entry_time': at, 'exit_time': at+100,
                 'complete': True, 'costed': True, 'net_pnl_sol': .001}
            self.baseline.append(b)
            for key in g['policies']:
                # Give a different non-champion a huge validation gain: it must not be selected.
                pnl = .003 if phase == 'training' else .002 if key == profitable else .1
                s = {'evolution': {'generation': g['generation'], 'phase': phase},
                     'complete': True, 'net_pnl_sol': pnl, 'exit_time': at+100}
                with db.store.conn() as c:
                    c.execute('INSERT INTO policy_trials VALUES(?,?,?,?,?,?)', ('shadow_trades', root, key, mint, at, json.dumps(s)))

    def test_prospective_split_freezes_winner_and_breeds_without_holdout_selection(self):
        g = evo.current('shadow_trades')
        self.assertEqual(len(g['policies']), 8)
        enrolled = evo.enroll('shadow_trades', 'already-seen')
        self.assertTrue(all(x[2]['phase'] == 'training' for x in enrolled))
        self.seed(g, 49, 'training')
        with patch.object(evo, 'positions', return_value=self.baseline):
            self.assertEqual(evo.advance('shadow_trades')['phase'], 'training')
        self.seed(g, 1, 'training', offset=49)
        with patch.object(evo, 'positions', return_value=self.baseline):
            frozen = evo.advance('shadow_trades')
        self.assertEqual(frozen['phase'], 'validation')
        self.assertEqual(evo.enroll('shadow_trades', 'already-seen'), [])
        self.assertEqual(evo.enroll('shadow_trades', 'new-coin')[0][2]['phase'], 'validation')
        self.seed(g, 25, 'validation', offset=100, profitable=frozen['champion'])
        with patch.object(evo, 'positions', return_value=self.baseline):
            next_g = evo.advance('shadow_trades')
        self.assertEqual(next_g['generation'], 2)
        self.assertEqual(next_g['phase'], 'training')
        lesson = evo.lesson('shadow_trades')
        self.assertEqual(lesson['status'], 'passed_paper_screen')
        self.assertAlmostEqual(lesson['fresh_validation']['candidate']['net_pnl_sol'], .05)
        self.assertEqual(lesson['rules'], frozen['policies'][frozen['champion']])
        self.assertEqual(evo.current('shadow_trades')['policies'], next_g['policies'])
        self.assertEqual(evo.population('shadow_trades', 2, frozen['parents']), next_g['policies'])
        for rules in next_g['policies'].values():
            for key, values in evo.DOMAINS.items(): self.assertIn(rules[key], values)

    def test_repeated_contracts_and_open_trials_are_not_independent_successes(self):
        g = evo.current('shadow_trades'); key = next(iter(g['policies']))
        b = {'root_id': 1, 'mint': 'same', 'entry_time': 1, 'exit_time': 2,
             'costed': True, 'complete': True, 'net_pnl_sol': 1}
        rows = [({'root_id': i, 'mint': 'same', 'entry_time': i, 'policy': key},
                 {'complete': True, 'evolution': {'phase': 'validation'}, 'exit_time': i+1, 'net_pnl_sol': 1}) for i in range(1, 30)]
        baseline = {i: dict(b, root_id=i) for i in range(1, 30)}
        self.assertEqual(len(evo.pairs(rows, baseline, key, 'validation')), 1)
        rows[0][1]['complete'] = False
        self.assertEqual(len(evo.pairs(rows[:1], baseline, key, 'validation')), 0)
        self.assertEqual(evo.lesson('trades')['status'], 'no_forward_validated_candidate')

    def test_optional_factor_answers_do_not_break_action_or_invent_confidence(self):
        body = jev.request_body({'task': 'paper_exit'}, [])
        self.assertEqual(len(body['questions']), 5)
        result = jev.normalize_response({'answers': {'exit': {'type': 'choice', 'choice': 'hold'},
                  'narrative_support': {'type': 'choice', 'choice': 'unknown', 'confidence': float('nan')}}})
        self.assertEqual(result['action'], 'hold')
        self.assertEqual(result['factors']['narrative_support'], {'assessment': 'unknown'})
        self.assertEqual(jev.normalize_response({'answers': {'exit': {'type': 'choice', 'choice': 'hold'}}})['factors'], {})
