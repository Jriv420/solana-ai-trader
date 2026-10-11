"""Bounded DEX Screener meta feed; themes are not endorsements or organic demand."""
import time,re,httpx,math,logging
from database.store import valid_cap
STATE={'checked_at':0,'status':'not_checked','themes':[]}
async def refresh():
    now=time.time()
    if now-STATE['checked_at']<300:return
    STATE['checked_at']=now
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response=await client.get('https://api.dexscreener.com/metas/trending/v1');response.raise_for_status();items=response.json()
            if not isinstance(items,list):raise ValueError('Invalid meta feed')
            themes=[]
            # Three detailed themes per five minutes; no paid search/model calls.
            for rank,item in enumerate(items[:3],1):
                slug=item.get('slug') if isinstance(item,dict) else None
                if not isinstance(slug,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',slug):continue
                detail=await client.get('https://api.dexscreener.com/metas/meta/v1/'+slug);detail.raise_for_status();meta=detail.json()
                if not isinstance(meta,dict):continue
                pairs=[p for p in (meta.get('pairs') or [])[:1000] if isinstance(p,dict) and p.get('chainId')=='solana']
                members={p.get('baseToken',{}).get('address') for p in pairs if p.get('baseToken',{}).get('address')}
                leaders=[]
                for p in pairs:
                    cap=valid_cap(p.get('marketCap'));changes=p.get('priceChange') or {}
                    positive=any(isinstance(changes.get(h),(int,float)) and math.isfinite(changes[h]) and changes[h]>0 for h in ('h1','h24'))
                    if cap and cap>=1000000 and positive:
                        leaders.append({'mint':p.get('baseToken',{}).get('address'),'symbol':p.get('baseToken',{}).get('symbol'),'market_cap_usd':cap,'change_1h_pct':changes.get('h1'),'change_24h_pct':changes.get('h24')})
                themes.append({'slug':slug,'name':str(meta.get('name') or slug)[:100],'meta_feed_rank':rank,'members':sorted(members),'leaders':sorted(leaders,key=lambda x:x['market_cap_usd'],reverse=True)[:3]})
        STATE.update(status='ok',themes=themes)
    except (httpx.HTTPError,ValueError,TypeError,KeyError,AttributeError):STATE.update(status='unavailable',themes=[])
    logging.getLogger('uvicorn.error').info('NEXUS narrative meta feed status=%s themes=%s',STATE['status'],len(STATE['themes']))
def mints():
    if STATE['status']!='ok' or time.time()-STATE['checked_at']>600:return []
    # Include leaders so their prices and outcomes enter the ordinary scan.
    return list(dict.fromkeys(x['mint'] for t in STATE['themes'] for x in t['leaders'] if x['mint']))[:9]
def context(token):
    fresh=STATE['status']=='ok' and time.time()-STATE['checked_at']<=600
    matches=[]
    if fresh:
        for theme in STATE['themes']:
            if token.get('mint') in theme['members']:
                matches.append({k:v for k,v in theme.items() if k!='members'})
    cap=valid_cap(token.get('market_cap_usd'));age=token.get('age_minutes')
    candidate=bool(cap and not token.get('market_cap_is_fdv') and 20000<=cap<=100000 and isinstance(age,(int,float)) and 0<=age<=60 and any(any(x['mint']!=token.get('mint') for x in t['leaders']) for t in matches))
    return {'status':'provider_tagged' if matches else 'unknown','themes':matches,'small_cap_rotation_candidate':candidate,'checked_at':STATE['checked_at'],'feed_status':STATE['status'],'scope':'First three provider trending metas, not a top-ten token ranking or the whole market. Exact contract membership only; shared names are insufficient. Theme association and leader gains do not prove endorsement, organic engagement or future gains.'}
def summary():
    return {'status':STATE['status'],'checked_at':STATE['checked_at'],'themes':[{'name':t['name'],'slug':t['slug'],'leaders':t['leaders']} for t in STATE['themes']], 'scope':'First three trending metas; updated every five minutes. Not a top-ten token ranking.'}
