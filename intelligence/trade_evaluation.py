"""Position-level evaluation and bounded decision records, not model retraining."""
import json
import time
import logging
from collections import defaultdict
from database.store import store

MARKET_KEYS = ('timestamp', 'price_usd', 'sol_price_usd', 'market_cap_usd', 'liquidity_usd',
               'volume_5m_usd', 'buys_5m', 'sells_5m', 'price_change_5m_pct')


def snapshot(token):
    research = token.get('research') or {}
    return {'market': {k: token.get(k) for k in MARKET_KEYS},
            'features': research.get('features') or {},
            'bundle': (research.get('bundle') or {}).get('launch_report') or {},
            'security': {k: (research.get('security') or {}).get(k) for k in ('status', 'danger', 'checked_at')},
            'scope': 'Evidence recorded at decision time. Provider observations can lag the chain; no future outcomes.'}


def ensure():
    with store.conn() as c:
        c.execute('CREATE TABLE IF NOT EXISTS learning_decisions(id INTEGER PRIMARY KEY,book TEXT,trade_id INTEGER,mint TEXT,recorded_at REAL,kind TEXT,payload_json TEXT)')


def record(book, trade_id, mint, kind, payload):
    ensure()
    with store.conn() as c:
        c.execute('INSERT INTO learning_decisions(book,trade_id,mint,recorded_at,kind,payload_json) VALUES(?,?,?,?,?,?)',
                  (book, trade_id, mint, time.time(), kind, json.dumps(payload)))
        c.execute('DELETE FROM learning_decisions WHERE id NOT IN (SELECT id FROM learning_decisions ORDER BY id DESC LIMIT 5000)')


def safe_record(*args):
    try:
        record(*args)
    except Exception as exc:
        logging.getLogger('uvicorn.error').warning('NEXUS learning record unavailable %s', type(exc).__name__)


def dataset(book, limit=50):
    ensure(); outcomes = {x['root_id']: x for x in positions(book)}
    with store.conn() as c:
        rows = c.execute('SELECT * FROM learning_decisions WHERE book=? ORDER BY id DESC LIMIT ?', (book, min(100, max(1, limit)))).fetchall()
    return [{'kind': x['kind'], 'recorded_at': x['recorded_at'], 'trade_id': x['trade_id'],
             'mint': x['mint'], 'decision': json.loads(x['payload_json']),
             'observed_outcome': outcomes.get(x['trade_id']) if outcomes.get(x['trade_id'], {}).get('complete') else None}
            for x in rows]


def positions(book):
    if book not in {'trades', 'shadow_trades'}:
        raise ValueError('Invalid book')
    with store.conn() as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (book,)).fetchone():
            return []
        rows = c.execute(f'SELECT * FROM {book} ORDER BY id DESC LIMIT 5000').fetchall()
    groups = defaultdict(list)
    for raw in rows:
        row = dict(raw); row['context'] = json.loads(row.pop('context_json') or '{}')
        parent = (row['context'].get('partial_exit') or {}).get('parent_trade_id')
        groups[parent or row['id']].append(row)
    results = []
    for root_id, legs in groups.items():
        root = next((x for x in legs if x['id'] == root_id and not x['context'].get('partial_exit')), None)
        if root is None:
            continue  # Missing parent outside the bounded history is not a complete position.
        costed = all(bool(x['context'].get('paper_fill')) for x in legs)
        complete = root['status'] == 'closed' and all(x['status'] == 'closed' for x in legs)
        realized = sum(float(x['pnl_sol'] or 0) for x in legs if x['status'] == 'closed')
        amount = sum(float(x['amount_sol']) for x in legs)
        entry=root['context'].get('entry_evidence') or root['context'].get('token') or {}
        entry_market={k:entry.get(k) for k in MARKET_KEYS}
        entry_market['market_cap_is_fdv']=entry.get('market_cap_is_fdv',bool(root.get('entry_cap_is_fdv')))
        if entry_market.get('market_cap_usd') is None:entry_market['market_cap_usd']=root.get('entry_market_cap_usd')
        results.append({'book': book, 'root_id': root_id, 'mint': root['mint'], 'symbol': root.get('symbol'),
                        'entry_time': root['entry_time'], 'exit_time': max((x['exit_time'] or 0) for x in legs) if complete else None,
                        'complete': complete, 'costed': costed, 'legs': len(legs), 'amount_sol': amount,
                        'net_pnl_sol': realized, 'return_pct': 100 * realized / amount if complete and amount else None,
                        'entry_market_cap_usd': root.get('entry_market_cap_usd'),
                        'entry_market': entry_market,
                        'activity': ((root['context'].get('entry_evidence') or root['context'].get('token') or {}).get('research') or {}).get('activity') or {},
                        'features': ((root['context'].get('entry_evidence') or root['context'].get('token') or {}).get('research') or {}).get('features') or {},
                        'exit_reason': root.get('exit_reason')})
    return sorted(results, key=lambda x: x['entry_time'])


def metrics(items):
    closed = sorted((x for x in items if x['complete'] and x['costed']), key=lambda x: x['exit_time'])
    pnl = [x['net_pnl_sol'] for x in closed]
    wins = [x for x in pnl if x > 1e-12]; losses = [x for x in pnl if x < -1e-12]
    cumulative = peak = drawdown = 0
    for value in pnl:
        cumulative += value; peak = max(peak, cumulative); drawdown = max(drawdown, peak - cumulative)
    return {'completed_positions': len(closed), 'open_positions': sum(not x['complete'] for x in items),
            'legacy_completed_positions': sum(x['complete'] and not x['costed'] for x in items),
            'win_rate_pct': round(100 * len(wins) / len(pnl), 1) if pnl else None,
            'average_win_sol': sum(wins) / len(wins) if wins else None,
            'average_loss_sol': sum(losses) / len(losses) if losses else None,
            'average_net_sol': sum(pnl) / len(pnl) if pnl else None, 'net_pnl_sol': sum(pnl),
            'profit_factor': sum(wins) / -sum(losses) if losses else None,
            'realized_drawdown_sol': drawdown,
            'distinct_coins': len({x['mint'] for x in closed}),
            'scope': 'Latest 5000 fills grouped by original position. Win rate excludes open remainders and legacy fills. Drawdown is completed-position realized drawdown, not intratrade equity drawdown.'}


def summary(book):
    items = positions(book)
    ensure()
    with store.conn() as c:
        rows = c.execute('SELECT kind,COUNT(*) n FROM learning_decisions WHERE book=? GROUP BY kind', (book,)).fetchall()
    return {'metrics': metrics(items), 'recent_positions': items[-12:][::-1],
            'recorded_decisions': {x['kind']: x['n'] for x in rows},
            'scope': 'Decision records are a dataset for evaluation; neither JEV nor Gemini weights are automatically trained.'}
