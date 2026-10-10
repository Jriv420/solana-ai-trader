def choose_route(t):
    d=str(t.get("dex_id","")).lower();age=float(t.get("age_minutes",9999))
    if "pump" in d and age<60:return {"route":"pump-direct","reason":"fresh Pump"}
    if "pump" in d:return {"route":"pumpswap","reason":"Pump-related liquidity"}
    if d in {"raydium","meteora"}:return {"route":d,"reason":"direct pool"}
    return {"route":"jupiter","reason":"aggregator fallback"}
