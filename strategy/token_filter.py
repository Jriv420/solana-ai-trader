from config.settings import settings
def evaluate_token(t):
    r=[]; li=float(t.get("liquidity_usd",0)); age=float(t.get("age_minutes",0))
    if t.get("error"):r.append("market data unavailable")
    if li<settings.min_liquidity_usd:r.append("liquidity below hard minimum")
    if age>settings.max_token_age_minutes:r.append("token older than maximum")
    return {"pass":not r,"reasons":r}
