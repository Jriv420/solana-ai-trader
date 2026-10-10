from config.settings import settings
def hard_risk_check(amount,open_positions,daily_pnl,token):
    r=[]
    if amount<=0:r.append("amount must be positive")
    if amount>settings.max_trade_sol:r.append("trade exceeds max")
    if open_positions>=settings.max_open_positions:r.append("max positions reached")
    if daily_pnl<=-abs(settings.max_daily_loss_sol):r.append("daily loss reached")
    if float(token.get("liquidity_usd",0))<settings.min_liquidity_usd:r.append("liquidity too low")
    return {"pass":not r,"reasons":r}
