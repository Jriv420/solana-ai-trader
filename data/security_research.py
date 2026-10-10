"""Bounded RugCheck research; outages never become a clean bill of health."""
import asyncio
import time
import httpx
from database.research import research,finite
from database.store import store
from data.tracked_wallets import valid_address
STATUS={'rugcheck':'starting'}


def normalize_report(data,mint):
    if not isinstance(data,dict) or data.get('mint')!=mint or not isinstance(data.get('risks'),list):raise ValueError('Incomplete RugCheck report')
    risks=[{k:r.get(k) for k in ('name','description','level','score','value')} for r in data['risks'] if isinstance(r,dict)]
    token=data.get('token') or {}
    if not isinstance(token,dict) or not {'mintAuthority','freezeAuthority'}<=token.keys():raise ValueError('Authority data unavailable')
    danger=bool(data.get('rugged') or token.get('mintAuthority') or token.get('freezeAuthority') or any(r.get('level')=='danger' for r in risks))
    supply=finite(token.get('supply'));decimals=token.get('decimals')
    return {'status':'ok','source':'RugCheck','risks':risks,'danger':danger,'rugged':bool(data.get('rugged')),'mint_authority':token.get('mintAuthority'),'freeze_authority':token.get('freezeAuthority'),'supply_raw':supply,'decimals':decimals,'score':data.get('score_normalised'),'graph_insiders_detected':data.get('graphInsidersDetected'),'message':'Provider risk report, not a guarantee. Cached provider data may lag the chain.'}

async def check_token(mint):
    if not valid_address(mint):return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r=await client.get('https://api.rugcheck.xyz/v1/tokens/'+mint+'/report');r.raise_for_status()
            result=normalize_report(r.json(),mint)
        research.check(mint,result);STATUS['rugcheck']='active'
    except Exception:
        research.check(mint,{'status':'unavailable','risks':[],'message':'RugCheck unavailable; security is not cleared.'});STATUS['rugcheck']='unavailable'

async def security_loop():
    while True:
        try:
            items=store.watch_history(limit=100)
            eligible=[x['token'] for x in items if time.time()-x.get('last_seen',0)<600 and valid_address(x['token'].get('mint',''))]
            # At most one report every ten seconds, cache success for five minutes.
            eligible.sort(key=lambda t:research.security(t['mint']).get('checked_at',0))
            if eligible:
                t=eligible[0];cached=research.security(t['mint']);ttl=300 if cached['status']=='ok' else 60
                if time.time()-cached.get('checked_at',0)>ttl:await check_token(t['mint'])
        except Exception:STATUS['rugcheck']='unavailable'
        await asyncio.sleep(10)
