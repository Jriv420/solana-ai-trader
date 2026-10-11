import math,time
from config.settings import settings
from paper.user_exit import exit_requested,REASON

def should_exit(p,t):
    entry=float(p.get("entry_price_usd") or 0);price=float(t.get("price_usd") or 0)
    timestamp=t.get('timestamp')
    if not all(math.isfinite(v) and v>0 for v in (entry,price)) or timestamp is None or not 0<=time.time()-timestamp<=120:return {"exit":False,"reason":"no fresh valid price"}
    if settings.paper_mode and exit_requested(p):return {'exit':True,'reason':REASON}
    security=(t.get('research') or {}).get('security',{})
    if security.get('status')=='ok' and security.get('danger'):return {'exit':True,'reason':'Security provider reports danger'}
    pnl=(price/entry-1)*100;peak=max(float(p.get('peak_price_usd') or entry),price)
    if pnl<=-abs(settings.stop_loss_pct):return {"exit":True,"reason":"hard stop","pnl_pct":pnl}
    evidence=(t.get('research') or {})
    rotation=evidence.get('narrative_rotation') or {}
    feedback=(evidence.get('exit_learning') or {}).get('user_feedback') or {}
    narrative_candidate=p.get('context',{}).get('paper_narrative_scaleout') or rotation.get('small_cap_rotation_candidate') or feedback.get('moonbag_candidate')
    scaled=bool(p.get('context',{}).get('paper_scale_out_done'))
    if settings.paper_mode and not scaled and narrative_candidate and pnl>=settings.take_profit_pct:
        return {'exit':True,'fraction':.5,'reason':'narrative paper scale-out: sell 50%, trail remainder','pnl_pct':pnl}
    if pnl>=settings.take_profit_pct and not scaled:return {"exit":True,"reason":"take profit","pnl_pct":pnl}
    if settings.trailing_stop_pct>0 and peak>entry and (price/peak-1)*100<=-settings.trailing_stop_pct:return {"exit":True,"reason":"trailing stop","pnl_pct":pnl}
    if settings.paper_max_hold_minutes>0 and time.time()-float(p.get('entry_time') or time.time())>=settings.paper_max_hold_minutes*60:return {"exit":True,"reason":"maximum holding time","pnl_pct":pnl}
    return {"exit":False,"reason":"hold","pnl_pct":pnl}
