"""Activity evidence and prospective cohorts; flags are not scam determinations."""
import json,time,math
from collections import defaultdict
from statistics import median
from database.store import store
_cache={}

def ensure():
    with store.conn() as c:
        c.execute('CREATE TABLE IF NOT EXISTS activity_labels(id INTEGER PRIMARY KEY,mint TEXT,recorded_at REAL,payload_json TEXT)')
        c.execute('CREATE INDEX IF NOT EXISTS activity_labels_mint ON activity_labels(mint,id)')

def save(mint,payload):
    ensure()
    with store.conn() as c:
        c.execute('INSERT INTO activity_labels(mint,recorded_at,payload_json) VALUES(?,?,?)',(mint,time.time(),json.dumps(payload)))
        c.execute('DELETE FROM activity_labels WHERE id NOT IN (SELECT id FROM activity_labels ORDER BY id DESC LIMIT 5000)')
    _cache.clear()

def latest(mint):
    ensure()
    with store.conn() as c:r=c.execute('SELECT * FROM activity_labels WHERE mint=? ORDER BY id DESC LIMIT 1',(mint,)).fetchone()
    return dict(json.loads(r['payload_json']),recorded_at=r['recorded_at'],provenance='user_reported_unverified') if r else {'volume':'unknown','engagement':'unknown','provenance':'not_reviewed'}

def context(mint,token,security,bundle):
    label=latest(mint);indicators=[]
    if bundle.get('same_slot_buyer_groups') or bundle.get('provider_flags'):
        indicators.append({'kind':'coordination_indicator','source':'partial wallet history / RugCheck','message':'Linked or coordinated activity indicator; not proof of fake volume.'})
    try:
        volume=float(token.get('volume_5m_usd') or 0);liq=float(token.get('liquidity_usd') or 0)
        buys=int(token.get('buys_5m') or 0);sells=int(token.get('sells_5m') or 0);total=buys+sells
        if all(math.isfinite(x) for x in (volume,liq)) and liq>0 and volume/liq>=5 and total>=100 and abs(buys-sells)/total<=.1:
            indicators.append({'kind':'high_turnover_balanced_flow','source':'DEX aggregate snapshot','message':'High turnover with balanced buy/sell counts; genuine two-way trading can also cause this. Distinct buyers and circular trades are not established.'})
    except (ValueError,TypeError):pass
    reported=label['volume'];engagement=label['engagement']
    volume_class='user_'+reported if reported!='unknown' else 'coordination_indicator' if any(x['kind']=='coordination_indicator' for x in indicators) else 'market_anomaly' if indicators else 'unknown'
    engagement_class='user_'+engagement if engagement!='unknown' else 'unknown'
    return {'user_review':label,'indicators':indicators,'volume_class':volume_class,'engagement_class':engagement_class,
        'coverage':{'distinct_buyer_analysis':'not_connected','circular_trade_analysis':'not_connected','pump_comments':'not_connected','x_reply_bot_analysis':'not_connected'},
        'scope':'User labels are unverified. Indicators are not scam proof. Missing comments/search results are not evidence of fake engagement. Activity flags do not automatically block the aggressive paper account.'}

def comparison(horizon='1h'):
    import database.store as db
    cache_key=(str(db.DB),horizon)
    cached=_cache.get(cache_key)
    if cached and time.time()-cached[0]<60:return cached[1]
    from database.research import research
    research.ensure()
    with store.conn() as c:
        rows=c.execute('SELECT c.mint,c.started_at,c.features_json,o.return_pct,o.peak_pct,o.drawdown_pct FROM research_cases c JOIN research_outcomes o ON c.id=o.case_id WHERE o.horizon=? ORDER BY c.started_at',(horizon,)).fetchall()
    groups=defaultdict(dict)
    for r in rows:
        f=json.loads(r['features_json']);key=(f.get('activity_volume','unknown'),f.get('activity_engagement','unknown'))
        groups[key].setdefault(r['mint'],r)
    result=[]
    for (volume,engagement),coins in groups.items():
        values=list(coins.values());n=len(values)
        result.append({'volume':volume,'engagement':engagement,'distinct_coins':n,'median_return_pct':round(median(x['return_pct'] for x in values),2),'gain_50_pct':round(100*sum(x['peak_pct']>=50 for x in values)/n,1),'sharp_dip_pct':round(100*sum(x['drawdown_pct']<=-30 for x in values)/n,1)})
    paper=[]
    for table,account in (('trades','Original AI strategy'),('shadow_trades','Aggressive momentum')):
        with store.conn() as c:
            exists=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
            trades=c.execute(f"SELECT status,pnl_sol,COALESCE(json_extract(context_json,'$.entry_evidence.research.activity.volume_class'),json_extract(context_json,'$.token.research.activity.volume_class'),'unknown') volume_class,COALESCE(json_extract(context_json,'$.entry_evidence.research.activity.engagement_class'),json_extract(context_json,'$.token.research.activity.engagement_class'),'unknown') engagement_class FROM {table} ORDER BY entry_time DESC LIMIT 5000").fetchall() if exists else []
        grouped=defaultdict(list)
        for trade in trades:
            grouped[(trade['volume_class'],trade['engagement_class'])].append(trade)
        for (volume,engagement),items in grouped.items():
            closed=[x for x in items if x['status']=='closed']
            paper.append({'account':account,'volume':volume,'engagement':engagement,'closed_trades':len(closed),'open_trades':sum(x['status']=='open' for x in items),'net_pnl_sol':sum(x['pnl_sol'] or 0 for x in closed),'win_rate_pct':round(100*sum((x['pnl_sol'] or 0)>0 for x in closed)/len(closed),1) if closed else None})
    output={'horizon':horizon,'groups':result,'paper_results':paper,'paper_scope':'Latest 5000 trades per account, grouped by evidence at entry; later labels do not relabel old trades. Realized paper PnL excludes open positions. Legacy fills may lack cost estimates.','scope':'Forward sampled price outcomes, not trade PnL or causal proof. One earliest case per coin per group; labels never rewrite old cases. Coins may enter different groups over time. Missing outcomes stay missing.'}
    _cache[cache_key]=(time.time(),output)
    return output
