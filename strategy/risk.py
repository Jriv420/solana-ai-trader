from config.settings import settings,trading_settings
import math
def hard_risk_check(amount,open_positions,daily_pnl,token):
    rules=trading_settings(settings)
    r=[]
    if not math.isfinite(amount):r.append("invalid trade size")
    if amount<=0:r.append("amount must be positive")
    if amount>rules.max_trade_sol:r.append("trade exceeds max")
    if open_positions>=rules.max_open_positions:r.append("max positions reached")
    if daily_pnl<=-abs(rules.max_daily_loss_sol):r.append("daily loss reached")
    if float(token.get("liquidity_usd",0))<rules.min_liquidity_usd:r.append("liquidity too low")
    return {"pass":not r,"reasons":r}
