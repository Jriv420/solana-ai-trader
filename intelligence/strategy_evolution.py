"""Bounded, prospective exit evolution. No orders or retrospective backtest fitting."""
import json
import logging
import random
import time
from datetime import datetime, timezone
from database.store import store
from intelligence.trade_evaluation import metrics, positions

VERSION = 'exit-evolution-v1'
_ticks = {}
FAMILIES = ('defensive', 'scalp', 'balanced', 'runner')
DOMAINS = {'take_profit': (25, 50, 75, 100), 'trail': (15, 20, 30, 40),
           'partial_fraction': (.25, .5, 1), 'trail_arm': (0, 25, 50),
           'max_hold_seconds': (900, 1800, 3600)}


def ensure():
    with store.conn() as c:
        c.execute('CREATE TABLE IF NOT EXISTS evolution_generations(book TEXT,generation INTEGER,payload_json TEXT,PRIMARY KEY(book,generation))')


def genome(rng, family):
    g = {k: rng.choice(v) for k, v in DOMAINS.items()}
    # Species preserve different holding hypotheses; they are not narrative labels.
    if family == 'defensive': g.update(take_profit=25, trail=15, trail_arm=0)
    if family == 'scalp': g.update(max_hold_seconds=900, partial_fraction=1)
    if family == 'runner': g.update(partial_fraction=rng.choice((.25, .5)), trail_arm=50, max_hold_seconds=3600)
    return dict(g, family=family)


def population(book, generation, parents=None):
    rng = random.Random(f'{VERSION}:{book}:{generation}')
    result = {}
    for family in FAMILIES:
        for slot in range(2):
            g = genome(rng, family)
            if slot == 0 and parents and family in parents:
                # One bounded mutation of the family's training winner; one newcomer.
                g = dict(parents[family])
                key = rng.choice(tuple(DOMAINS)); g[key] = rng.choice(DOMAINS[key])
            result[f'evo_{generation}_{family}_{slot}'] = g
    return result


def save(book, g):
    with store.conn() as c:
        c.execute('INSERT OR REPLACE INTO evolution_generations VALUES(?,?,?)', (book, g['generation'], json.dumps(g)))
        c.execute('DELETE FROM evolution_generations WHERE book=? AND generation<?', (book, g['generation'] - 30))


def current(book):
    ensure()
    with store.conn() as c:
        row = c.execute('SELECT payload_json FROM evolution_generations WHERE book=? ORDER BY generation DESC LIMIT 1', (book,)).fetchone()
    if row:
        g = json.loads(row['payload_json'])
        if g['phase'] != 'finished': return g
        # Recover if a process stopped between archiving and creating its successor.
        n = g['generation'] + 1
        g = {'version': VERSION, 'generation': n, 'created_at': time.time(), 'phase': 'training',
             'training_mints': [], 'policies': population(book, n, g['parents']), 'champion': None}
        save(book, g)
        return g
    g = {'version': VERSION, 'generation': 1, 'created_at': time.time(), 'phase': 'training',
         'policies': population(book, 1), 'training_mints': [], 'champion': None}
    save(book, g)
    logging.getLogger('uvicorn.error').info('NEXUS evolution initialized book=%s version=%s generation=1 candidates=8 phase=training', book, VERSION)
    return g


def enroll(book, mint):
    g = current(book)
    if g['phase'] == 'validation' and mint in g['training_mints']:
        return []  # A training contract never counts as an unseen validation contract.
    if g['phase'] == 'training' and mint not in g['training_mints']:
        g['training_mints'].append(mint)
        # Bounded metadata; no false claims of unseen data after eviction.
        if len(g['training_mints']) > 1000: return []
        save(book, g)
    return [(key, dict(rules), {'generation': g['generation'], 'phase': g['phase']})
            for key, rules in g['policies'].items()]


def pairs(rows, baseline, policy, phase):
    output = []
    for r, s in rows:
        b = baseline.get(r['root_id'])
        if r['policy'] == policy and s.get('evolution', {}).get('phase') == phase and s['complete'] and b and b['complete'] and b['costed']:
            output.append((r, s, b))
    # Repeated trades of one coin do not become independent validation successes.
    unique = {}
    for item in sorted(output, key=lambda x: x[0]['entry_time']): unique.setdefault(item[0]['mint'], item)
    return list(unique.values())


def comparison(items):
    actual = [b for _, _, b in items]
    virtual = [dict(b, net_pnl_sol=s['net_pnl_sol'], exit_time=s['exit_time']) for _, s, b in items]
    return {'candidate': metrics(virtual), 'actual': metrics(actual),
            'entry_days': len({datetime.fromtimestamp(b['entry_time'], timezone.utc).date() for b in actual})}


def fitness(report):
    m = report['candidate']
    return m['net_pnl_sol'] - m['realized_drawdown_sol']


def advance(book):
    """Select on training only, freeze, then judge that one candidate prospectively."""
    g = current(book)
    with store.conn() as c:
        raw = c.execute("SELECT * FROM policy_trials WHERE book=? AND json_extract(payload_json,'$.evolution.generation')=? ORDER BY entry_time", (book, g['generation'])).fetchall()
    rows = [(dict(r), json.loads(r['payload_json'])) for r in raw]
    baseline = {p['root_id']: p for p in positions(book)}
    if g['phase'] == 'training':
        # Require all candidates' same completed entries so incomplete long holds cannot win by omission.
        common = None
        for key in g['policies']:
            ids = {r['root_id'] for r, _, _ in pairs(rows, baseline, key, 'training')}
            common = ids if common is None else common & ids
        common = common or set()
        reports = {key: comparison([x for x in pairs(rows, baseline, key, 'training') if x[0]['root_id'] in common]) for key in g['policies']}
        g['training_reports'] = reports
        enough = len(common) >= 50 and all(r['entry_days'] >= 7 for r in reports.values())
        if enough:
            g['champion'] = max(reports, key=lambda key: fitness(reports[key]))
            g['phase'] = 'validation'; g['frozen_at'] = time.time()
            g['parents'] = {family: g['policies'][max((k for k, v in g['policies'].items() if v['family'] == family), key=lambda k: fitness(reports[k]))] for family in FAMILIES}
            logging.getLogger('uvicorn.error').info('NEXUS evolution frozen book=%s generation=%s candidate=%s training_coins=%s', book, g['generation'], g['champion'], len(common))
    else:
        report = comparison(pairs(rows, baseline, g['champion'], 'validation'))
        g['validation_report'] = report
        if report['candidate']['completed_positions'] >= 25 and report['entry_days'] >= 3:
            m, b = report['candidate'], report['actual']
            profitable = m['profit_factor'] > 1 if m['profit_factor'] is not None else m['average_win_sol'] is not None and m['average_loss_sol'] is None
            passed = m['net_pnl_sol'] > max(0, b['net_pnl_sol']) and m['realized_drawdown_sol'] <= b['realized_drawdown_sol'] and profitable
            g.update(phase='finished', finished_at=time.time(), result='passed_paper_screen' if passed else 'rejected_on_fresh_data')
            logging.getLogger('uvicorn.error').info('NEXUS evolution result book=%s generation=%s result=%s validation_coins=%s', book, g['generation'], g['result'], m['completed_positions'])
            save(book, g)
            n = g['generation'] + 1
            next_g = {'version': VERSION, 'generation': n, 'created_at': time.time(), 'phase': 'training', 'training_mints': [],
                      'policies': population(book, n, g['parents']), 'champion': None}
            save(book, next_g)
            return next_g
    save(book, g)
    return g


def summary(book):
    g = advance(book)
    with store.conn() as c:
        past = c.execute('SELECT payload_json FROM evolution_generations WHERE book=? AND generation<? ORDER BY generation DESC LIMIT 5', (book, g['generation'])).fetchall()
    return {'version': VERSION, 'current': g, 'finished': [json.loads(x['payload_json']) for x in past],
            'scope': 'Eight exit candidates: four families, five bounded genes. Selection needs 50 common completed distinct-coin trials across seven UTC entry dates. The frozen training winner then needs 25 NEW contracts across three dates. Holdout results never select parents. Generations use only entries made after enrollment, never replay old candles. No automatic replacement of trading policy or model-weight training. Estimated fills do not model executable liquidity or portfolio capacity; missing samples remain pending.'}


def lesson(book):
    ensure()
    with store.conn() as c:
        row = c.execute("SELECT payload_json FROM evolution_generations WHERE book=? AND json_extract(payload_json,'$.result')='passed_paper_screen' ORDER BY generation DESC LIMIT 1", (book,)).fetchone()
    if not row: return {'status': 'no_forward_validated_candidate', 'instruction': 'Do not claim a new strategy has been learned or proven.'}
    g = json.loads(row['payload_json'])
    return {'status': 'passed_paper_screen', 'generation': g['generation'], 'rules': g['policies'][g['champion']],
            'fresh_validation': g['validation_report'], 'instruction': 'Limited exit evidence on selected actual entries, not a validated portfolio or guaranteed edge. Consider alongside current evidence; do not override protective gates.'}


def tick():
    import database.store as db
    key = str(db.DB); now = time.time()
    if now - _ticks.get(key, 0) < 60: return
    _ticks.clear(); _ticks[key] = now
    for book in ('trades', 'shadow_trades'): advance(book)
