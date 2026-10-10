from config.settings import settings,trading_settings
import math
def position_size_sol(confidence,available):
    rules=trading_settings(settings)
    if available<=0:return 0
    c=max(.25,min(1,confidence/100))
    return max(0,math.floor(min(rules.default_buy_sol*c,rules.max_trade_sol,available)*10000)/10000)
