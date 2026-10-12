"""Exact-contract pool candles for retrospective wallet review; no executable-profit claims."""
import asyncio,json,logging,math,os,time
from datetime import datetime,timezone
import httpx
from database.store import store
from data.tracked_wallets import valid_address
PUBLIC='https://api.geckoterminal.com/api/v2'
PRO='https://pro-api.coingecko.com/api/v3/onchain'
DAILY_LIMIT=15

def ensure():
    with store.conn() as c:
        c.execute('CREATE TABLE IF NOT EXISTS wallet_price_history(address TEXT,mint TEXT,start_time REAL,end_time REAL,checked_at REAL,payload_json TEXT,PRIMARY KEY(address,mint,start_time,end_time))')

def pool_for(data,mint,start):
    pools=[]
    for p in data.get('data') or []:
        a=p.get('attributes') or {};r=p.get('relationships') or {}
        base=((r.get('base_token') or {}).get('data') or {}).get('id','').removeprefix('solana_')
        quote=((r.get('quote_token') or {}).get('data') or {}).get('id','').removeprefix('solana_')
        if mint not in (base,quote) or not valid_address(a.get('address')):continue
        try:created=datetime.fromisoformat(a['pool_created_at'].replace('Z','+00:00')).timestamp()
        except (KeyError,ValueError,TypeError):continue
        if created>start:continue
        try:liquidity=float(a.get('reserve_in_usd') or 0)
        except (ValueError,TypeError):liquidity=0
        pools.append({'address':a['address'],'base':base,'quote':quote,'created_at':created,'current_liquidity_usd':liquidity if math.isfinite(liquidity) else 0})
    # Current liquidity is only a selection heuristic, not evidence of old liquidity.
    return max(pools,key=lambda p:p['current_liquidity_usd']) if pools else None

def normalize_candles(data,mint,pool):
    meta=data.get('meta') or {}
    if (meta.get('base') or {}).get('address')!=pool['base'] or (meta.get('quote') or {}).get('address')!=pool['quote']:
        raise ValueError('Candle token identity mismatch')
    if mint not in (pool['base'],pool['quote']):raise ValueError('Subject mismatch')
    rows=[];seen=set()
    for row in ((data.get('data') or {}).get('attributes') or {}).get('ohlcv_list') or []:
        if not isinstance(row,list) or len(row)!=6:raise ValueError('Invalid candle')
        if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in row):raise ValueError('Invalid candle numbers')
        ts,o,h,l,close,volume=row
        if ts<=0 or ts!=int(ts) or min(o,h,l,close)<=0 or volume<0 or h<max(o,l,close) or l>min(o,h,close):raise ValueError('Invalid OHLC')
        if ts in seen:continue
        seen.add(ts);rows.append(row)
    return sorted(rows,key=lambda x:x[0])

def comparison(candles,start,end,seconds):
    # Exclude boundary candles whose highs may predate entry or postdate exit.
    held=[r for r in candles if r[0]>=start and r[0]+seconds<=end]
    after=[r for r in candles if r[0]>=end and r[0]+seconds<=end+86400]
    result={'held_full_candles':len(held),'after_exit_full_candles':len(after),'interval_seconds':seconds,
            'scope':'USD candles from one selected pool. Intracandle execution, historical liquidity, gaps and other pools are unknown. Boundary bars excluded. Candle highs are not executable fills or net trade profit; historical market cap and SOL/USD conversion are not inferred.'}
    if held:
        peak=max(held,key=lambda r:r[2]);base=held[0][4]
        result.update(first_sampled_close_usd=base,last_sampled_close_usd=held[-1][4],sampled_high_usd=peak[2],sampled_low_usd=min(r[3] for r in held),high_candle_start=peak[0],high_vs_first_sampled_close_multiple=peak[2]/base,close_giveback_from_high_pct=100*(1-held[-1][4]/peak[2]),first_candle_at=held[0][0],last_candle_at=held[-1][0])
    if held and after:result['post_exit_high_vs_last_sampled_close_pct']=100*(max(r[2] for r in after)/held[-1][4]-1)
    return result

def save(address,mint,start,end,payload):
    ensure()
    with store.conn() as c:
        c.execute('INSERT OR REPLACE INTO wallet_price_history VALUES(?,?,?,?,?,?)',(address,mint,start,end,time.time(),json.dumps(payload)))
        c.execute('DELETE FROM wallet_price_history WHERE rowid NOT IN (SELECT rowid FROM wallet_price_history ORDER BY checked_at DESC LIMIT 500)')
def summary(address):
    ensure()
    with store.conn() as c:rows=c.execute('SELECT * FROM wallet_price_history WHERE address=? ORDER BY checked_at DESC LIMIT 12',(address,)).fetchall()
    return [{'mint':r['mint'],'start_time':r['start_time'],'end_time':r['end_time'],'checked_at':r['checked_at'],**json.loads(r['payload_json'])} for r in rows]

async def get(client,path,params=None):
    day=datetime.now(timezone.utc).date().isoformat()
    if not store.reserve_ai_request('wallet_historical_candles',day,DAILY_LIMIT):raise RuntimeError('daily_candle_budget_reached')
    key=os.getenv('COINGECKO_PRO_API_KEY','').strip()
    r=await client.get((PRO if key else PUBLIC)+path,params=params,headers={'x-cg-pro-api-key':key} if key else {})
    if r.status_code in (401,403):raise RuntimeError('historical_access_rejected')
    if r.status_code==429:raise RuntimeError('historical_provider_rate_limited')
    r.raise_for_status();return r.json()
async def fetch_case(address,mint,start,end,kind='matched_trade'):
    payload={'status':'pending','case_kind':kind,'source':'GeckoTerminal / CoinGecko pool OHLCV','currency':'USD'}
    if not valid_address(mint) or not 0<start<=end<=time.time():raise ValueError('Invalid history window')
    if start<time.time()-180*86400 and not os.getenv('COINGECKO_PRO_API_KEY'):
        payload.update(status='archive_access_required',message='Window exceeds free historical range; requires a compatible paid archive key or independently supplied candles. No purchase is made.');save(address,mint,start,end,payload);return payload
    duration=end-start;frame,aggregate,seconds=('minute',5,300) if duration<=2*86400 else ('hour',1,3600) if duration<=30*86400 else ('day',1,86400)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            pool=pool_for(await get(client,f'/networks/solana/tokens/{mint}/pools',{'page':1}),mint,start)
            if not pool:payload.update(status='no_matching_historical_pool',message='No exact-mint pool on the first provider page predates this window. Unlisted, migrated or inactive pools may be missing.');save(address,mint,start,end,payload);return payload
            data=await get(client,f"/networks/solana/pools/{pool['address']}/ohlcv/{frame}",{'aggregate':aggregate,'limit':1000,'before_timestamp':int(end+86400),'currency':'usd','token':mint,'include_empty_intervals':'false'})
        candles=normalize_candles(data,mint,pool)
        selected=[r for r in candles if start<=r[0]<end+86400]
        payload.update(status='candles_returned' if selected else 'no_candles_in_window',pool=pool,interval_seconds=seconds,candles=selected,comparison=comparison(selected,start,end,seconds),coverage='Observed bars only; skipped intervals and missing pools remain gaps. Historical peak across all markets is not established.')
    except Exception as exc:payload.update(status=str(exc) if isinstance(exc,RuntimeError) else 'history_unavailable_'+type(exc).__name__)
    save(address,mint,start,end,payload)
    logging.getLogger('uvicorn.error').info('NEXUS wallet candle study mint=%s status=%s candles=%s',mint,payload['status'],len(payload.get('candles',[])))
    return payload

async def step():
    from intelligence.user_wallet_study import address,evaluate,ensure as study_ensure
    study_ensure();ensure();wallet=address()
    if not valid_address(wallet):return
    with store.conn() as c:rows=c.execute('SELECT event_json FROM user_wallet_study_events WHERE address=? ORDER BY timestamp',(wallet,)).fetchall()
    events=[json.loads(r[0]) for r in rows];analysis=evaluate(events)
    cases=[(x['mint'],x['entry_time'],x['exit_time'],'matched_trade') for x in analysis['recent_completed']]
    for x in analysis['recent_matched_sales']:cases.append((x['mint'],x['timestamp']-x['holding_seconds'],x['timestamp'],'matched_partial_sale'))
    # Transfers can identify a token's observed date, but are never called buys/exits.
    grouped={}
    for e in events:
        for mint in ([e['mint']] if e.get('mint') else e.get('mints',[])):
            if mint=='So11111111111111111111111111111111111111112':continue
            lo,hi=grouped.get(mint,(e['timestamp'],e['timestamp']));grouped[mint]=(min(lo,e['timestamp']),max(hi,e['timestamp']))
    cases.extend((mint,lo,hi,'observed_token_activity_not_verified_trade') for mint,(lo,hi) in sorted(grouped.items(),key=lambda x:x[1][1],reverse=True) if hi>lo)
    for mint,start,end,kind in cases:
        with store.conn() as c:r=c.execute('SELECT checked_at,payload_json FROM wallet_price_history WHERE address=? AND mint=? AND start_time=? AND end_time=?',(wallet,mint,start,end)).fetchone()
        if r:
            previous=json.loads(r['payload_json'])
            if previous['status'] in ('candles_returned','archive_access_required','no_matching_historical_pool','no_candles_in_window') and not (previous['status']=='archive_access_required' and os.getenv('COINGECKO_PRO_API_KEY')):continue
            if time.time()-r['checked_at']<86400:continue
        await fetch_case(wallet,mint,start,end,kind);return
async def loop():
    while True:
        try:await step()
        except Exception as exc:logging.getLogger('uvicorn.error').warning('NEXUS wallet candle study unavailable %s',type(exc).__name__)
        await asyncio.sleep(300)
