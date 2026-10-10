"""Quota-aware Gemini second opinion; Google project billing controls free access."""
import asyncio,json,math,re,time
from datetime import datetime,timezone
import httpx
from config.settings import settings
from database.store import store
from intelligence.openai_review import ReviewPaused,request_body as openai_body

_semaphore=asyncio.Semaphore(1)
_blocked_until=0
_reviews={}

def usage():
    day=datetime.now(timezone.utc).date().isoformat()
    return {'model':settings.gemini_model,'requests_today':store.ai_request_count('gemini',day),
            'daily_request_limit':max(0,settings.gemini_daily_request_limit),'day':day,
            'billing_note':'Keep Google project billing disabled for free-tier access. Provider quotas may be lower than this app limit.'}

def request_body(state):
    # Share evidence limits and conservative instructions with the OpenAI adapter.
    body=openai_body(state)
    return {'systemInstruction':{'parts':[{'text':body['instructions']}]},
            'contents':[{'role':'user','parts':[{'text':body['input']}]}],
            'generationConfig':{'candidateCount':1,'maxOutputTokens':1000,
                'thinkingConfig':{'thinkingLevel':'LOW','includeThoughts':False},
                'responseMimeType':'application/json',
                'responseSchema':{'type':'OBJECT','properties':{
                    'score':{'type':'NUMBER','minimum':0,'maximum':100},
                    'reason':{'type':'STRING'}},'required':['score','reason']}}}

def normalize_response(data):
    if not isinstance(data,dict) or data.get('promptFeedback',{}).get('blockReason'):
        raise ValueError('Blocked response')
    candidates=data.get('candidates',[])
    if len(candidates)!=1 or candidates[0].get('finishReason')!='STOP':raise ValueError('Incomplete response')
    parts=candidates[0].get('content',{}).get('parts',[])
    # Never treat internal thinking or a tool call as the returned review.
    if any('functionCall' in p for p in parts):raise ValueError('Unexpected tool call')
    answer=json.loads(''.join(p.get('text','') for p in parts if not p.get('thought')))
    score=answer.get('score');reason=answer.get('reason')
    if (not isinstance(score,(int,float)) or isinstance(score,bool) or not math.isfinite(score)
        or not 0<=score<=100 or not isinstance(reason,str)):raise ValueError('Invalid review')
    return {'score':score,'review':{'reason':reason[:1000],'model':data.get('modelVersion'),
                                  'usage':data.get('usageMetadata')}}

async def ask_gemini(state):
    global _blocked_until
    if not settings.gemini_api_key:raise ReviewPaused('not_configured')
    if settings.gemini_daily_request_limit<=0:raise ReviewPaused('daily_limit_reached')
    if not re.fullmatch(r'gemini-[a-zA-Z0-9.-]+',settings.gemini_model):raise ReviewPaused('invalid_model')
    key=state.get('mint');body=request_body(state)
    async with _semaphore:
        now=time.time();cached=_reviews.get(key)
        if key and cached and now-cached[0]<900:return dict(cached[1],cached=True)
        if now<_blocked_until:raise ReviewPaused('cooldown')
        day=datetime.now(timezone.utc).date().isoformat()
        if not store.reserve_ai_request('gemini',day,settings.gemini_daily_request_limit):
            raise ReviewPaused('daily_limit_reached')
        # At most one attempt per minute, including manual tests and failures.
        _blocked_until=now+60
        async with httpx.AsyncClient(timeout=max(1,settings.gemini_timeout_ms/1000)) as client:
            response=await client.post(settings.gemini_endpoint+settings.gemini_model+':generateContent',
                headers={'x-goog-api-key':settings.gemini_api_key},json=body)
        if response.status_code in (429,503):
            try:delay=float(response.headers.get('Retry-After','300'))
            except ValueError:delay=300
            _blocked_until=time.time()+max(60,min(3600,delay if math.isfinite(delay) else 300))
            raise ReviewPaused('provider_quota_or_capacity' if response.status_code==429 else 'provider_unavailable')
        if response.status_code in (401,403):raise ReviewPaused('key_or_access_rejected')
        if response.status_code==404:raise ReviewPaused('model_unavailable')
        response.raise_for_status()
        result=normalize_response(response.json())
        if key:
            _reviews[key]=(time.time(),result)
            if len(_reviews)>1000:_reviews.pop(min(_reviews,key=lambda k:_reviews[k][0]))
    return result
