"""Use fresh tracked holdings and qualified reputation; whale wealth is not skill."""
import time
from database.wallet_registry import wallet_registry


def score_wallet_context(token,wallet_profile=None,overlap_count=0):
    from database.store import store
    with store.conn() as c:positions=c.execute('SELECT address,value_usd,checked_at FROM wallet_positions WHERE mint=? AND checked_at>? AND value_usd>0',(token['mint'],time.time()-900)).fetchall()
    registry={w['address']:w for w in wallet_registry.list() if w['tracking']}
    holders=[registry[p['address']] for p in positions if p['address'] in registry]
    profitable=[w for w in holders if w['profitable']]
    whales=[w for w in holders if w['whale']]
    score=40
    if profitable:score=50+min(25,max(float(w['profile'].get('score') or 0) for w in profitable)*.25)+min(15,(len(profitable)-1)*5)
    elif holders:score=45+min(4,len(holders))
    if profitable and whales:score+=min(5,len(whales))
    return {'score':round(min(100,score),1),'status':'observed' if holders else 'no_fresh_holdings','qualified_holders':len(profitable),'tracked_holders':len(holders),'whale_holders':len(whales),'addresses':[w['address'] for w in holders],'reason':'Fresh scanned holdings + qualified observed reputation; manual labels and whale size do not establish profitability.'}
