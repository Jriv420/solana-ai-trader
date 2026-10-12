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


def provider_performance(book,items):
    # Distinct completed positions per provider, not repeated reviews counted as wins.
    outcomes={x['root_id']:x for x in items if x['complete'] and x['costed']};groups=defaultdict(set)
    with store.conn() as c:rows=c.execute("SELECT trade_id,payload_json FROM learning_decisions WHERE book=? AND kind IN ('entry','exit_review') ORDER BY id DESC LIMIT 1000",(book,)).fetchall()
    for r in rows:
        if r['trade_id'] not in outcomes:continue
        payload=json.loads(r['payload_json']);team=payload.get('team') or {}
        for review in team.get('reviews',[]):
            if review.get('status')=='verified_response':groups[review['provider']].add(r['trade_id'])
    return [{'provider':name,'completed_positions':len(ids),'average_return_pct':sum(outcomes[i]['return_pct'] for i in ids)/len(ids),'win_rate_pct':100*sum(outcomes[i]['net_pnl_sol']>0 for i in ids)/len(ids),
             'scope':'Observed results on positions reviewed by this model, not its standalone strategy, causal contribution or forecast calibration.'} for name,ids in groups.items()]

def summary(book):
    items = positions(book)
    ensure()
    with store.conn() as c:
        rows = c.execute('SELECT kind,COUNT(*) n FROM learning_decisions WHERE book=? GROUP BY kind', (book,)).fetchall()
    return {'provider_performance':provider_performance(book,items),'metrics': metrics(items), 'recent_positions': items[-12:][::-1],
            'recorded_decisions': {x['kind']: x['n'] for x in rows},
            'scope': 'Decision records are a dataset for evaluation; neither JEV nor Gemini weights are automatically trained.'}


def shared_lessons(limit=8,now=None):
    now=time.time() if now is None else now
    items=[p for book in ('trades','shadow_trades') for p in positions(book) if p['complete'] and p['costed'] and p['exit_time']<now and p['entry_time']>=now-30*86400]
    seen=set();out=[]
    for p in sorted(items,key=lambda x:x['exit_time'],reverse=True):
        if p['mint'] in seen:continue
        seen.add(p['mint'])
        from intelligence.exit_learning import review
        out.append(dict({k:p[k] for k in ('book','root_id','mint','entry_time','exit_time','net_pnl_sol','return_pct','exit_reason','features')},after_exit_review=review(p['book'],p['root_id'])))
        if len(out)>=limit:break
    return {'positions':out,'scope':'Shared completed costed outcomes from both paper accounts, one latest case per coin, preceding this decision. Account source is retained; different policies can explain different outcomes. No weight training or assumed improvement.'}
