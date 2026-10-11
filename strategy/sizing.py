from config.settings import settings,trading_settings
import math
def position_size_sol(confidence,available):
    rules=trading_settings(settings)
    if not math.isfinite(available) or available<=0:return 0
    if rules.paper_mode:
        minimum=max(0,rules.paper_min_buy_sol)
        ceiling=min(rules.default_buy_sol,rules.max_trade_sol,available)
        if ceiling<minimum:return 0
        if not math.isfinite(confidence):return 0
        amount=min(ceiling,max(minimum,rules.default_buy_sol*max(0,min(1,confidence/100))))
        return math.floor(amount*10000+1e-9)/10000
    c=max(.25,min(1,confidence/100))
    return max(0,math.floor(min(rules.default_buy_sol*c,rules.max_trade_sol,available)*10000)/10000)
