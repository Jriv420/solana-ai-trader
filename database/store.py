import json,sqlite3
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
store=Store()
