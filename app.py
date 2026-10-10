import asyncio,time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from config.settings import settings
from data.token_stream import scan_tokens
from data.social_data import get_social_snapshot
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
            ts=await scan_tokens();STATE["opportunities"]=[await analyze(t) for t in ts if not t.get("error")]
            by={t["mint"]:t for t in ts}
            for p in paper_trader.open_positions():
                if p["mint"] in by:
                    d=should_exit(p,by[p["mint"]])
                    if d["exit"]:paper_trader.sell(p,by[p["mint"]],d["reason"])
        except Exception as e:STATE["error"]=str(e)
        await asyncio.sleep(settings.scan_interval_seconds)
@asynccontextmanager
async def life(app):
    task=asyncio.create_task(loop());yield;task.cancel()
app=FastAPI(lifespan=life)
D=Path(__file__).resolve().parent/"dashboard"
app.mount("/static",StaticFiles(directory=D),name="static")
@app.get("/")
async def home():return FileResponse(D/"index.html")
@app.get("/api/status")
async def status():return {"paper_mode":settings.paper_mode,"balance_sol":paper_trader.balance_sol(),"open_positions":paper_trader.open_positions(),"agents":STATE["agents"],"error":STATE.get("error")}
@app.get("/api/opportunities")
async def opps():return STATE["opportunities"]
@app.get("/api/trades")
async def trades():return store.all()
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
