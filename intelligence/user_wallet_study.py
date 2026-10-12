"""Read-only, paginated personal-wallet study; never a copy-trading authority."""
import asyncio,json,logging,os,time
from collections import defaultdict
from decimal import Decimal
from datetime import datetime,timezone
from statistics import median
from collections import Counter
import httpx
from config.settings import settings
from database.store import store
from data.tracked_wallets import valid_address
from intelligence.wallet_learning import normalize_transaction
PAGE_LIMIT=10

def address():return os.getenv('STUDY_WALLET','').strip()
def ensure():
    with store.conn() as c:
        c.execute('CREATE TABLE IF NOT EXISTS user_wallet_studies(address TEXT PRIMARY KEY,state_json TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS user_wallet_study_events(address TEXT,signature TEXT,timestamp REAL,event_json TEXT,PRIMARY KEY(address,signature))')
def state():
    ensure();wallet=address()
    with store.conn() as c:r=c.execute('SELECT state_json FROM user_wallet_studies WHERE address=?',(wallet,)).fetchone()
    return json.loads(r[0]) if r else {'address':wallet,'status':'pending' if valid_address(wallet) else 'not_configured','pages':0,'transactions_seen':0,'cursor':None}
def save(s):
    with store.conn() as c:c.execute('INSERT OR REPLACE INTO user_wallet_studies VALUES(?,?)',(s['address'],json.dumps(s)))
def evaluate(events):
    books={};completed=[];matched=[];excluded=0
    for e in sorted(events,key=lambda x:(x['timestamp'],x.get('slot') or 0,x['signature'])):
        if e['kind']=='invalidate_all':books.clear();excluded+=1;continue
        if e['kind']=='invalidate':
            for mint in e.get('mints',[]):books.pop(mint,None)
            excluded+=1;continue
        mint=e['mint'];qty=Decimal(e['quantity']);sol=Decimal(e['sol'])
        if not qty.is_finite() or not sol.is_finite() or qty<=0 or sol<=0:excluded+=1;continue
        if e['kind']=='buy':
            b=books.setdefault(mint,{'qty':Decimal(0),'basis':Decimal(0),'spent':Decimal(0),'pnl':Decimal(0),'entry':e['timestamp'],'buys':0,'sells':0,'peak_own_fill':Decimal(0),'last_sell':None})
            b['qty']+=qty;b['basis']+=sol;b['spent']+=sol;b['buys']+=1;b['peak_own_fill']=max(b['peak_own_fill'],sol/qty);continue
        b=books.get(mint)
        if not b or qty>b['qty']:books.pop(mint,None);excluded+=1;continue
        basis=b['basis']*qty/b['qty'];profit=sol-basis;unit=sol/qty
        matched.append({'mint':mint,'timestamp':e['timestamp'],'net_pnl_sol':float(profit),'return_pct':float(100*profit/basis),'holding_seconds':e['timestamp']-b['entry']})
        b['qty']-=qty;b['basis']-=basis;b['pnl']+=profit;b['sells']+=1;b['last_sell']=unit;b['peak_own_fill']=max(b['peak_own_fill'],unit)
        if b['qty']==0:
            completed.append({'mint':mint,'entry_time':b['entry'],'exit_time':e['timestamp'],'net_pnl_sol':float(b['pnl']),'spent_sol':float(b['spent']),'return_pct':float(100*b['pnl']/b['spent']),'holding_seconds':e['timestamp']-b['entry'],'buys':b['buys'],'sells':b['sells'],'last_sale_below_highest_own_fill_pct':float(100*(1-b['last_sell']/b['peak_own_fill'])),'scope':'Highest own execution price, not historical market peak. Fee/route differences may affect comparisons.'})
            books.pop(mint)
    losses=[x for x in completed if x['net_pnl_sol']<0];wins=[x for x in completed if x['net_pnl_sol']>0]
    return {'matched_sale_net_pnl_sol':sum(x['net_pnl_sol'] for x in matched),'recent_matched_sales':matched[-12:][::-1],'completed_positions':len(completed),'matched_sales':len(matched),'unresolved_positions':len(books),'excluded_events':excluded,'net_realized_sol_completed':sum(x['net_pnl_sol'] for x in completed),'completed_win_rate_pct':100*len(wins)/len(completed) if completed else None,'median_losing_hold_seconds':median(x['holding_seconds'] for x in losses) if losses else None,'median_winning_hold_seconds':median(x['holding_seconds'] for x in wins) if wins else None,'repeated_buy_positions':sum(x['buys']>1 for x in completed),'recent_completed':completed[-12:][::-1]}
def summary():
    s=state()
    with store.conn() as c:rows=c.execute('SELECT event_json FROM user_wallet_study_events WHERE address=? ORDER BY timestamp',(s['address'],)).fetchall()
    from data.historical_prices import summary as price_summary
    return dict(s,price_history=[{k:v for k,v in x.items() if k!='candles'} for x in price_summary(s['address'])],analysis=evaluate([json.loads(r[0]) for r in rows]),owner_claim='User identifies this as their wallet; ownership not cryptographically verified.',
        scope='Observed, unambiguous SOL-quoted swaps only. Transfers, deposits, unknown routes and unparsed windows are excluded or invalidate cost basis. Partial historical coverage, not lifetime PnL. Two-year peak price/cap, original narrative and holder distribution are not verified. SOL returns are not historical USD returns. No automatic copying or model-weight training.')
async def step():
    s=state()
    if not valid_address(s['address']) or s.get('complete'):return
    if not settings.helius_api_key:s.update(status='helius_not_configured');save(s);return
    day=datetime.now(timezone.utc).date().isoformat()
    if not store.reserve_ai_request('wallet_study_history',day,PAGE_LIMIT):s.update(status='daily_history_budget_reached');save(s);return
    body={'address':s['address'],'limit':100,'sortOrder':'desc','commitment':'confirmed'}
    if s.get('cursor'):body['paginationToken']=s['cursor']
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r=await client.post('https://mainnet.helius-rpc.com/v1/parsed-events/transaction-history',params={'api-key':settings.helius_api_key},json=body)
        if r.status_code in (401,403):s.update(status='history_access_rejected',checked_at=time.time());save(s);return
        r.raise_for_status();data=r.json();items=data['data']
        if not isinstance(items,list):raise ValueError('Invalid history')
        stamps=[];events=[]
        for item in items:
            tx=item.get('parsed') or {};stamp=tx.get('blockTime')
            if stamp:stamps.append(stamp)
            event=normalize_transaction(item,s['address'])
            if event:events.append(event)
            elif item.get('signature') and stamp and (item.get('parserStatus')!='OK' or tx.get('transactionStatus') not in ('OK','FAILED')):
                events.append({'signature':item['signature'],'timestamp':stamp,'slot':tx.get('slot',0),'kind':'invalidate_all','mints':sorted({t.get('mint') for t in tx.get('tokenTransfers',[]) if valid_address(t.get('mint')) and s['address'] in (t.get('toUserAccount'),t.get('fromUserAccount'))})})
        with store.conn() as c:
            for e in events:c.execute('INSERT OR IGNORE INTO user_wallet_study_events VALUES(?,?,?,?)',(s['address'],e['signature'],e['timestamp'],json.dumps(e)))
        cursor=data.get('paginationToken');s.update(status='importing' if cursor else 'history_end_reached',cursor=cursor,complete=not bool(cursor),pages=s['pages']+1,transactions_seen=s['transactions_seen']+len(items),checked_at=time.time())
        if stamps:s.update(newest_time=max(s.get('newest_time') or 0,max(stamps)),oldest_time=min(s.get('oldest_time') or min(stamps),min(stamps)))
        s['last_page_event_kinds']=dict(Counter(e['kind'] for e in events));s['last_page_parser_statuses']=dict(Counter(str(x.get('parserStatus')) for x in items));s['last_page_transaction_statuses']=dict(Counter(str((x.get('parsed') or {}).get('transactionStatus')) for x in items));save(s);a=summary()['analysis'];logging.getLogger('uvicorn.error').info('NEXUS personal wallet study status=%s pages=%s transactions=%s oldest=%s matched_sales=%s completed_positions=%s event_kinds=%s',s['status'],s['pages'],s['transactions_seen'],s.get('oldest_time'),a['matched_sales'],a['completed_positions'],s['last_page_event_kinds'])
    except Exception as exc:s.update(status='history_unavailable_'+type(exc).__name__,checked_at=time.time());save(s)
async def loop():
    while True:
        try:
            await step()
            logging.getLogger('uvicorn.error').info('NEXUS personal wallet study status=%s',state()['status'])
        except Exception as exc:logging.getLogger('uvicorn.error').warning('NEXUS personal wallet study unavailable %s',type(exc).__name__)
        await asyncio.sleep(600)
