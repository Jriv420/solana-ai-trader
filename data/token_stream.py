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

# NEXUS automatic Solana token discovery - Phase 1
import asyncio
import httpx

DISCOVERY_URLS = [
    "https://api.dexscreener.com/token-profiles/latest/v1",
    "https://api.dexscreener.com/token-boosts/latest/v1",
    "https://api.dexscreener.com/token-boosts/top/v1",
    "https://api.dexscreener.com/community-takeovers/latest/v1",
]

_discovery_cache = []
_discovery_updated = 0


async def discover_tokens():
    global _discovery_cache, _discovery_updated

    now = time.time()
    if now - _discovery_updated < 60:
        return _discovery_cache

    found = []
    seen = set()

    async with httpx.AsyncClient(timeout=10.0) as client:
        for url in DISCOVERY_URLS:
            try:
                response = await client.get(url)
                response.raise_for_status()
                items = response.json()

                if not isinstance(items, list):
                    continue

                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if item.get("chainId") != "solana":
                        continue

                    mint = item.get("tokenAddress")
                    if not mint or mint in seen:
                        continue

                    seen.add(mint)
                    found.append(mint)

            except (httpx.HTTPError, ValueError):
                continue

    if found:
        _discovery_cache = found[:60]
        _discovery_updated = now

    return _discovery_cache


async def scan_tokens():
    mints = await discover_tokens()

    if not mints:
        return []

    # Rotate through discoveries to cover more tokens.
    batch_size = 15
    batch_index = int(time.time() // 20)
    start = (batch_index * batch_size) % len(mints)
    selected = [
        mints[(start + i) % len(mints)]
        for i in range(min(batch_size, len(mints)))
    ]

    semaphore = asyncio.Semaphore(5)

    async def fetch(mint):
        async with semaphore:
            try:
                token = await get_token_snapshot(mint)
                if token:
                    token["discovery_source"] = "dexscreener"
                return token
            except Exception:
                return None

    results = await asyncio.gather(
        *(fetch(mint) for mint in selected)
    )

    return [token for token in results if token]
