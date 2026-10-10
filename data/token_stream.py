import math,time
from config.settings import settings
from data.market_data import get_token_snapshot
DEMO=[("MOONPUP","Moon Pup"),("FLYBRAIN","Fly Brain"),("ZEBRA","Zebra")]
def _demo(i):
    s,n=DEMO[i]; t=time.time(); w=math.sin(t/30+i); b=[.000182,.000061,.000033][i]
    return {"mint":"DEMO_"+s,"symbol":s,"name":n,"price_usd":b*(1+w*.05),
            "market_cap_usd":[182000,420000,310000][i]*(1+w*.04),
            "liquidity_usd":[64000,110000,88000][i],
            "volume_5m_usd":[412000,1200000,240000][i]*(1+max(w,0)),
            "price_change_5m_pct":[11.8,6.2,4.8][i]+w*2,
            "buys_5m":[124,231,92][i],"sells_5m":[52,121,71][i],
            "age_minutes":[2,8,14][i],"dex_id":"pumpfun-demo","source":"demo","timestamp":t}
async def scan_tokens():
    if not settings.watchlist_mints:return [_demo(i) for i in range(3)]
    out=[]
    for m in settings.watchlist_mints:
        try:
            x=await get_token_snapshot(m)
            if x:out.append(x)
        except Exception as e:
            out.append({"mint":m,"symbol":m[:6],"name":"Unavailable","error":str(e),"source":"error"})
    return out
