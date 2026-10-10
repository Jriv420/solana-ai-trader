from config.settings import settings
def evaluate_token(t):
    r=[]; li=float(t.get("liquidity_usd",0)); age=t.get("age_minutes")
    if t.get("error"):r.append("market data unavailable")
    if li<settings.min_liquidity_usd:r.append("liquidity below hard minimum")
    if age is not None and float(age)>settings.max_token_age_minutes:r.append("token older than maximum")
    research=t.get('research')
    if research is not None:
        security=research.get('security',{})
        if security.get('status')!='ok':r.append("security check pending, unavailable or stale")
        elif security.get('danger'):r.append("RugCheck danger or active mint/freeze authority")
    return {"pass":not r,"reasons":r}
