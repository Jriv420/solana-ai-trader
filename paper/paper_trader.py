import math,time
from config.settings import settings
from database.store import store

class PaperTrader:
    def open_positions(self):return store.open()
    def balance_sol(self):return settings.paper_starting_sol+store.realized()-sum(float(p["amount_sol"]) for p in self.open_positions())
    def buy(self,t,a,c):
        price=float(t.get('price_usd') or 0);sol_usd=float(t.get('sol_price_usd') or 0)
        if not 0<=time.time()-float(t.get('timestamp') or 0)<=120:return None
        if not all(math.isfinite(x) and x>0 for x in (price,sol_usd,a)) or a>self.balance_sol():return None
        fee=max(0,min(settings.paper_fee_bps,5000))/10000;slip=max(0,min(settings.paper_slippage_bps,5000))/10000
        execution=price*(1+slip);notional=a/(1+fee)
        fill={'version':1,'entry_sol_price_usd':sol_usd,'quantity':notional*sol_usd/execution,'entry_fee_sol':a-notional,'fee_bps':fee*10000,'slippage_bps':slip*10000,'scope':'Estimated proportional fees/slippage; no execution guarantee.'}
        context=dict(c,paper_fill=fill)
        return store.create_trade({"mint":t["mint"],"symbol":t.get("symbol"),"entry_price_usd":execution,"amount_sol":a,"entry_time":time.time(),"context":context})
    def sell(self,p,t,reason):
        price=float(t.get('price_usd') or 0);sol_usd=float(t.get('sol_price_usd') or 0)
        if not 0<=time.time()-float(t.get('timestamp') or 0)<=120:return False
        if not all(math.isfinite(x) and x>0 for x in (price,sol_usd)):return False
        fill=p.get('context',{}).get('paper_fill');a=float(p['amount_sol']);entry=float(p['entry_price_usd'])
        if fill:
            execution=price*(1-fill['slippage_bps']/10000)
            proceeds=fill['quantity']*execution/sol_usd*(1-fill['fee_bps']/10000)
        else:
            # Preserve legacy positions without inventing historical cost or SOL prices.
            execution=price;proceeds=a*price/entry
        sol=proceeds-a;pct=100*sol/a
        return store.close_trade(int(p['id']),execution,time.time(),pct,sol,reason)
paper_trader=PaperTrader()
