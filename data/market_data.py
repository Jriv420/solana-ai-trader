import time, httpx
DEX="https://api.dexscreener.com/latest/dex/tokens/{mint}"
async def get_token_snapshot(mint):
    async with httpx.AsyncClient(timeout=5.0) as c:
        r=await c.get(DEX.format(mint=mint)); r.raise_for_status(); p=r.json()
    pairs=[x for x in p.get("pairs",[]) if x.get("chainId")=="solana"]
    if not pairs:return None
    x=max(pairs,key=lambda z:float((z.get("liquidity") or {}).get("usd") or 0))
    created=x.get("pairCreatedAt") or int(time.time()*1000)
    return {"mint":mint,"symbol":(x.get("baseToken") or {}).get("symbol") or mint[:6],
            "name":(x.get("baseToken") or {}).get("name") or "Unknown",
            "price_usd":float(x.get("priceUsd") or 0),
            "market_cap_usd":float(x.get("marketCap") or x.get("fdv") or 0),
            "liquidity_usd":float((x.get("liquidity") or {}).get("usd") or 0),
            "volume_5m_usd":float((x.get("volume") or {}).get("m5") or 0),
            "price_change_5m_pct":float((x.get("priceChange") or {}).get("m5") or 0),
            "buys_5m":int(((x.get("txns") or {}).get("m5") or {}).get("buys") or 0),
            "sells_5m":int(((x.get("txns") or {}).get("m5") or {}).get("sells") or 0),
            "age_minutes":max(0,(time.time()*1000-created)/60000),
            "dex_id":x.get("dexId") or "unknown","source":"dexscreener"}
