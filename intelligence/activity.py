"""Activity evidence and prospective cohorts; flags are not scam determinations."""
import json,time,math
from collections import defaultdict
from statistics import median
from database.store import store
_cache={}
SUPMKT='3Y9QZ7TR3WUD1ZDsrjWe2uNAdXESZEBo2XacPw7Vpump'
COLLAPSE_LESSON={
    'id':'supmkt-collapse-2026-10-11','mint':SUPMKT,'recorded_at':1791736674,
    'provenance':'user_reported_screenshot_unverified',
    'chart_observation':'User screenshot shows SUPMKT near $3,552 market cap after a plateau around $1.3M and a sharp collapse.',
    'user_claim':'Suspected artificial volume and engagement; user reports no dip-buying demand.',
    'lesson':'Early momentum profits do not establish durable demand. Assess liquidity, buy-flow persistence through pullbacks, concentration and coordinated activity together. A collapse can exceed a stop trigger.',
    'limitations':'A chart does not establish zero buyers or prove wash trading. No transaction-level confirmation or independent engagement verification. This later feedback must not relabel historical entry evidence. One example is not a validated strategy.'}

SCAM_REVIEW_LESSON={
    'id':'sajadflips-secretfrog-video-2026-10-11','source':'User-supplied recording of @SajadFlips X post about $SECRETFROG','provenance':'recorded speaker claims; exact token contract and underlying transactions not independently verified',
    'claims':'Speaker compares roughly 2% and 57% wallet clusters across tools; cites 7.6% first-second buying, about 55% suspicious holdings, around $37K hourly volume at about $1M cap, isolated pump candles and a displayed 4.25% trading tax.',
    'lesson':'A no_bundle launch finding is not a current distribution all-clear. Check fresh linked/flagged holdings, early purchase concentration, relative turnover, independently sourced ownership evidence and transaction fees. Provider disagreement requires investigation, not averaging cluster percentages. Isolated candles and a straight launch rise are hypotheses, not proof of bundling. High market cap and prior gains do not establish broad demand. Unknown fees must remain unknown; include verified costs before judging profit.',
    'limitations':'The bot does not read live bubble maps, 30-second candles or GMGN displayed taxes. These are recorded claims, not automatic scam labels. No exact mint is inferred from a ticker. Proxima tooling alone does not prove fraud. Different graphs can cover different holders/time windows; linked transfers can be legitimate.'}

def ensure():
    with store.conn() as c:
        c.execute('CREATE TABLE IF NOT EXISTS activity_labels(id INTEGER PRIMARY KEY,mint TEXT,recorded_at REAL,payload_json TEXT)')
        c.execute('CREATE INDEX IF NOT EXISTS activity_labels_mint ON activity_labels(mint,id)')
        c.execute('CREATE TABLE IF NOT EXISTS activity_feedback_seeds(id TEXT PRIMARY KEY)')
        inserted=c.execute('INSERT OR IGNORE INTO activity_feedback_seeds VALUES(?)',(COLLAPSE_LESSON['id'],)).rowcount
        if inserted:
            c.execute('INSERT INTO activity_labels(mint,recorded_at,payload_json) VALUES(?,?,?)',(SUPMKT,COLLAPSE_LESSON['recorded_at'],json.dumps({'volume':'suspected','engagement':'suspected','note':COLLAPSE_LESSON['chart_observation']+' '+COLLAPSE_LESSON['user_claim']+' Transaction-level confirmation unavailable.','source_url':''})))
            __import__('logging').getLogger('uvicorn.error').info('NEXUS activity feedback recorded: %s',COLLAPSE_LESSON['id'])

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
    relative_turnover=None
    try:
        cap=float(token.get('market_cap_usd'));hourly=float(token.get('volume_1h_usd'))
        if math.isfinite(cap) and cap>0 and math.isfinite(hourly) and hourly>=0:
            relative_turnover=hourly/cap
            if cap>=1000000 and relative_turnover<.05:
                indicators.append({'kind':'low_hourly_turnover_at_large_cap','source':'DEX aggregate snapshot','ratio':relative_turnover,'message':'Hourly turnover below 5% at $1M+ cap is a review hypothesis, not proof of manipulation. Token age, quiet market periods and FDV versus circulating cap can affect this ratio.'})
    except (TypeError,ValueError):pass
    reported=label['volume'];engagement=label['engagement']
    volume_class='user_'+reported if reported!='unknown' else 'coordination_indicator' if any(x['kind']=='coordination_indicator' for x in indicators) else 'market_anomaly' if indicators else 'unknown'
    engagement_class='user_'+engagement if engagement!='unknown' else 'unknown'
    return {'user_review':label,'indicators':indicators,'volume_class':volume_class,'engagement_class':engagement_class,'hourly_volume_to_market_cap':relative_turnover,'reviewed_examples':[dict(COLLAPSE_LESSON),dict(SCAM_REVIEW_LESSON)],
        'coverage':{'distinct_buyer_analysis':'not_connected','circular_trade_analysis':'not_connected','pump_comments':'not_connected','x_reply_bot_analysis':'not_connected','live_bubble_maps':'not_connected','30_second_candles':'not_connected','token_tax_verification':'not_connected'},
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
