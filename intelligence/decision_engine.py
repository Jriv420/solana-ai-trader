from intelligence.jev import ask_jev
from intelligence.laya import ask_laya
from intelligence.darwin import ask_darwin
import math,time
CONNECTIONS={}
_CACHE={}
Q=["Use research evidence and learned forward outcomes. Never infer identity or endorsement from a token receipt. User-reviewed claims are not independently authenticated. Unknown bundle/security data is not safe data. Distinguish gains from subsequent drawdowns.","Does this setup show meaningful participation?","Is accumulation strengthening?","Is there enough evidence to escalate?"]
def _fallback(s):
    b=float(s.get("buys_5m",0)); se=float(s.get("sells_5m",0)); li=float(s.get("liquidity_usd",0)); v=float(s.get("volume_5m_usd",0)); m=float(s.get("price_change_5m_pct",0))
    score=100*(.35*b/max(b+se,1)+.25*min(li/100000,1)+.25*min(v/500000,1)+.15*max(0,min((m+10)/30,1)))
    return {"provider":"deterministic-fallback","score":round(max(0,min(100,score)),1),"raw":{}}
def _score(p):
    vals=[]
    if isinstance(p,dict):
        for k in ("score","confidence","probability"):
            x=p.get(k)
            if isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x):
                vals.append(float(x)*100 if k!='score' and 0<=x<=1 else float(x))
    if not vals:return None
    x=sum(vals)/len(vals); return max(0,min(100,x))
async def provider_result(provider,state):
    try:
        if provider=='jev':response=await ask_jev(state,Q)
        elif provider=='laya':response=await ask_laya(state,Q)
        else:response=await ask_darwin("Evaluate evidence conservatively. "+" ".join(Q)+" Return a numeric score from 0 to 100.",state)
        score=_score(response)
        if score is None:raise ValueError('No finite numeric score')
        CONNECTIONS[provider]={'status':'verified_response','checked_at':time.time()}
        return {'provider':provider,'score':score,'raw':response}
    except Exception:
        from config.settings import settings
        configured=bool(getattr(settings,provider+'_api_key') and getattr(settings,provider+'_endpoint'))
        CONNECTIONS[provider]={'status':'unavailable_or_incompatible' if configured else 'not_configured','checked_at':time.time()}
        return None

async def evaluate_fast(state):
    key=state.get('mint');now=time.time();cached=_CACHE.get(key)
    # Cache AI assessments briefly; market/wallet/security gates are recalculated every scan.
    if key and cached and now-cached[0]<30:return dict(cached[1],cached=True)
    result=None
    for provider in ('jev','laya','darwin'):
        if provider=='darwin' and _fallback(state)['score']<60:break
        result=await provider_result(provider,state)
        if result is not None:break
    if result is None:result=_fallback(state)
    if key:
        _CACHE[key]=(now,result)
        if len(_CACHE)>1000:_CACHE.pop(min(_CACHE,key=lambda k:_CACHE[k][0]))
    return result
