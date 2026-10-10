from config.settings import settings
import math
def position_size_sol(confidence,available):
    if available<=0:return 0
    c=max(.25,min(1,confidence/100))
    return max(0,math.floor(min(settings.default_buy_sol*c,settings.max_trade_sol,available)*10000)/10000)
