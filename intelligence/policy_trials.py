"""Forward-only exit hypotheses using existing observations; never place orders."""
import json
import logging
import time
from datetime import datetime, timezone
from database.store import store, valid_cap
from intelligence.trade_evaluation import positions, metrics

VERSION = 'exit-trial-v1'
POLICIES = {'rule_reference': {'take_profit': 50, 'trail': 20, 'partial': False},
            'partial_runner': {'take_profit': 50, 'trail': 30, 'partial': True}}


def ensure():
    with store.conn() as c:
        c.execute('CREATE TABLE IF NOT EXISTS policy_trials(book TEXT,root_id INTEGER,policy TEXT,mint TEXT,entry_time REAL,payload_json TEXT,PRIMARY KEY(book,root_id,policy))')
        c.execute('CREATE INDEX IF NOT EXISTS policy_trials_mint ON policy_trials(mint)')


def start(book, trade_id, token, amount, execution, fill, entry_time):
    ensure()
    from intelligence.strategy_evolution import enroll
    candidates = [(key, dict(rules), None) for key, rules in POLICIES.items()] + enroll(book, token['mint'])
    for policy, rules, evolution in candidates:
        state = {'version': VERSION, 'entry_price': execution, 'amount_sol': amount,
                 'quantity': fill['quantity'], 'remaining': 1, 'proceeds_sol': 0,
                 'fee_bps': fill['fee_bps'], 'slippage_bps': fill['slippage_bps'],
                 'peak': execution, 'scaled_out': False, 'complete': False,
                 'last_sample_at': None, 'samples': 0}
        state.update(rules=rules, evolution=evolution or {})
        with store.conn() as c:
            c.execute('INSERT OR IGNORE INTO policy_trials VALUES(?,?,?,?,?,?)',
                      (book, trade_id, policy, token['mint'], entry_time, json.dumps(state)))
            # Bound storage. Evicted incomplete comparisons have no invented outcome.
            c.execute("DELETE FROM policy_trials WHERE rowid IN (SELECT rowid FROM policy_trials ORDER BY entry_time DESC LIMIT -1 OFFSET 8000)")


def observe(token):
    now = time.time(); price = valid_cap(token.get('price_usd')); sol = valid_cap(token.get('sol_price_usd'))
    stamp = valid_cap(token.get('timestamp'))
    if price is None or sol is None or stamp is None or not 0 <= now - stamp <= 120:
        return
    ensure()
    with store.conn() as c:
        rows = c.execute("SELECT rowid,* FROM policy_trials WHERE mint=? AND json_extract(payload_json,'$.complete')=0", (token['mint'],)).fetchall()
        for row in rows:
            state = json.loads(row['payload_json']); rules = state.get('rules') or POLICIES.get(row['policy'])
            if not rules: continue
            if stamp < row['entry_time'] or stamp <= (state['last_sample_at'] or 0):
                continue
            state.update(last_sample_at=stamp, samples=state['samples'] + 1, peak=max(state['peak'], price))
            gain = 100 * (price / state['entry_price'] - 1)
            peak_gain = 100 * (state['peak'] / state['entry_price'] - 1)
            danger = bool(((token.get('research') or {}).get('security') or {}).get('danger'))
            reason = None; fraction = 0
            if danger or gain <= -20 or stamp - row['entry_time'] >= rules.get('max_hold_seconds', 86400):
                reason = 'security' if danger else 'hard stop' if gain <= -20 else 'maximum hold'
                fraction = state['remaining']
            elif 100 * (price / state['peak'] - 1) <= -rules['trail'] and peak_gain >= rules.get('trail_arm', 50 if rules.get('partial') else 0):
                reason = 'trailing stop'; fraction = state['remaining']
            elif gain >= rules['take_profit'] and not state['scaled_out']:
                fraction = state['remaining'] * rules.get('partial_fraction', .5 if rules.get('partial') else 1)
                reason = 'partial profit' if fraction < state['remaining'] else 'take profit'
                state['scaled_out'] = True
            if fraction:
                state['proceeds_sol'] += state['quantity'] * fraction * price * (1 - state['slippage_bps'] / 10000) / sol * (1 - state['fee_bps'] / 10000)
                state['remaining'] = max(0, state['remaining'] - fraction)
                state['last_action'] = reason
                if state['remaining'] <= 1e-12:
                    state.update(complete=True, exit_time=stamp, net_pnl_sol=state['proceeds_sol'] - state['amount_sol'])
            c.execute('UPDATE policy_trials SET payload_json=? WHERE rowid=?', (json.dumps(state), row['rowid']))


def safe_start(*args):
    try:
        start(*args)
    except Exception as exc:
        logging.getLogger('uvicorn.error').warning('NEXUS policy trial recording unavailable %s', type(exc).__name__)


def safe_observe(token):
    try:
        observe(token)
        from intelligence.strategy_evolution import tick
        tick()
    except Exception as exc:
        logging.getLogger('uvicorn.error').warning('NEXUS policy trial observation unavailable %s', type(exc).__name__)


def summary(book):
    ensure(); baseline = {x['root_id']: x for x in positions(book)}
    with store.conn() as c:
        rows = c.execute('SELECT * FROM policy_trials WHERE book=? ORDER BY entry_time DESC LIMIT 5000', (book,)).fetchall()
    output = []
    for policy in POLICIES:
        trials = [(x, json.loads(x['payload_json'])) for x in rows if x['policy'] == policy]
        paired = [(r, s, baseline[r['root_id']]) for r, s in trials if s['complete'] and r['root_id'] in baseline and baseline[r['root_id']]['complete'] and baseline[r['root_id']]['costed']]
        actual = [b for _, _, b in paired]
        virtual = [dict(b, net_pnl_sol=s['net_pnl_sol'], exit_time=s['exit_time']) for _, s, b in paired]
        bm = metrics(actual); vm = metrics(virtual)
        days = (time.time() - min((b['entry_time'] for b in actual), default=time.time())) / 86400
        entry_days = len({datetime.fromtimestamp(b['entry_time'],timezone.utc).date() for b in actual})
        enough = len(paired) >= 50 and bm['distinct_coins'] >= 20 and days >= 7 and entry_days >= 7
        better = enough and vm['net_pnl_sol'] > max(0, bm['net_pnl_sol']) and vm['realized_drawdown_sol'] <= bm['realized_drawdown_sol'] and vm['profit_factor'] is not None and vm['profit_factor'] > 1
        output.append({'policy': policy, 'rules': POLICIES[policy], 'paired_positions': len(paired),
                       'elapsed_days': round(days, 1), 'entry_days': entry_days, 'candidate': vm, 'same_entries_actual': bm,
                       'pending': sum(not s['complete'] for _, s in trials),
                       'awaiting_price': sum(not s['complete'] and time.time() - (s['last_sample_at'] or r['entry_time']) > 120 for r, s in trials),
                       'status': 'candidate_for_review' if better else 'not_better_on_gate' if enough else 'collecting_evidence'})
    return {'version': VERSION, 'policies': output,
            'scope': 'Prospective exit comparisons on identical new paper entries; no orders, extra model calls or market requests. Observations may stop after the actual exit; missing prices stay pending; storage retains the latest 8000 trials across accounts. Estimated costs, not executable fills. Different hold times mean portfolio capacity and future entry availability are not simulated.',
            'promotion': 'No automatic policy replacement. Requires at least 50 paired completed positions, 20 distinct coins, 7 elapsed days and entries on 7 UTC dates before reviewing net profit and realized drawdown. This gate is evidence screening, not proof of superiority.'}
