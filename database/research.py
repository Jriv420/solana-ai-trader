"""Point-in-time narrative evidence and forward-only outcomes, in the existing SQLite DB."""
import json
import math
import time
from statistics import median
from database.store import store

HORIZONS={'5m':300,'1h':3600,'24h':86400}

def finite(value):
    try:
        n=float(value)
        return n if math.isfinite(n) else None
    except (TypeError,ValueError):return None

class Research:
    def ensure(self):
        with store.conn() as c:
            c.execute('CREATE TABLE IF NOT EXISTS research_claims(id INTEGER PRIMARY KEY,mint TEXT,wallet TEXT,created_at REAL,payload_json TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS research_events(signature TEXT,wallet TEXT,mint TEXT,event_time REAL,payload_json TEXT,PRIMARY KEY(signature,wallet,mint))')
            c.execute('CREATE TABLE IF NOT EXISTS research_checks(mint TEXT PRIMARY KEY,checked_at REAL,payload_json TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS research_cases(id INTEGER PRIMARY KEY,mint TEXT,started_at REAL,baseline REAL,features_json TEXT,peak REAL,trough REAL,worst_drawdown REAL DEFAULT 0,UNIQUE(mint,features_json))')
            if 'worst_drawdown' not in {r['name'] for r in c.execute('PRAGMA table_info(research_cases)')}:c.execute('ALTER TABLE research_cases ADD COLUMN worst_drawdown REAL DEFAULT 0')
            c.execute('CREATE TABLE IF NOT EXISTS research_outcomes(case_id INTEGER,horizon TEXT,measured_at REAL,return_pct REAL,peak_pct REAL,drawdown_pct REAL,PRIMARY KEY(case_id,horizon))')
            c.execute('CREATE INDEX IF NOT EXISTS research_claims_mint ON research_claims(mint,id)')
            c.execute('CREATE INDEX IF NOT EXISTS research_events_mint ON research_events(mint,event_time)')
            c.execute('CREATE INDEX IF NOT EXISTS research_cases_features ON research_cases(features_json,started_at)')
    def claim(self,mint,payload):
        with store.conn() as c:
            cur=c.execute('INSERT INTO research_claims(mint,wallet,created_at,payload_json) VALUES(?,?,?,?)',(mint,payload.get('wallet'),time.time(),json.dumps(payload)))
            c.execute('DELETE FROM research_claims WHERE id NOT IN (SELECT id FROM research_claims ORDER BY id DESC LIMIT 5000)')
        return cur.lastrowid
    def claims(self,mint):
        with store.conn() as c:rows=c.execute('SELECT * FROM research_claims WHERE mint=? ORDER BY id DESC LIMIT 100',(mint,)).fetchall()
        return [dict(json.loads(r['payload_json']),id=r['id'],recorded_at=r['created_at'],provenance='user_reviewed') for r in rows]
    def mints(self):
        with store.conn() as c:rows=c.execute('SELECT mint FROM research_claims GROUP BY mint ORDER BY MAX(created_at) DESC LIMIT 20').fetchall()
        return [r[0] for r in rows]
    def events(self,mint):
        with store.conn() as c:rows=c.execute('SELECT payload_json FROM research_events WHERE mint=? ORDER BY event_time DESC LIMIT 200',(mint,)).fetchall()
        return [json.loads(r[0]) for r in rows]
    def event(self,event):
        with store.conn() as c:
            c.execute('INSERT OR IGNORE INTO research_events VALUES(?,?,?,?,?)',(event['signature'],event['wallet'],event['mint'],event['timestamp'],json.dumps(event)))
            c.execute('DELETE FROM research_events WHERE rowid NOT IN (SELECT rowid FROM research_events ORDER BY event_time DESC LIMIT 20000)')
    def check(self,mint,payload):
        with store.conn() as c:
            c.execute('INSERT INTO research_checks VALUES(?,?,?) ON CONFLICT(mint) DO UPDATE SET checked_at=excluded.checked_at,payload_json=excluded.payload_json',(mint,time.time(),json.dumps(payload)))
            c.execute('DELETE FROM research_checks WHERE mint NOT IN (SELECT mint FROM research_checks ORDER BY checked_at DESC LIMIT 2000)')
    def security(self,mint):
        with store.conn() as c:r=c.execute('SELECT * FROM research_checks WHERE mint=?',(mint,)).fetchone()
        if not r:return {'status':'pending','risks':[],'message':'RugCheck has not checked this coin yet.'}
        result=dict(json.loads(r['payload_json']),checked_at=r['checked_at'])
        if time.time()-r['checked_at']>600:result.update(status='stale',message='Security check is stale; not cleared for entry.')
        return result
    def snapshot(self,token,features,now=None):
        now=time.time() if now is None else now
        price=finite(token.get('price_usd'));timestamp=finite(token.get('timestamp'))
        if not price or price<=0 or timestamp is None or not 0<=now-timestamp<=120:return
        key=json.dumps(features,sort_keys=True)
        with store.conn() as c:
            # Features never change retroactively; a changed claim starts a separate case.
            c.execute('INSERT OR IGNORE INTO research_cases(mint,started_at,baseline,features_json,peak,trough) VALUES(?,?,?,?,?,?)',(token['mint'],now,price,key,price,price))
            cases=c.execute('SELECT * FROM research_cases WHERE mint=? AND started_at>?',(token['mint'],now-90000)).fetchall()
            for r in cases:
                peak=max(price,r['peak']);trough=min(price,r['trough']);drawdown=min(r['worst_drawdown'],100*(price/peak-1))
                c.execute('UPDATE research_cases SET peak=?,trough=?,worst_drawdown=? WHERE id=?',(peak,trough,drawdown,r['id']))
                for label,seconds in HORIZONS.items():
                    elapsed=now-r['started_at'];tolerance=max(120,seconds*.1)
                    # Only fresh observations near the deadline; missed windows stay missing.
                    if seconds<=elapsed<=seconds+tolerance:
                        c.execute('INSERT OR IGNORE INTO research_outcomes VALUES(?,?,?,?,?,?)',(r['id'],label,now,100*(price/r['baseline']-1),100*(peak/r['baseline']-1),drawdown))
            c.execute('DELETE FROM research_cases WHERE id NOT IN (SELECT id FROM research_cases ORDER BY id DESC LIMIT 10000)')
            c.execute('DELETE FROM research_outcomes WHERE case_id NOT IN (SELECT id FROM research_cases)')
    def learning(self,features,horizon='1h'):
        key=json.dumps(features,sort_keys=True)
        with store.conn() as c:rows=c.execute('SELECT c.mint,o.* FROM research_outcomes o JOIN research_cases c ON c.id=o.case_id WHERE c.features_json=? AND o.horizon=? ORDER BY c.started_at',(key,horizon)).fetchall()
        # One earliest case per coin; repeated scans cannot inflate sample size.
        distinct={}
        for r in rows:distinct.setdefault(r['mint'],dict(r))
        data=list(distinct.values());n=len(data)
        returns=[r['return_pct'] for r in data];dips=sum(r['drawdown_pct']<=-30 for r in data)
        return {'status':'learning' if n<10 else 'observed_pattern','horizon':horizon,'distinct_coins':n,'median_return_pct':round(median(returns),2) if n else None,'positive_outcome_pct':round(100*sum(x>0 for x in returns)/n,1) if n else None,'sharp_dip_pct':round(100*dips/n,1) if n else None,'gain_50pct_frequency':round(100*sum(r['peak_pct']>=50 for r in data)/n,1) if n else None,'loss_50pct_frequency':round(100*sum(r['return_pct']<=-50 for r in data)/n,1) if n else None,'risk_adjustment':round(10*dips/n,1) if n>=10 else 0,'scope':'Forward observed prices; no trade fees/slippage, no causal endorsement claim. Missing prices are not treated as coin death.'}
    def detail(self,mint):
        from intelligence.narrative import context
        result=context(mint)
        with store.conn() as c:rows=c.execute('SELECT c.started_at,c.features_json,o.* FROM research_cases c LEFT JOIN research_outcomes o ON o.case_id=c.id WHERE c.mint=? ORDER BY c.started_at DESC LIMIT 30',(mint,)).fetchall()
        result['outcomes']=[dict(r) for r in rows]
        return result
research=Research()
research.ensure()
