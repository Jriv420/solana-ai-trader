"""Sample what happens after paper exits; this does not change exit policy."""
import time
from database.store import store,valid_cap
RUNNER='MLn86AfgezEPPKd4SNQZ5txM7SVSDTDGEyYhnpNpump'
FEEDBACK={'engagement':'genuine — user reported, unverified','narrative':'User reports strong narrative and room to grow from a $38.2K entry.','moonbag_candidate':True,'scope':'Retrospective user feedback, not evidence known at entry or an instruction to buy.'}
DOPE='FiLRrZ7Bt2HHGfs83RFJdGmp3mLceycq3zkDN6Apump'
DOPE_CASE={'mint':DOPE,'recorded_at':1791742622,
    'confirmed_logs':'Aggressive account closed DOPE at 13:12 Eastern for +0.008513 SOL, then at 13:45 for -0.006432 SOL on October 11.',
    'screenshot_evidence':'Later position entered at 13:42, market cap $207.3K, exited at $191.3K. Sampled post-exit peak +205.7%, low -50.5% relative to exit spot price.',
    'user_report':'Earlier entry was approximately $114K; user considers the entry, profit capture and subsequent higher re-entry a useful review case.',
    'lesson':'Evaluate initial entry, exit and later re-entry separately. Assess profit giveback, partial exits and fresh support before re-entering higher. A later peak is not executable profit and a rebound does not prove holding was the correct decision beforehand.',
    'scope':'Retrospective case from user screenshots and runtime exits. Earlier entry cap is user reported. No rewritten historical entry evidence or automatic strategy promotion.'}
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
RISK_CASE={'mint':'Go1EM5gL1bSjfYZLi1idz2C5iAFx6b1RGe9uR3ipump','symbol':'GTA 6 Coin','entry_market_cap_usd':441500,'exit_market_cap_usd':90400,'realized_pnl_pct':-80.3,'exit_reason':'hard stop','user_report':'Sharp dip toward zero; possible bundling, unverified.','lesson':'A -20% trigger did not cap this observed paper loss. Consider price gaps, concentration, liquidity and monitoring delay; do not infer a verified bundle or learn that all dips recover.','scope':'Retrospective incident from dashboard and confirmed exit log; exact intraperiod price path and cause are unverified.'}
def trade_sequence(mint,now=None):
    import json
    now=time.time() if now is None else now
    result=[]
    for book in ('trades','shadow_trades'):
        with store.conn() as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(book,)).fetchone():continue
            rows=c.execute(f'SELECT * FROM {book} WHERE mint=? AND entry_time<=? ORDER BY entry_time DESC,id DESC LIMIT 20',(mint,now)).fetchall()
        roots=[r for r in rows if not json.loads(r['context_json'] or '{}').get('partial_exit')][:3]
        for r in roots:
            closed=r['status']=='closed' and r['exit_time']<=now
            result.append({'book':book,'trade_id':r['id'],'entry_time':r['entry_time'],'entry_market_cap_usd':r['entry_market_cap_usd'],'entry_cap_is_fdv':bool(r['entry_cap_is_fdv']),
                'status':'closed' if closed else 'open','exit_time':r['exit_time'] if closed else None,'exit_market_cap_usd':r['exit_market_cap_usd'] if closed else None,
                'final_fill_pnl_sol':r['pnl_sol'] if closed else None,'after_exit_review':review(book,r['id']) if closed else None})
    return result

def context(mint):
    ensure()
    with store.conn() as c:rows=c.execute('SELECT book,trade_id FROM exit_reviews WHERE mint=? ORDER BY exit_time DESC LIMIT 5',(mint,)).fetchall()
    return {'execution_risk_case':RISK_CASE,'reviewed_trade_case':DOPE_CASE,'same_contract_positions':trade_sequence(mint),'recent_exits':[review(r['book'],r['trade_id']) for r in rows],'user_feedback':FEEDBACK if mint==RUNNER else None,'scope':'Observed feedback for future reviews; each new trade ID is a separate entry. Final-fill PnL excludes earlier partial sells; completed-position metrics remain authoritative. Retrospective user labels are unverified. Models are not retrained.'}
