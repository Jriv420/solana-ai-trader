import json,sqlite3,time
from pathlib import Path
DB=Path(__file__).resolve().parent/"trades.sqlite3"
class Store:
    def __init__(self):
        with self.conn() as c:c.execute('CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY AUTOINCREMENT,mint TEXT,symbol TEXT,entry_price_usd REAL,exit_price_usd REAL,amount_sol REAL,entry_time REAL,exit_time REAL,status TEXT,pnl_pct REAL,pnl_sol REAL,exit_reason TEXT,context_json TEXT)')
    def conn(self):
        c=sqlite3.connect(DB);c.row_factory=sqlite3.Row;return c
    def row(self,r):
        x=dict(r);raw=x.pop("context_json",None);x["context"]=json.loads(raw) if raw else {};return x
    def create_trade(self,t):
        with self.conn() as c:
            cur=c.execute('INSERT INTO trades(mint,symbol,entry_price_usd,amount_sol,entry_time,status,context_json) VALUES(?,?,?,?,?,"open",?)',(t["mint"],t.get("symbol"),t["entry_price_usd"],t["amount_sol"],t["entry_time"],json.dumps(t.get("context",{}))));t["id"]=cur.lastrowid
        return t
    def close_trade(self,i,price,tm,pct,sol,reason):
        with self.conn() as c:c.execute("UPDATE trades SET exit_price_usd=?,exit_time=?,status='closed',pnl_pct=?,pnl_sol=?,exit_reason=? WHERE id=?",(price,tm,pct,sol,reason,i))
    def open(self):
        with self.conn() as c:rows=c.execute("SELECT * FROM trades WHERE status='open'").fetchall()
        return [self.row(r) for r in rows]
    def all(self):
        with self.conn() as c:rows=c.execute("SELECT * FROM trades ORDER BY entry_time DESC LIMIT 200").fetchall()
        return [self.row(r) for r in rows]
    def realized(self):
        with self.conn() as c:r=c.execute("SELECT COALESCE(SUM(pnl_sol),0) p FROM trades WHERE status='closed'").fetchone()
        return float(r["p"] or 0)
    def ensure_observations(self):
        with self.conn() as c:
            c.execute('CREATE TABLE IF NOT EXISTS watched(mint TEXT PRIMARY KEY, first_seen REAL, last_seen REAL, observations INTEGER, creation_time REAL, latest_json TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY AUTOINCREMENT, mint TEXT, observed_at REAL, payload_json TEXT)')
    def record_launch(self, token):
        now=time.time()
        payload={"token":token,"status":"awaiting_data","observed_at":now}
        with self.conn() as c:
            c.execute('INSERT OR IGNORE INTO watched VALUES(?,?,?,?,?,?)', (token['mint'],now,now,0,token['created_at'],json.dumps(payload)))
            c.execute('UPDATE watched SET creation_time=COALESCE(creation_time,?) WHERE mint=?', (token['created_at'],token['mint']))
            self._prune(c)
    def record_observation(self, payload):
        now=time.time(); token=payload['token']; payload=dict(payload,observed_at=now)
        raw=json.dumps(payload)
        with self.conn() as c:
            c.execute('INSERT INTO watched VALUES(?,?,?,?,?,?) ON CONFLICT(mint) DO UPDATE SET last_seen=excluded.last_seen, observations=watched.observations+1, latest_json=excluded.latest_json', (token['mint'],now,now,1,token.get('created_at'),raw))
            c.execute('INSERT INTO observations(mint,observed_at,payload_json) VALUES(?,?,?)',(token['mint'],now,raw))
            self._prune(c)
    def _prune(self,c):
        c.execute('DELETE FROM watched WHERE mint NOT IN (SELECT mint FROM watched ORDER BY last_seen DESC LIMIT 2000)')
        c.execute('DELETE FROM observations WHERE id NOT IN (SELECT id FROM observations ORDER BY id DESC LIMIT 5000)')
    def watch_history(self, limit=200, mint=None):
        with self.conn() as c:
            if mint:
                rows=c.execute('SELECT payload_json FROM observations WHERE mint=? ORDER BY id DESC LIMIT ?', (mint,limit)).fetchall()
                return [json.loads(r['payload_json']) for r in rows]
            rows=c.execute('SELECT * FROM watched ORDER BY last_seen DESC LIMIT ?', (limit,)).fetchall()
        return [dict(json.loads(r['latest_json']), first_seen=r['first_seen'], last_seen=r['last_seen'], observations=r['observations']) for r in rows]
    def new_pairs(self):
        with self.conn() as c:
            rows=c.execute('SELECT * FROM watched WHERE creation_time>? ORDER BY creation_time DESC LIMIT 100', (time.time()-3600,)).fetchall()
        return [dict(json.loads(r['latest_json']), created_at=r['creation_time']) for r in rows]
    def watched_mints(self, limit=10, offset=0):
        with self.conn() as c:
            rows=c.execute('SELECT mint FROM watched WHERE observations>0 ORDER BY last_seen ASC').fetchall()
        return [rows[(offset+i)%len(rows)]['mint'] for i in range(min(limit,len(rows)))]
store=Store()
store.ensure_observations()
