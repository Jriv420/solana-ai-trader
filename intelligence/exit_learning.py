"""Sample what happens after paper exits; this does not change exit policy."""
import time
from database.store import store,valid_cap
RUNNER='MLn86AfgezEPPKd4SNQZ5txM7SVSDTDGEyYhnpNpump'
FEEDBACK={'engagement':'genuine — user reported, unverified','narrative':'User reports strong narrative and room to grow from a $38.2K entry.','moonbag_candidate':True,'scope':'Retrospective user feedback, not evidence known at entry or an instruction to buy.'}
def ensure():
    with store.conn() as c:
        c.execute('CREATE TABLE IF NOT EXISTS exit_reviews(book TEXT,trade_id INTEGER,mint TEXT,exit_time REAL,baseline REAL,peak REAL,low REAL,last REAL,samples INTEGER DEFAULT 0,last_at REAL,PRIMARY KEY(book,trade_id))')
        c.execute('CREATE INDEX IF NOT EXISTS exit_reviews_mint ON exit_reviews(mint,exit_time)')
def start(book,trade_id,token,exit_time=None):
    ensure();price=valid_cap(token.get('price_usd'))
    if price is None:return
    with store.conn() as c:
        c.execute('INSERT OR IGNORE INTO exit_reviews VALUES(?,?,?,?,?,?,?,?,0,NULL)',(book,trade_id,token['mint'],exit_time or time.time(),price,price,price,price))
        c.execute('DELETE FROM exit_reviews WHERE rowid NOT IN (SELECT rowid FROM exit_reviews ORDER BY exit_time DESC LIMIT 2000)')
def observe(token):
    ensure();now=time.time();price=valid_cap(token.get('price_usd'));timestamp=valid_cap(token.get('timestamp'))
    if price is None or timestamp is None or not 0<=now-timestamp<=120:return
    with store.conn() as c:
        c.execute('UPDATE exit_reviews SET peak=MAX(peak,?),low=MIN(low,?),last=?,samples=samples+1,last_at=? WHERE mint=? AND exit_time<? AND exit_time>=? AND (last_at IS NULL OR last_at<?)',(price,price,price,timestamp,token['mint'],timestamp,now-3600,timestamp))
def mints():
    ensure()
    # Resume one-hour reviews for recent trades closed before this feature deployed.
    for book in ('trades','shadow_trades'):
        with store.conn() as c:
            exists=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(book,)).fetchone()
            rows=c.execute(f"SELECT id,mint,exit_time,exit_price_usd,context_json FROM {book} WHERE status='closed' AND exit_time>? ORDER BY exit_time DESC LIMIT 100",(time.time()-3600,)).fetchall() if exists else []
        import json
        for r in rows:
            fill=json.loads(r['context_json'] or '{}').get('paper_fill') or {}
            factor=1-float(fill.get('slippage_bps') or 0)/10000
            price=valid_cap(r['exit_price_usd'])
            if price and factor>0:start(book,r['id'],{'mint':r['mint'],'price_usd':price/factor},r['exit_time'])
    with store.conn() as c:rows=c.execute('SELECT mint FROM exit_reviews WHERE exit_time>? GROUP BY mint ORDER BY COALESCE(MIN(last_at),0) LIMIT 3',(time.time()-3600,)).fetchall()
    return [r['mint'] for r in rows]
def review(book,trade_id):
    ensure()
    with store.conn() as c:r=c.execute('SELECT * FROM exit_reviews WHERE book=? AND trade_id=?',(book,trade_id)).fetchone()
    if not r:return None
    x=dict(r);base=x['baseline']
    return {'samples':x['samples'],'peak_after_exit_pct':round((x['peak']/base-1)*100,1),'low_after_exit_pct':round((x['low']/base-1)*100,1),'last_after_exit_pct':round((x['last']/base-1)*100,1),'complete':time.time()-x['exit_time']>=3600,'scope':'One-hour sampled spot-price changes after exit; no fees, hypothetical trade return or guarantee. Missing samples stay missing.'}
def context(mint):
    ensure()
    with store.conn() as c:rows=c.execute('SELECT book,trade_id FROM exit_reviews WHERE mint=? ORDER BY exit_time DESC LIMIT 5',(mint,)).fetchall()
    return {'recent_exits':[review(r['book'],r['trade_id']) for r in rows],'user_feedback':FEEDBACK if mint==RUNNER else None,'scope':'Observational feedback only. Fixed exits remain active; models are not retrained.'}
