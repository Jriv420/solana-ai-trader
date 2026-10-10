from config.settings import settings
def position_size_sol(confidence,available):
    c=max(.25,min(1,confidence/100)); return round(max(.001,min(settings.default_buy_sol*c,settings.max_trade_sol,available)),4)
