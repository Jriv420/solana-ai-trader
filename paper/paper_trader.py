import time
from config.settings import settings
from database.store import store
class PaperTrader:
    def open_positions(self):return store.open()
    def balance_sol(self):return settings.paper_starting_sol+store.realized()-sum(float(p["amount_sol"]) for p in self.open_positions())
    def buy(self,t,a,c):
        return store.create_trade({"mint":t["mint"],"symbol":t.get("symbol"),"entry_price_usd":float(t["price_usd"]),"amount_sol":a,"entry_time":time.time(),"context":c})
    def sell(self,p,t,reason):
        price=float(t["price_usd"]);entry=float(p["entry_price_usd"]);a=float(p["amount_sol"]);pct=(price/entry-1)*100;sol=a*pct/100
        store.close_trade(int(p["id"]),price,time.time(),pct,sol,reason)
paper_trader=PaperTrader()
