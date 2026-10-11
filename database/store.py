import json,sqlite3,time,os
from datetime import datetime,timezone
from pathlib import Path
DEFAULT_DB=Path(__file__).resolve().parent/"trades.sqlite3"
DB=Path(os.getenv("DB_PATH") or (str(Path(os.environ["RAILWAY_VOLUME_MOUNT_PATH"])/"trades.sqlite3") if os.getenv("RAILWAY_VOLUME_MOUNT_PATH") else str(DEFAULT_DB)))
class Store:
    def __init__(self,trade_table="trades"):
        if trade_table not in {"trades","shadow_trades"}:raise ValueError("Invalid trade table")
        self.trade_table=trade_table
        with self.conn() as c:c.execute(f'CREATE TABLE IF NOT EXISTS {self.trade_table}(id INTEGER PRIMARY KEY AUTOINCREMENT,mint TEXT,symbol TEXT,entry_price_usd REAL,exit_price_usd REAL,amount_sol REAL,entry_time REAL,exit_time REAL,status TEXT,pnl_pct REAL,pnl_sol REAL,exit_reason TEXT,context_json TEXT)')
        with self.conn() as c:
            if 'peak_price_usd' not in {r['name'] for r in c.execute(f'PRAGMA table_info({self.trade_table})')}:c.execute(f'ALTER TABLE {self.trade_table} ADD COLUMN peak_price_usd REAL')
    def conn(self):
        DB.parent.mkdir(parents=True,exist_ok=True)
        c=sqlite3.connect(DB,timeout=15);c.row_factory=sqlite3.Row;return c
    def ai_request_count(self,provider,day):
        with self.conn() as c:
            c.execute('CREATE TABLE IF NOT EXISTS ai_requests(provider TEXT,day TEXT,attempts INTEGER,PRIMARY KEY(provider,day))')
            r=c.execute('SELECT attempts FROM ai_requests WHERE provider=? AND day=?',(provider,day)).fetchone()
        return r['attempts'] if r else 0
    def reserve_ai_request(self,provider,day,limit):
        # Count before sending, including failed requests and manual connection tests.
        with self.conn() as c:
            c.execute('CREATE TABLE IF NOT EXISTS ai_requests(provider TEXT,day TEXT,attempts INTEGER,PRIMARY KEY(provider,day))')
            c.execute('BEGIN IMMEDIATE')
            c.execute('INSERT OR IGNORE INTO ai_requests VALUES(?,?,0)',(provider,day))
            used=c.execute('SELECT attempts FROM ai_requests WHERE provider=? AND day=?',(provider,day)).fetchone()['attempts']
            if used>=max(0,limit):return False
            c.execute('UPDATE ai_requests SET attempts=attempts+1 WHERE provider=? AND day=?',(provider,day))
            c.execute('DELETE FROM ai_requests WHERE day<?',(day[:4]+'-01-01',))
        return True
    def row(self,r):
        x=dict(r);raw=x.pop("context_json",None);x["context"]=json.loads(raw) if raw else {};return x
    def create_trade(self,t):
        with self.conn() as c:
            cur=c.execute(f'INSERT INTO {self.trade_table}(mint,symbol,entry_price_usd,amount_sol,entry_time,status,context_json) VALUES(?,?,?,?,?,"open",?)',(t["mint"],t.get("symbol"),t["entry_price_usd"],t["amount_sol"],t["entry_time"],json.dumps(t.get("context",{}))));t["id"]=cur.lastrowid
        return t
    def close_trade(self,i,price,tm,pct,sol,reason):
        with self.conn() as c:
            result=c.execute(f"UPDATE {self.trade_table} SET exit_price_usd=?,exit_time=?,status='closed',pnl_pct=?,pnl_sol=?,exit_reason=? WHERE id=? AND status='open'",(price,tm,pct,sol,reason,i))
            return bool(result.rowcount)
    def open(self):
        with self.conn() as c:rows=c.execute(f"SELECT * FROM {self.trade_table} WHERE status='open'").fetchall()
        return [self.row(r) for r in rows]
    def all(self):
        with self.conn() as c:rows=c.execute(f"SELECT * FROM {self.trade_table} ORDER BY entry_time DESC LIMIT 200").fetchall()
        return [self.row(r) for r in rows]
    def mark_peak(self,i,price):
        with self.conn() as c:c.execute(f'UPDATE {self.trade_table} SET peak_price_usd=MAX(COALESCE(peak_price_usd,entry_price_usd),?) WHERE id=? AND status="open"',(price,i))
    def daily_realized(self,now=None):
        now=time.time() if now is None else now
        start=datetime.fromtimestamp(now,timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        with self.conn() as c:r=c.execute(f'SELECT COALESCE(SUM(pnl_sol),0) p FROM {self.trade_table} WHERE exit_time>=? AND exit_time<=? AND status="closed"',(start,now)).fetchone()
        return float(r['p'])
    def paper_metrics(self):
        with self.conn() as c:
            rows=c.execute(f'SELECT pnl_sol,context_json FROM {self.trade_table} WHERE status="closed"').fetchall()
        pnl=[float(r['pnl_sol'] or 0) for r in rows];n=len(pnl)
        fills=sum(bool(json.loads(r['context_json'] or '{}').get('paper_fill')) for r in rows)
        return {'closed_trades':n,'cost_model_trades':fills,'legacy_trades':n-fills,'win_rate_pct':round(100*sum(x>0 for x in pnl)/n,1) if n else None,'net_pnl_sol':sum(pnl),'daily_realized_sol':self.daily_realized(),'daily_window':'UTC calendar day','scope':'Simulated fills; not executable profit.'}
    def realized(self):
        with self.conn() as c:r=c.execute(f"SELECT COALESCE(SUM(pnl_sol),0) p FROM {self.trade_table} WHERE status='closed'").fetchone()
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
