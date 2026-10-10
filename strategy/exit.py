import math,time
from config.settings import settings

def should_exit(p,t):
    entry=float(p.get("entry_price_usd") or 0);price=float(t.get("price_usd") or 0)
    timestamp=t.get('timestamp')
    if not all(math.isfinite(v) and v>0 for v in (entry,price)) or timestamp is None or not 0<=time.time()-timestamp<=120:return {"exit":False,"reason":"no fresh valid price"}
    pnl=(price/entry-1)*100;peak=max(float(p.get('peak_price_usd') or entry),price)
    if pnl<=-abs(settings.stop_loss_pct):return {"exit":True,"reason":"hard stop","pnl_pct":pnl}
    if pnl>=settings.take_profit_pct:return {"exit":True,"reason":"take profit","pnl_pct":pnl}
    if settings.trailing_stop_pct>0 and peak>entry and (price/peak-1)*100<=-settings.trailing_stop_pct:return {"exit":True,"reason":"trailing stop","pnl_pct":pnl}
    if settings.paper_max_hold_minutes>0 and time.time()-float(p.get('entry_time') or time.time())>=settings.paper_max_hold_minutes*60:return {"exit":True,"reason":"maximum holding time","pnl_pct":pnl}
    return {"exit":False,"reason":"hold","pnl_pct":pnl}
