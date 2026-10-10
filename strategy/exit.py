def should_exit(p,t):
    e=float(p.get("entry_price_usd",0)); price=float(t.get("price_usd",0))
    if e<=0 or price<=0:return {"exit":False,"reason":"no valid price"}
    pnl=(price/e-1)*100
    if pnl<=-20:return {"exit":True,"reason":"hard stop","pnl_pct":pnl}
    if pnl>=50:return {"exit":True,"reason":"take profit","pnl_pct":pnl}
    return {"exit":False,"reason":"hold","pnl_pct":pnl}
