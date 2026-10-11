"""Bounded, empirical paper-entry adaptation. Never train model weights or loosen safety gates."""
import json,math,time,logging
from collections import defaultdict
from database.store import store,valid_cap
from intelligence.trade_evaluation import positions
from intelligence.market_regime import market_features
from config.settings import settings
VERSION='entry-loss-v1'
_CACHE={}


def groups(token):
    # Reconstruct market groups from the saved entry, never today's token labels.
    r=token.get('research') or {};f=market_features(token,r.get('security') or {})
    liquidity=valid_cap(token.get('liquidity_usd'))
    liq='under_20k' if liquidity and liquidity<20000 else '20k_plus' if liquidity else 'unknown'
    result=[]
    if f['market_cap_group']!='unknown' and liq!='unknown':
        result.append('market:'+f['cap_basis']+':'+f['market_cap_group']+':'+liq+':'+f['volume_to_cap_group'])
    bundle=(r.get('features') or {}).get('launch_bundle_group')
    if bundle in {'under_5','5_to_20','20_plus'}:result.append('launch_bundle:'+bundle)
    return result


def history(book,now):
    import database.store as db
    key=(str(db.DB),book);cached=_CACHE.get(key)
    if cached and 0<=now-cached[0]<30:return cached[1]
    items=sorted((p for p in positions(book) if p['complete'] and p['costed'] and p['exit_time']<now and p['entry_time']>=now-30*86400 and math.isfinite(p['return_pct'])),key=lambda p:p['exit_time'])[-500:]
    _CACHE[key]=(now,items)
    if len(_CACHE)>4:_CACHE.pop(next(iter(_CACHE)))
    return items


def assess(book,token,now=None):
    now=time.time() if now is None else now
    items=history(book,now)
    # One recent completed position per distinct coin per group. Repeated trading is not independent evidence.
    grouped=defaultdict(dict)
    for p in sorted(items,key=lambda x:x['exit_time']):
        if p['mint']==token['mint']:continue
        for group in groups(dict(p.get('entry_market') or {},research={'features':p.get('features') or {}})):grouped[group][p['mint']]=p
    matches=[]
    for group in groups(token):
        sample=list(grouped[group].values());n=len(sample)
        losses=sum(p['return_pct']<0 for p in sample);severe=sum(p['return_pct']<=-50 for p in sample)
        average=sum(p['return_pct'] for p in sample)/n if n else None
        avoid=n>=8 and losses/n>=.6 and severe>=2 and average<0
        matches.append({'group':group,'distinct_coins':n,'loss_rate_pct':round(100*losses/n,1) if n else None,
                        'average_net_return_pct':round(average,2) if average is not None else None,
                        'severe_losses':severe,'avoid':avoid})
    repeat=next((p for p in sorted(items,key=lambda x:x['exit_time'],reverse=True) if p['mint']==token['mint'] and p['return_pct']<=-50 and now-p['exit_time']<86400),None)
    avoid=bool(repeat or any(m['avoid'] for m in matches))
    return {'version':VERSION,'action':'avoid' if avoid else 'allow','checked_at':now,'matches':matches,
            'reason':'24h cooldown after this contract lost at least 50%' if repeat else 'Matching entry cohort has repeated severe losses and negative average net return' if avoid else 'No sufficiently supported loss pattern; existing rules still apply',
            'scope':'Paper-only empirical gate, not a profit probability or model training. Latest 500 completed costed positions within 30 days; one coin per cohort, candidate coin excluded from cohort statistics. Unknown data does not establish a pattern. A cohort needs 8 coins, at least 60% losses, 2 losses of 50% or worse and negative average return. Correlation can reflect the old exit policy, market regime or missing data. No safety checks are relaxed.'}


def safe_assess(book,token):
    try:return assess(book,token)
    except Exception as exc:
        logging.getLogger('uvicorn.error').warning('NEXUS entry learning unavailable %s',type(exc).__name__)
        # New paper entries wait rather than silently bypassing a learned restriction.
        return {'version':VERSION,'action':'wait','matches':[],'reason':'Entry-learning evidence unavailable; wait for next scan'}


def ensure():
    with store.conn() as c:
        c.execute('CREATE TABLE IF NOT EXISTS entry_learning_trials(id INTEGER PRIMARY KEY,book TEXT,mint TEXT,bucket INTEGER,started_at REAL,price REAL,sol REAL,fee_bps REAL,slip_bps REAL,decision_json TEXT,last_at REAL,samples INTEGER DEFAULT 0,outcome_json TEXT,UNIQUE(book,mint,bucket))')
        c.execute('CREATE INDEX IF NOT EXISTS entry_learning_mint ON entry_learning_trials(mint)')


def screen(book,token,decision,now=None):
    now=time.time() if now is None else now
    price=valid_cap(token.get('price_usd'));sol=valid_cap(token.get('sol_price_usd'));stamp=valid_cap(token.get('timestamp'))
    if not price or not sol or not stamp or not 0<=now-stamp<=120:return
    ensure()
    with store.conn() as c:
        inserted=c.execute('INSERT OR IGNORE INTO entry_learning_trials(book,mint,bucket,started_at,price,sol,fee_bps,slip_bps,decision_json) VALUES(?,?,?,?,?,?,?,?,?)',
                  (book,token['mint'],int(now//3600),now,price,sol,max(0,min(settings.paper_fee_bps,5000)),max(0,min(settings.paper_slippage_bps,5000)),json.dumps(decision))).rowcount
        c.execute('DELETE FROM entry_learning_trials WHERE id NOT IN (SELECT id FROM entry_learning_trials ORDER BY id DESC LIMIT 3000)')
    if inserted:
        logging.getLogger('uvicorn.error').info('NEXUS entry learning screen book=%s action=%s cohort_coins=%s',book,decision['action'],[x['distinct_coins'] for x in decision.get('matches') or []])


def observe(token,now=None):
    now=time.time() if now is None else now
    price=valid_cap(token.get('price_usd'));sol=valid_cap(token.get('sol_price_usd'));stamp=valid_cap(token.get('timestamp'))
    if not price or not sol or not stamp or not 0<=now-stamp<=120:return
    ensure()
    with store.conn() as c:
        rows=c.execute('SELECT * FROM entry_learning_trials WHERE mint=? AND outcome_json IS NULL AND started_at>=?',(token['mint'],now-7200)).fetchall()
        for row in rows:
            if stamp<=row['started_at'] or stamp<=(row['last_at'] or 0):continue
            outcome=None
            # First fresh observation 60–70 minutes later. Later prices do not fill missing history.
            elapsed=stamp-row['started_at']
            if 3600<=elapsed<=4200:
                fee=row['fee_bps']/10000;slip=row['slip_bps']/10000
                net=(price/row['price'])*(row['sol']/sol)*(1-slip)/(1+slip)*(1-fee)/(1+fee)-1
                outcome=json.dumps({'net_return_pct':100*net,'observed_at':stamp,'elapsed_seconds':elapsed,'scope':'One-hour hypothetical mark after estimated round-trip proportional costs; no strategy exits, portfolio capacity, liquidity impact or guaranteed execution.'})
            c.execute('UPDATE entry_learning_trials SET last_at=?,samples=samples+1,outcome_json=? WHERE id=?',(stamp,outcome,row['id']))


def safe_screen(*args):
    try:screen(*args)
    except Exception as exc:logging.getLogger('uvicorn.error').warning('NEXUS entry screen record unavailable %s',type(exc).__name__)


def safe_observe(token):
    try:observe(token)
    except Exception as exc:logging.getLogger('uvicorn.error').warning('NEXUS entry screen observation unavailable %s',type(exc).__name__)


def summary(book):
    ensure()
    with store.conn() as c:rows=c.execute('SELECT * FROM entry_learning_trials WHERE book=? ORDER BY id DESC LIMIT 1000',(book,)).fetchall()
    completed=defaultdict(list);recent=[];pending=missing=0
    for row in rows:
        decision=json.loads(row['decision_json']);outcome=json.loads(row['outcome_json']) if row['outcome_json'] else None
        if outcome:completed[decision['action']].append(outcome['net_return_pct'])
        elif time.time()-row['started_at']>4200:missing+=1
        else:pending+=1
        if len(recent)<8:recent.append({'mint':row['mint'],'at':row['started_at'],'decision':decision,'outcome':outcome})
    evidence=history(book,time.time())
    return {'version':VERSION,'completed_evidence_positions':len(evidence),'recent':recent,'recorded_screens':len(rows),'pending':pending,'missing':missing,
            'outcomes':{a:{'samples':len(v),'positive_pct':round(100*sum(x>0 for x in v)/len(v),1),'mean_net_return_pct':round(sum(v)/len(v),2)} for a,v in completed.items()},
            'scope':'Learning changes paper entries only. Fixed cohort definitions; evidence updates as trades complete. Forward one-hour marks track allowed AND avoided candidates, not a trading win rate. Allow means this learner permitted entry, not that a buy filled; account limits still apply. First eligible screen per coin/account/UTC hour; repeated coins across hours are correlated. Missing marks remain missing. Coverage and selection bias prevent claiming strategy improvement from these averages. No automatic model-weight training.'}
