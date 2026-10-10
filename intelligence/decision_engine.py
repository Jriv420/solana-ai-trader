from intelligence.jev import ask_jev
from intelligence.laya import ask_laya
Q=["Does this setup show meaningful participation?","Is accumulation strengthening?","Is there enough evidence to escalate?"]
def _fallback(s):
    b=float(s.get("buys_5m",0)); se=float(s.get("sells_5m",0)); li=float(s.get("liquidity_usd",0)); v=float(s.get("volume_5m_usd",0)); m=float(s.get("price_change_5m_pct",0))
    score=100*(.35*b/max(b+se,1)+.25*min(li/100000,1)+.25*min(v/500000,1)+.15*max(0,min((m+10)/30,1)))
    return {"provider":"deterministic-fallback","score":round(max(0,min(100,score)),1),"raw":{}}
def _score(p):
    vals=[]
    if isinstance(p,dict):
        for k in ("score","confidence","probability"):
            x=p.get(k)
            if isinstance(x,(int,float)):vals.append(float(x))
    if not vals:return None
    x=sum(vals)/len(vals); return max(0,min(100,x*100 if x<=1 else x))
async def evaluate_fast(state):
    try:
        p=await ask_jev(state,Q); s=_score(p); return {"provider":"jev","score":s if s is not None else 50,"raw":p}
    except Exception as je:
        try:
            p=await ask_laya(state,Q); s=_score(p); return {"provider":"laya","score":s if s is not None else 50,"raw":p,"jev_error":str(je)}
        except Exception as le:
            x=_fallback(state); x["jev_error"]=str(je); x["laya_error"]=str(le); return x
