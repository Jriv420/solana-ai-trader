"""Bounded, mint-specific X evidence. Mentions never establish endorsement."""
import asyncio,json,time
from datetime import datetime,timezone,timedelta
import httpx
from config.settings import settings
from database.store import store
from data.tracked_wallets import valid_address
STATUS={'x':'starting','last_check':None}

def ensure():
    with store.conn() as c:c.execute('CREATE TABLE IF NOT EXISTS social_snapshots(mint TEXT PRIMARY KEY,checked_at REAL,payload_json TEXT)')

def save(mint,payload):
    with store.conn() as c:
        c.execute('INSERT INTO social_snapshots VALUES(?,?,?) ON CONFLICT(mint) DO UPDATE SET checked_at=excluded.checked_at,payload_json=excluded.payload_json',(mint,time.time(),json.dumps(payload)))
        c.execute('DELETE FROM social_snapshots WHERE mint NOT IN (SELECT mint FROM social_snapshots ORDER BY checked_at DESC LIMIT 2000)')

async def get_social_snapshot(mint):
    with store.conn() as c:r=c.execute('SELECT * FROM social_snapshots WHERE mint=?',(mint,)).fetchone()
    if not r:return {'status':'not_configured' if not settings.x_bearer_token else 'pending','mentions_5m':None,'known_influencers':[],'source':'X mint search'}
    data=json.loads(r['payload_json']);data['checked_at']=r['checked_at']
    if time.time()-r['checked_at']>600:data['status']='stale'
    return data

def summarize(data,mint,now=None):
    now=time.time() if now is None else now
    if data.get('errors'):raise ValueError('Partial X response')
    if not isinstance(data.get('meta'),dict):raise ValueError('Malformed X response')
    rows=data.get('data') or []
    if not isinstance(rows,list):raise ValueError('Malformed X response')
    current=[];previous=[];posts=[]
    users={u['id']:u for u in (data.get('includes') or {}).get('users',[]) if 'id' in u}
    for p in rows:
        # Contract match avoids ticker impersonators and unrelated names.
        if mint not in p.get('text',''):continue
        try:created=datetime.fromisoformat(p['created_at'].replace('Z','+00:00')).timestamp()
        except (KeyError,ValueError):continue
        if not 0<=now-created<=600:continue
        (current if now-created<=300 else previous).append(p)
        user=users.get(p.get('author_id'),{})
        posts.append({'id':p.get('id'),'author_id':p.get('author_id'),'username':user.get('username'),'text':p.get('text','')[:600],'created_at':created,'url':'https://x.com/i/web/status/'+str(p.get('id'))})
    known=sorted({p['author_id'] for p in current if p.get('author_id') in settings.x_kol_ids})
    return {'status':'ok','mentions_5m':len(current),'previous_mentions_5m':len(previous),'unique_accounts_5m':len({p.get('author_id') for p in current}),'known_influencers':known,'mention_growth':len(current)/len(previous) if previous else None,'posts':posts[:20],'sample_truncated':bool((data.get('meta') or {}).get('next_token')),'source':'X API · exact mint · sampled last 10m','scope':'One page of up to 100 posts; not all mentions or verified endorsement.'}

async def poll(mint):
    if not valid_address(mint):return
    if not settings.x_bearer_token:STATUS['x']='not_configured';return
    try:
        start=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat(timespec='seconds').replace('+00:00','Z')
        async with httpx.AsyncClient(timeout=10) as client:
            response=await client.get('https://api.x.com/2/tweets/search/recent',params={'query':mint+' -is:retweet','start_time':start,'max_results':100,'tweet.fields':'created_at,author_id,public_metrics','expansions':'author_id','user.fields':'username'},headers={'Authorization':'Bearer '+settings.x_bearer_token})
            response.raise_for_status();payload=summarize(response.json(),mint)
        save(mint,payload);STATUS.update(x='active',last_check=time.time())
    except Exception:save(mint,{'status':'unavailable','source':'X API','known_influencers':[]});STATUS['x']='unavailable'

async def social_loop():
    while True:
        try:
            if settings.x_bearer_token:
                items=store.watch_history(limit=100)
                selected=[x['token']['mint'] for x in items if valid_address(x['token'].get('mint',''))]
                oldest=None;old_time=time.time()
                for mint in selected:
                    data=await get_social_snapshot(mint);stamp=data.get('checked_at',0)
                    if stamp<old_time:oldest=mint;old_time=stamp
                if oldest and time.time()-old_time>300:await poll(oldest)
            else:STATUS['x']='not_configured'
        except Exception:STATUS['x']='unavailable'
        await asyncio.sleep(60)
ensure()
