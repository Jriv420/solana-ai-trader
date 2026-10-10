"""Persistent wallet candidates, manual pins, observed positions, and trade evidence."""
import json
import time
from database.store import store

class WalletRegistry:
    def __init__(self):self.ensure()
    def ensure(self):
        with store.conn() as c:
            c.execute('CREATE TABLE IF NOT EXISTS wallets(address TEXT PRIMARY KEY,label TEXT,manual INTEGER DEFAULT 0,disabled INTEGER DEFAULT 0,first_seen REAL,last_seen REAL,evaluated_at REAL DEFAULT 0,profile_json TEXT DEFAULT "{}")')
            c.execute('CREATE TABLE IF NOT EXISTS wallet_positions(address TEXT,mint TEXT,balance TEXT,value_usd REAL,checked_at REAL,PRIMARY KEY(address,mint))')
            c.execute('CREATE TABLE IF NOT EXISTS wallet_evidence(id INTEGER PRIMARY KEY AUTOINCREMENT,address TEXT,signature TEXT,observed_at REAL,slot INTEGER,event_json TEXT,UNIQUE(address,signature))')
    def add(self,address,label=None,manual=False):
        now=time.time()
        with store.conn() as c:
            c.execute('INSERT INTO wallets(address,label,manual,first_seen,last_seen) VALUES(?,?,?,?,?) ON CONFLICT(address) DO UPDATE SET last_seen=excluded.last_seen, manual=MAX(wallets.manual,excluded.manual),label=CASE WHEN excluded.manual=1 THEN excluded.label ELSE wallets.label END,disabled=CASE WHEN excluded.manual=1 THEN 0 ELSE wallets.disabled END', (address,label or address[:6]+'…'+address[-4:],int(manual),now,now))
            c.execute('DELETE FROM wallets WHERE manual=0 AND disabled=0 AND address NOT IN (SELECT address FROM wallets WHERE manual=0 AND disabled=0 ORDER BY last_seen DESC LIMIT 1000)')
            for table in ('wallet_positions','wallet_evidence'):c.execute(f'DELETE FROM {table} WHERE address NOT IN (SELECT address FROM wallets)')
    def disable(self,address):
        with store.conn() as c:c.execute('UPDATE wallets SET disabled=1 WHERE address=?',(address,))
    def position(self,address,mint,balance,value):
        with store.conn() as c:c.execute('INSERT INTO wallet_positions VALUES(?,?,?,?,?) ON CONFLICT(address,mint) DO UPDATE SET balance=excluded.balance,value_usd=excluded.value_usd,checked_at=excluded.checked_at',(address,mint,str(balance),float(value),time.time()))
    def evidence(self,address,events,reset=False):
        with store.conn() as c:
            if reset:c.execute('DELETE FROM wallet_evidence WHERE address=?',(address,))
            for event in events:
                c.execute('INSERT OR IGNORE INTO wallet_evidence(address,signature,observed_at,slot,event_json) VALUES(?,?,?,?,?)',(address,event['signature'],event['timestamp'],event.get('slot',0),json.dumps(event)))
    def events(self,address):
        with store.conn() as c:rows=c.execute('SELECT event_json FROM wallet_evidence WHERE address=? ORDER BY observed_at,slot,id',(address,)).fetchall()
        return [json.loads(r[0]) for r in rows]
    def profile(self,address,profile):
        with store.conn() as c:c.execute('UPDATE wallets SET profile_json=?,evaluated_at=? WHERE address=?',(json.dumps(profile),time.time(),address))
    def list(self):
        with store.conn() as c:
            rows=c.execute('SELECT * FROM wallets ORDER BY manual DESC,evaluated_at DESC').fetchall()
            positions=c.execute('SELECT address,MAX(value_usd) peak,SUM(value_usd) total FROM wallet_positions WHERE checked_at>? GROUP BY address',(time.time()-900,)).fetchall()
        values={r['address']:r for r in positions};out=[]
        from config.settings import settings
        for r in rows:
            x=dict(r);p=json.loads(x.pop('profile_json'));v=values.get(x['address']);x['profile']=p
            x['largest_position_usd']=v['peak'] if v else None
            x['observed_portfolio_usd']=v['total'] if v else None
            x['whale']=bool(v and (v['peak']>=settings.whale_position_usd or v['total']>=settings.whale_portfolio_usd))
            x['profitable']=bool(p.get('qualified') and p.get('data_status')=='ok' and time.time()-x['evaluated_at']<3600)
            x['tracking']=not x['disabled'] and bool(x['manual'] or x['whale'] or x['profitable'])
            x['tags']=(['Manual'] if x['manual'] else [])+(['Whale'] if x['whale'] else [])+(['Profitable'] if x['profitable'] else [])
            out.append(x)
        out.sort(key=lambda x:(x['tracking'],x['manual'],x['profile'].get('score',0),x['largest_position_usd'] or 0),reverse=True)
        return out
    def tracking_wallets(self):
        return [dict(address=x['address'],label=x['label'],tags=x['tags']) for x in self.list() if x['tracking']]
    def candidates(self,limit=2):
        with store.conn() as c:rows=c.execute('SELECT address FROM wallets WHERE disabled=0 AND evaluated_at<? ORDER BY evaluated_at,manual DESC LIMIT ?',(time.time()-600,limit)).fetchall()
        return [r[0] for r in rows]
wallet_registry=WalletRegistry()
