import asyncio,time,logging,traceback
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from urllib.parse import urlsplit
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from config.settings import settings,trading_settings,risk_trial_status
from data.token_stream import scan_tokens, stream_new_tokens, FEED
from data.social_data import get_social_snapshot, social_loop, STATUS as SOCIAL_STATUS
from data.market_data import get_sol_price
from data.wallet_signals import wallet_signals_loop
from database.research import research
from database.missed import missed
from data.web_research import research_loop,usage as web_usage,search as web_search
from paper.shadow import step as shadow_step,summary as shadow_summary
from strategy.paper_exception import eligible as exception_eligible, decide as exception_decide
from intelligence.narrative import context as narrative_context
from data.security_research import security_loop, STATUS as SECURITY_STATUS
from typing import Literal
from data.tracked_wallets import get_tracked_wallet_holders, valid_address, configured_wallets, _cache as wallet_balance_cache
from data.wallet_discovery import wallet_learning_loop, STATUS as WALLET_STATUS
from database.wallet_registry import wallet_registry
from intelligence.decision_engine import evaluate_fast, CONNECTIONS, provider_result, _fallback
from intelligence.wallet_ai import score_wallet_context
from intelligence.social_ai import score_social_context
from intelligence.risk_ai import score_contextual_risk
from intelligence.token_identity import annotate as annotate_identity
from strategy.token_filter import evaluate_token
from strategy.entry import should_enter
from strategy.exit import should_exit
from strategy.sizing import position_size_sol
from strategy.risk import hard_risk_check
from paper.paper_trader import paper_trader
from database.store import store
from execution.router import choose_route

STATE={"opportunities":[],"agents":{"jev":"standby","laya":"standby","darwin":"standby","wallet_ai":"active","social_ai":"active","risk_ai":"active"}}
async def analyze(t):
    rules=trading_settings()
    social_evidence=await get_social_snapshot(t['mint'])
    t=dict(t,social_context=social_evidence)
    t=dict(t,research=narrative_context(t["mint"],t))
    research.snapshot(t,t["research"]["features"])
    w=score_wallet_context(t)
    t.update(wallet_context=w,social_context=social_evidence)
    f=evaluate_token(t)
    t['setup_type']=f['mode']
    t['paper_risk_trial']=risk_trial_status()
    t['missed_opportunity_learning']=STATE.get('missed_learning',{})
    discretionary=exception_eligible(t,f)
    if not f["pass"] and not discretionary:
        missed.observe(t,f['reasons'])
        return {"token":t,"status":"rejected","filter":f}
    # Bound exploratory reviews to one per minute; normal qualified reviews keep their existing limits.
    explore=discretionary and time.time()-STATE.get('last_exception_review',0)>=60
    if explore:STATE['last_exception_review']=time.time()
    fast=await evaluate_fast(t) if w['score']>=rules.min_wallet_score or explore else dict(_fallback(t),reason='Awaiting qualified wallet evidence before paid AI escalation')
    STATE['agents'][fast['provider']]='active'
    STATE['agents']['wallet_ai']=w['status']
    STATE['agents']['social_ai']=social_evidence.get('status','unknown')
    s=score_social_context(social_evidence);r=score_contextual_risk(t)
    e=should_enter(t,float(fast["score"]),float(w["score"]),float(s["score"]),float(r["score"]))
    waived=exception_decide(t,f,e,fast,r['score']) if not f['pass'] or not e['enter'] else {'allowed':False}
    missed.observe(t,f['reasons']+e['reasons'])
    if waived['allowed']:e=dict(e,enter=True,paper_exception=waived)
    elif not f['pass']:e=dict(e,enter=False,reasons=f['reasons']+e['reasons'])
    o={"filter":f,"token":t,"fast":fast,"wallet":w,"social":s,"risk":r,"entry":e,"route":choose_route(t),"status":"candidate" if e["enter"] else "watch" if f["pass"] else "rejected"}
    if e["enter"] and settings.paper_mode:
        existing={p["mint"] for p in paper_trader.open_positions()}
        if t["mint"] not in existing:
            a=position_size_sol(e["combined_score"],paper_trader.balance_sol())
            h=hard_risk_check(a,len(existing),store.daily_realized(),t)
            if h["pass"]:
                bought=paper_trader.buy(t,a,o)
                if bought:o["paper_action"]=f"BUY {a} SOL"
                else:o['paper_blocked']='Fresh SOL price or available balance missing'
            else:o['paper_blocked']='; '.join(h['reasons'])
    return o
async def loop():
    while True:
        try:
            STATE['scan_started_at']=time.time()
            ts=annotate_identity(await scan_tokens(),[x['token'] for x in store.watch_history(limit=2000)])
            sol_price=await get_sol_price()
            for token in ts:token["sol_price_usd"]=sol_price
            by={t['mint']:t for t in ts}
            # Process exits before entries so risk limits use the latest realized balance.
            for position in paper_trader.open_positions():
                token=by.get(position['mint'])
                if token:
                    store.mark_peak(position['id'],token.get('price_usd') or 0)
                    decision=should_exit(position,token)
                    if decision['exit']:paper_trader.sell(position,token,decision['reason'])
            STATE["missed_learning"]=missed.summary()
            observations=[]
            semaphore=asyncio.Semaphore(4)
            async def evaluate(t):
                async with semaphore:return await analyze(t)
            results=await asyncio.gather(*(evaluate(t) for t in ts if not t.get('error')),return_exceptions=True)
            STATE['evaluation_failures']=sum(isinstance(x,Exception) for x in results)
            for observation in results:
                if isinstance(observation,Exception):continue
                store.record_observation(observation)
                observations.append(observation)
            STATE["shadow"]=shadow_step(observations)
            logging.getLogger('uvicorn.error').info('NEXUS shadow paper summary %s',STATE["shadow"])
            STATE["opportunities"]=observations
            reasons=Counter(reason for o in observations for reason in ((o.get('filter') or {}).get('reasons',[])+(o.get('entry') or {}).get('reasons',[])))
            diagnostic={'finished_at':time.time(),'checked':len(ts),'evaluated':len(observations),'evaluation_failures':STATE['evaluation_failures'],'failure_types':dict(Counter(type(x).__name__ for x in results if isinstance(x,Exception))),'statuses':dict(Counter(o.get('status','unknown') for o in observations)),'blockers':dict(reasons.most_common(8)),'paper_buys':sum('paper_action' in o for o in observations),'open_positions':len(paper_trader.open_positions()),'risk_trial_active':risk_trial_status()['active'],'model_assessments':dict(Counter(str(o['fast']['provider'])+': '+str(o['fast']['score']) for o in observations if o.get('fast')))}
            STATE['scan']=diagnostic
            logging.getLogger('uvicorn.error').info('NEXUS scan summary %s',diagnostic)
            STATE.pop("error",None)
        except Exception as exc:
            STATE["error"]='Scan unavailable; retrying. Check provider connections.'
            frame=traceback.extract_tb(exc.__traceback__)[-1]
            logging.getLogger('uvicorn.error').warning('NEXUS scan failed: %s at %s:%s (%s)',type(exc).__name__,Path(frame.filename).name,frame.lineno,frame.name)
        await asyncio.sleep(settings.scan_interval_seconds)
@asynccontextmanager
async def life(app):
    tasks=[asyncio.create_task(loop()),asyncio.create_task(stream_new_tokens()),asyncio.create_task(wallet_learning_loop()),asyncio.create_task(security_loop()),asyncio.create_task(social_loop()),asyncio.create_task(wallet_signals_loop()),asyncio.create_task(research_loop())]
    try:
        yield
    finally:
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
app=FastAPI(lifespan=life)
D=Path(__file__).resolve().parent/"dashboard"
app.mount("/static",StaticFiles(directory=D),name="static")
@app.get("/healthz")
def healthz():return {"ready":True}
@app.get("/")
async def home():return FileResponse(D/"index.html")
@app.get("/api/status")
async def status():return {"shadow":shadow_summary(),"risk_trial":risk_trial_status(),"paper_mode":settings.paper_mode,"balance_sol":paper_trader.balance_sol(),"open_positions":paper_trader.open_positions(),"agents":STATE["agents"],"error":STATE.get("error"),"new_pairs_feed":dict(FEED),"paper_metrics":store.paper_metrics(),"missed_learning":STATE.get("missed_learning",{}),"scan":STATE.get("scan"),"scan_started_at":STATE.get("scan_started_at")}
@app.get("/api/opportunities")
async def opps():return STATE["opportunities"]
@app.get("/api/trades")
async def trades():return store.all()
@app.get("/api/new-pairs")
async def new_pairs():
    items=store.new_pairs()
    checked={t['mint']:t for t in annotate_identity([x['token'] for x in items],[x['token'] for x in store.watch_history(limit=2000)])}
    return {"feed":dict(FEED),"items":[dict(x,token=checked[x['token']['mint']]) for x in items]}
@app.get("/api/watch-history")
async def watch_history(mint: str | None = None):return store.watch_history(mint=mint)
class WalletInput(BaseModel):
    address: str = Field(min_length=32,max_length=44)
    label: str = Field(default="",max_length=100)
def check_wallet_write(request):
    origin=request.headers.get('origin')
    if origin and urlsplit(origin).netloc!=request.headers.get('host'):
        raise HTTPException(status_code=403,detail="Use the dashboard to manage wallets")
@app.get("/api/wallets")
async def wallets():
    existing={w['address'] for w in wallet_registry.list()}
    try:
        for w in configured_wallets():
            if w['address'] not in existing and not w.get('tags'):wallet_registry.add(w['address'],w['label'],manual=True)
    except (ValueError,TypeError):pass
    return {"items":wallet_registry.list(),"status":dict(WALLET_STATUS),"whale_threshold_usd":settings.whale_position_usd,"whale_portfolio_usd":settings.whale_portfolio_usd,"min_matched_sells":settings.wallet_min_matched_sells}
@app.post("/api/wallets")
async def add_wallet(wallet: WalletInput, request: Request):
    check_wallet_write(request)
    if not valid_address(wallet.address):raise HTTPException(status_code=400,detail="Invalid public wallet address")
    try:
        existing={w['address'] for w in configured_wallets() if 'Manual' in w.get('tags',[]) or not w.get('tags')}
        if wallet.address not in existing and len(existing)>=50:raise HTTPException(status_code=409,detail="Manual tracking limit is 50 wallets")
    except ValueError:raise HTTPException(status_code=409,detail="Correct the existing wallet configuration first")
    wallet_registry.add(wallet.address,wallet.label.strip() or None,manual=True)
    wallet_balance_cache.clear()
    return {"saved":True,"address":wallet.address}
@app.delete("/api/wallets/{address}")
async def remove_wallet(address: str, request: Request):
    check_wallet_write(request)
    if not valid_address(address):raise HTTPException(status_code=400,detail="Invalid public wallet address")
    wallet_registry.disable(address);wallet_balance_cache.clear()
    return {"disabled":True}
@app.get("/api/tracked-wallets/{mint}")
async def tracked_wallets(mint: str):
    try:return await get_tracked_wallet_holders(mint)
    except ValueError:raise HTTPException(status_code=400,detail="Invalid mint address")
def connection_summary():
    import os
    from database.store import DB
    mount=os.getenv('RAILWAY_VOLUME_MOUNT_PATH')
    persistent=bool(mount and DB.resolve().is_relative_to(Path(mount).resolve()))
    models={}
    for provider in ('jev','laya','darwin','openai','gemini'):
        configured=bool(getattr(settings,provider+'_api_key') and getattr(settings,provider+'_endpoint'))
        models[provider]=dict(CONNECTIONS.get(provider,{}),configured=configured)
        models[provider].setdefault('status','configured_untested' if configured else 'not_configured')
        if provider=='openai':
            from intelligence.openai_review import usage
            models[provider].update(usage())
        if provider=='gemini':
            from intelligence.gemini_review import usage
            models[provider].update(usage())
    return {'web_research':web_usage(),'models':models,'rpc':{'configured':bool(settings.solana_rpc_url),'status':WALLET_STATUS['discovery']},'helius':{'configured':bool(settings.helius_api_key),'status':WALLET_STATUS['learning']},'x':dict(SOCIAL_STATUS,configured=bool(settings.x_bearer_token)),'rugcheck':dict(SECURITY_STATUS),'storage':{'railway_volume_detected':persistent,'db_path':str(DB),'message':'Volume detected; verify memory survives a restart.' if persistent else 'Persistent Railway volume not detected; learning may reset on deployment.'},'paper_mode':settings.paper_mode,'live_execution_enabled':False}
@app.get('/api/connections')
async def connections():return connection_summary()
@app.post('/api/connections/check')
async def test_connections(request: Request):
    check_wallet_write(request)
    now=time.time()
    if now-STATE.get('last_connection_test',0)<60:raise HTTPException(status_code=429,detail='Wait a minute before testing again')
    STATE['last_connection_test']=now
    for provider in ('jev','laya','darwin','openai','gemini'):
        await provider_result(provider,{'connection_test':True,'message':'Return a numeric score of 50. No trading decision.'})
    return connection_summary()

class NarrativeInput(BaseModel):
    wallet: str = Field(min_length=32,max_length=44)
    subject: str = Field(default="",max_length=100)
    identity: Literal["unknown","alleged","verified"] = "unknown"
    endorsement: Literal["unknown","speculative","confirmed","denied"] = "unknown"
    source_url: str = Field(default="",max_length=500)
    note: str = Field(default="",max_length=500)
@app.get("/api/research/{mint}")
async def coin_research(mint: str):
    if not valid_address(mint):raise HTTPException(status_code=400,detail="Invalid mint")
    return research.detail(mint)
@app.post("/api/research/{mint}/claims")
async def add_claim(mint: str, claim: NarrativeInput, request: Request):
    check_wallet_write(request)
    if not valid_address(mint) or not valid_address(claim.wallet):raise HTTPException(status_code=400,detail="Use valid public addresses")
    url=urlsplit(claim.source_url)
    if claim.source_url and (url.scheme!='https' or not url.netloc or url.username or url.password):raise HTTPException(status_code=400,detail="Use a public HTTPS source link")
    if (claim.identity=='verified' or claim.endorsement in {'confirmed','denied'}) and not claim.source_url:raise HTTPException(status_code=400,detail="A source link is required for reviewed verification or endorsement")
    manual=[w for w in wallet_registry.list() if w['manual'] and not w['disabled']]
    if not any(w['address']==claim.wallet for w in manual) and len(manual)>=50:raise HTTPException(status_code=409,detail="Manual tracking limit reached; stop tracking a wallet first")
    # Researching a claimed wallet does not verify who owns it.
    wallet_registry.add(claim.wallet,manual=True)
    return {"saved":True,"id":research.claim(mint,claim.model_dump()),"provenance":"user_reviewed"}

@app.get("/api/trending")
async def trending(window: str = "5m"):
    field={"5m":"volume_5m_usd","1h":"volume_1h_usd","24h":"volume_24h_usd"}.get(window,"volume_5m_usd")
    now=time.time()
    items=[x for x in store.watch_history(limit=2000) if x.get("observations",0)>0 and now-x['last_seen']<=600]
    items=[x for x in items if float(x['token'].get(field) or 0)>0 and float(x['token'].get('market_cap_usd') or 0)>0]
    def ranks(key):
        values=sorted(set(float(x['token'].get(key) or 0) for x in items))
        return {v: i/max(1,len(values)-1) for i,v in enumerate(values)}
    volume_ranks=ranks(field); cap_ranks=ranks('market_cap_usd')
    for x in items:
        token=x['token']
        x['trending_score']=round(100*(.7*volume_ranks[float(token.get(field) or 0)]+.3*cap_ranks[float(token.get('market_cap_usd') or 0)]),1)
        x['volume_mc_ratio']=float(token.get(field) or 0)/float(token['market_cap_usd'])
    items.sort(key=lambda x:(x['trending_score'],float(x['token'].get(field) or 0)),reverse=True)
    return {"items":items[:100],"window":window if window in {'5m','1h','24h'} else '5m',"scope":"Recently scanned tokens; not the entire Solana market", "ranking":"70% volume rank + 30% market cap rank"}
from dashboard_auth import install as install_auth
install_auth(app,D)

@app.post("/api/research/{mint}/search")
async def search_sources(mint: str,request: Request):
    check_wallet_write(request)
    if not valid_address(mint):raise HTTPException(status_code=400,detail="Invalid contract address")
    return await web_search(mint)
