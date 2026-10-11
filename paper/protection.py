"""Independent paper protective checks; polling cannot guarantee a stop fill."""
import asyncio,logging,time
from data.market_data import get_token_snapshot,get_sol_price
from database.store import store
from paper.paper_trader import paper_trader
from paper.shadow import BOOK,TRADER
from intelligence.narrative import context
from strategy.exit import should_exit
INTERVAL=5
STATE={}
async def check_positions():
    positions=[(book,trader,p) for book,trader in ((store,paper_trader),(BOOK,TRADER)) for p in book.open()]
    if not positions:return
    sol=await get_sol_price();semaphore=asyncio.Semaphore(3)
    async def check(mint):
        async with semaphore:
            try:return await get_token_snapshot(mint)
            except Exception:return None
    mints=list(dict.fromkeys(p['mint'] for _,_,p in positions))
    results=await asyncio.gather(*(check(m) for m in mints));by=dict(zip(mints,results))
    valid=0;exits=0
    for book,trader,p in positions:
        t=by.get(p['mint'])
        if not t:continue
        t=dict(t,sol_price_usd=sol,research=context(p['mint'],t))
        from intelligence.policy_trials import safe_observe
        safe_observe(t)
        book.mark_peak(p['id'],t.get('price_usd') or 0)
        book.record_risk_sample(p['id'],t)
        d=should_exit(p,t,protective_only=True)
        if d['reason']=='no fresh valid price':continue
        valid+=1
        if d['exit'] and trader.sell(p,t,d['reason']):exits+=1
    STATE.update(checked_at=time.time(),open_checked=len(positions),valid_prices=valid,exits=exits,interval_seconds=INTERVAL)
    logging.getLogger('uvicorn.error').info('NEXUS protection summary %s',STATE)
async def protection_loop():
    while True:
        started=time.monotonic()
        try:await check_positions()
        except Exception as e:logging.getLogger('uvicorn.error').warning('NEXUS protection unavailable %s',type(e).__name__)
        await asyncio.sleep(max(.1,INTERVAL-(time.monotonic()-started)))
