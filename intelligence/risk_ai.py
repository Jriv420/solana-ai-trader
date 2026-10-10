def score_contextual_risk(t):
    r=35.0; liq=float(t.get("liquidity_usd",0)); buys=int(t.get("buys_5m",0)); sells=int(t.get("sells_5m",0)); ch=float(t.get("price_change_5m_pct",0))
    if liq<20000:r+=20
    if sells>buys:r+=15
    if abs(ch)>25:r+=15
    return {"score":round(max(0,min(100,r)),1),"reason":"liquidity + flow + volatility"}
