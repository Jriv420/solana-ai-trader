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
        from intelligence.trade_evaluation import positions,metrics
        grouped=defaultdict(list)
        for position in positions(table):
            a=position.get('activity') or {}
            grouped[(a.get('volume_class','unknown'),a.get('engagement_class','unknown'))].append(position)
        for (volume,engagement),items in grouped.items():
            m=metrics(items)
            paper.append({'account':account,'volume':volume,'engagement':engagement,'closed_trades':m['completed_positions'],'open_trades':m['open_positions'],'net_pnl_sol':m['net_pnl_sol'],'win_rate_pct':m['win_rate_pct']})
    output={'horizon':horizon,'groups':result,'paper_results':paper,'paper_scope':'Latest 5000 fills grouped into positions by evidence at entry. Partial sells plus the final remainder count once. Completed-position results exclude open remainders and legacy fills. Later labels do not relabel old trades.','scope':'Forward sampled price outcomes, not trade PnL or causal proof. One earliest case per coin per group; labels never rewrite old cases. Coins may enter different groups over time. Missing outcomes stay missing.'}
    _cache[cache_key]=(time.time(),output)
    return output
