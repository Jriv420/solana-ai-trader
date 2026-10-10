"""Signed, expiring browser sessions alongside existing Basic authentication."""
import base64,hashlib,hmac,os,secrets,time
from urllib.parse import parse_qs,urlsplit
from fastapi import Request
from fastapi.responses import FileResponse,RedirectResponse,Response

COOKIE='nexus_session';TTL=12*3600
_attempts={}

def signature(value,password):
    key=hashlib.sha256(('nexus-browser-session:'+password).encode()).digest()
    return hmac.new(key,value.encode(),hashlib.sha256).hexdigest()

def session(password,now=None):
    value=str(int(time.time() if now is None else now))+'.'+secrets.token_hex(16)
    return value+'.'+signature(value,password)

def valid_session(token,password,now=None):
    try:
        issued,nonce,signed=token.split('.');value=issued+'.'+nonce
        elapsed=(time.time() if now is None else now)-int(issued)
        return len(nonce)==32 and 0<=elapsed<TTL and secrets.compare_digest(signed,signature(value,password))
    except (AttributeError,ValueError,TypeError):return False

def same_origin(request):
    origin=request.headers.get('origin')
    if not origin:return False
    parsed=urlsplit(origin)
    return parsed.scheme in ('https','http') and parsed.netloc.lower()==request.headers.get('host','').lower()

def install(app,dashboard):
    @app.get('/login')
    async def login_page():
        return FileResponse(dashboard/'login.html',headers={'Cache-Control':'no-store'})

    @app.post('/login')
    async def login(request:Request):
        password=os.getenv('NEXUS_PASSWORD')
        if not password:return Response('Dashboard password is not configured.',status_code=503)
        if request.headers.get('origin') and not same_origin(request):return Response('Origin rejected',status_code=403)
        if request.headers.get('content-type','').split(';')[0]!='application/x-www-form-urlencoded':return Response('Invalid form',status_code=415)
        body=await request.body()
        if len(body)>4096:return Response('Form too large',status_code=413)
        ip=request.client.host if request.client else 'unknown';now=time.time()
        attempts=[t for t in _attempts.get(ip,[]) if now-t<60]
        if len(attempts)>=10:return RedirectResponse('/login?error=rate',status_code=303)
        _attempts[ip]=attempts+[now]
        if len(_attempts)>1000:_attempts.pop(next(iter(_attempts)))
        supplied=parse_qs(body.decode('utf-8',errors='replace')).get('password',[''])[0]
        if not secrets.compare_digest(supplied.encode(),password.encode()):return RedirectResponse('/login?error=password',status_code=303)
        response=RedirectResponse('/',status_code=303,headers={'Cache-Control':'no-store'})
        response.set_cookie(COOKIE,session(password),max_age=TTL,secure=True,httponly=True,samesite='strict')
        return response

    @app.middleware('http')
    async def security(request,call_next):
        if request.url.path in ('/login','/healthz'):return await call_next(request)
        password=os.getenv('NEXUS_PASSWORD')
        if not password:return Response('NEXUS password not configured',status_code=503)
        cookie_ok=valid_session(request.cookies.get(COOKIE),password);basic_ok=False
        authorization=request.headers.get('Authorization','')
        if authorization.startswith('Basic '):
            try:
                username,supplied=base64.b64decode(authorization.split(' ',1)[1]).decode().split(':',1)
                basic_ok=secrets.compare_digest(username,'nexus') and secrets.compare_digest(supplied.encode(),password.encode())
            except (ValueError,UnicodeDecodeError):pass
        if not (cookie_ok or basic_ok):
            if request.url.path=='/':return RedirectResponse('/login',status_code=303)
            return Response('Login required',status_code=401,headers={'WWW-Authenticate':'Basic realm="NEXUS"','Cache-Control':'no-store'})
        if cookie_ok and not basic_ok and request.method not in ('GET','HEAD','OPTIONS') and not same_origin(request):
            return Response('Origin rejected',status_code=403)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        if basic_ok and not cookie_ok:response.set_cookie(COOKIE,session(password),max_age=TTL,secure=True,httponly=True,samesite='strict')
        return response
