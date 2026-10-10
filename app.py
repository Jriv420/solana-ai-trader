import asyncio,time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from urllib.parse import urlsplit
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from config.settings import settings
from data.token_stream import scan_tokens, stream_new_tokens, FEED
from data.social_data import get_social_snapshot
from data.tracked_wallets import get_tracked_wallet_holders, valid_address, configured_wallets, _cache as wallet_balance_cache
from data.wallet_discovery import wallet_learning_loop, STATUS as WALLET_STATUS
from database.wallet_registry import wallet_registry
from intelligence.decision_engine import evaluate_fast
from intelligence.wallet_ai import score_wallet_context
from intelligence.social_ai import score_social_context
from intelligence.risk_ai import score_contextual_risk
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
    f=evaluate_token(t)
    if not f["pass"]:return {"token":t,"status":"rejected","filter":f}
    fast=await evaluate_fast(t);STATE["agents"][fast["provider"]]="active"
    w=score_wallet_context(t);s=score_social_context(await get_social_snapshot(t.get("symbol","")));r=score_contextual_risk(t)
    e=should_enter(t,float(fast["score"]),float(w["score"]),float(s["score"]),float(r["score"]))
    o={"token":t,"fast":fast,"wallet":w,"social":s,"risk":r,"entry":e,"route":choose_route(t),"status":"candidate" if e["enter"] else "watch"}
    if e["enter"] and settings.paper_mode:
        existing={p["mint"] for p in paper_trader.open_positions()}
        if t["mint"] not in existing:
            a=position_size_sol(e["combined_score"],paper_trader.balance_sol())
            h=hard_risk_check(a,len(existing),store.realized(),t)
            if h["pass"]:paper_trader.buy(t,a,o);o["paper_action"]=f"BUY {a} SOL"
    return o
async def loop():
    while True:
        try:
            ts=await scan_tokens()
            observations=[]
            for t in ts:
                if not t.get("error"):
                    observation=await analyze(t)
                    store.record_observation(observation)
                    observations.append(observation)
            STATE["opportunities"]=observations
            STATE.pop("error",None)
            by={t["mint"]:t for t in ts}
            for p in paper_trader.open_positions():
                if p["mint"] in by:
                    d=should_exit(p,by[p["mint"]])
                    if d["exit"]:paper_trader.sell(p,by[p["mint"]],d["reason"])
        except Exception as e:STATE["error"]=str(e)
        await asyncio.sleep(settings.scan_interval_seconds)
@asynccontextmanager
async def life(app):
    tasks=[asyncio.create_task(loop()),asyncio.create_task(stream_new_tokens()),asyncio.create_task(wallet_learning_loop())]
    try:
        yield
    finally:
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
app=FastAPI(lifespan=life)
D=Path(__file__).resolve().parent/"dashboard"
app.mount("/static",StaticFiles(directory=D),name="static")
@app.get("/")
async def home():return FileResponse(D/"index.html")
@app.get("/api/status")
async def status():return {"paper_mode":settings.paper_mode,"balance_sol":paper_trader.balance_sol(),"open_positions":paper_trader.open_positions(),"agents":STATE["agents"],"error":STATE.get("error"),"new_pairs_feed":dict(FEED)}
@app.get("/api/opportunities")
async def opps():return STATE["opportunities"]
@app.get("/api/trades")
async def trades():return store.all()
@app.get("/api/new-pairs")
async def new_pairs():return {"feed":dict(FEED),"items":store.new_pairs()}
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
import os
import base64
import secrets
from fastapi import Request
from fastapi.responses import Response

@app.middleware("http")
async def nexus_security(request: Request, call_next):
    password = os.getenv("NEXUS_PASSWORD")

    if not password:
        return Response("NEXUS password not configured", status_code=503)

    authorization = request.headers.get("Authorization", "")
    valid = False

    if authorization.startswith("Basic "):
        try:
            encoded = authorization.split(" ", 1)[1]
            decoded = base64.b64decode(encoded).decode()
            username, supplied_password = decoded.split(":", 1)

            valid = (
                secrets.compare_digest(username, "nexus")
                and secrets.compare_digest(supplied_password, password)
            )
        except (ValueError, UnicodeDecodeError):
            pass

    if not valid:
        return Response(
            "Login required",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="NEXUS"'}
        )

    return await call_next(request)
