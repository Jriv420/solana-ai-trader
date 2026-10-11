"""Bounded cached web evidence. Search text is not an authenticated endorsement."""
import asyncio,json,logging,time
from datetime import datetime,timezone
from urllib.parse import urlsplit
import httpx
from config.settings import settings
from database.store import store
from data.tracked_wallets import valid_address
STATUS={'status':'standby','checked_at':None}
_LAST=0
_LOCK=asyncio.Lock()

def ensure():
    with store.conn() as c:c.execute('CREATE TABLE IF NOT EXISTS web_research(mint TEXT PRIMARY KEY,checked_at REAL,payload TEXT)')

def safe_url(value):
    try:
        u=urlsplit(value)
        return value[:1000] if u.scheme=='https' and u.hostname and not u.username and not u.password else ''
    except (TypeError,ValueError):return ''

def cached(mint):
    ensure()
    with store.conn() as c:r=c.execute('SELECT payload FROM web_research WHERE mint=?',(mint,)).fetchone()
    return json.loads(r['payload']) if r else {'status':'not_researched','sources':[]}

def usage():
    day=datetime.now(timezone.utc).date().isoformat()
    # Existing counter table is initialized without reserving or consuming a credit.
    daily=store.ai_request_count('tavily',day)
    with store.conn() as c:r=c.execute('SELECT COALESCE(SUM(attempts),0) n FROM ai_requests WHERE provider="tavily" AND day LIKE ?',(day[:7]+'%',)).fetchone()
    return dict(STATUS,configured=bool(settings.tavily_api_key),requests_today=daily,requests_month=r['n'],daily_limit=25,monthly_limit=750)

def save(mint,payload):
    ensure()
    with store.conn() as c:
        c.execute('INSERT OR REPLACE INTO web_research VALUES(?,?,?)',(mint,payload['checked_at'],json.dumps(payload)))
        c.execute('DELETE FROM web_research WHERE mint NOT IN (SELECT mint FROM web_research ORDER BY checked_at DESC LIMIT 1000)')

async def search(mint):
    global _LAST
    if not valid_address(mint):return {'status':'invalid_contract','sources':[]}
    previous=cached(mint);now=time.time()
    ttl=1800 if previous['status']=='no_exact_contract_sources' else 21600
    if now-previous.get('checked_at',0)<ttl:return previous
    if not settings.tavily_api_key:return {'status':'not_configured','sources':[]}
    async with _LOCK:
        if time.time()<STATUS.get('blocked_until',0):return dict(previous,request_status=STATUS['status'])
        if time.time()-_LAST<60:return dict(previous,request_status='rate_limited')
        limits=usage();day=datetime.now(timezone.utc).date().isoformat()
        if limits['requests_month']>=750 or not store.reserve_ai_request('tavily',day,25):
            STATUS['status']='budget_paused';return dict(previous,request_status='budget_paused')
        _LAST=time.time();payload={'checked_at':_LAST,'query':mint,'sources':[],'status':'unavailable'}
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response=await client.post('https://api.tavily.com/search',headers={'Authorization':'Bearer '+settings.tavily_api_key},json={'query':'"'+mint+'"','search_depth':'basic','max_results':4,'include_answer':False,'include_raw_content':False,'include_images':False,'auto_parameters':False})
            if response.status_code in (401,429,432,433):
                pause=86400 if response.status_code==401 else 3600
                if response.status_code in (432,433):
                    dt=datetime.now(timezone.utc);next_month=dt.replace(year=dt.year+(dt.month==12),month=dt.month%12+1,day=1,hour=0,minute=0,second=0,microsecond=0)
                    pause=max(3600,next_month.timestamp()-time.time())
                STATUS.update(status='provider_quota_or_auth_paused',blocked_until=time.time()+pause)
                payload['status']='provider_quota_or_auth_paused'
            response.raise_for_status();result=response.json()
            sources=[]
            for r in result.get('results',[])[:4]:
                url=safe_url(r.get('url'));title=str(r.get('title') or '')[:160];content=str(r.get('content') or '')[:700]
                # Exact address linkage prevents a same-name token's lore being borrowed.
                if url and mint in url+' '+title+' '+content:
                    sources.append({'url':url,'title':title,'snippet':content,'contract_linked':True,'endorsement_verified':False})
            payload.update(sources=sources,status='sources_found' if sources else 'no_exact_contract_sources')
        except Exception as exc:
            # Never log provider bodies, request headers, or secrets.
            logging.getLogger('uvicorn.error').info('NEXUS web search unavailable: %s',type(exc).__name__)
        save(mint,payload);STATUS.update(status=payload['status'],checked_at=payload['checked_at'])
        logging.getLogger('uvicorn.error').info('NEXUS web research %s; %s contract-linked sources',payload['status'],len(payload['sources']))
        return payload

async def research_loop():
    while True:
        try:
            if settings.tavily_api_key:
                candidates=[x['token'] for x in store.watch_history(limit=100) if time.time()-x.get('last_seen',0)<600 and valid_address(x['token'].get('mint','')) and float(x['token'].get('liquidity_usd') or 0)>=5000 and float(x['token'].get('volume_5m_usd') or 0)>=1000]
                candidates.sort(key=lambda t:float(t.get('volume_5m_usd') or 0),reverse=True)
                for t in candidates:
                    old=cached(t['mint']);ttl=1800 if old['status']=='no_exact_contract_sources' else 21600
                    if time.time()-old.get('checked_at',0)>=ttl:
                        await search(t['mint']);break
        except Exception as exc:logging.getLogger('uvicorn.error').info('NEXUS web worker retry: %s',type(exc).__name__)
        await asyncio.sleep(60)
