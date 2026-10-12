import math,time,logging
from paper.user_exit import exit_requested
from config.settings import settings
from database.store import store

class PaperTrader:
    def __init__(self,book=None):self.store=book or store
    def open_positions(self):return self.store.open()
    def balance_sol(self):return settings.paper_starting_sol+self.store.realized()-sum(float(p["amount_sol"]) for p in self.open_positions())
    def buy(self,t,a,c):
        from paper.accounts import enabled
        if not enabled(self.store.trade_table) or exit_requested(t):return None
        price=float(t.get('price_usd') or 0);sol_usd=float(t.get('sol_price_usd') or 0)
        if not 0<=time.time()-float(t.get('timestamp') or 0)<=120:return None
        if not all(math.isfinite(x) and x>0 for x in (price,sol_usd,a)) or a>self.balance_sol():return None
        fee=max(0,min(settings.paper_fee_bps,5000))/10000;slip=max(0,min(settings.paper_slippage_bps,5000))/10000
        execution=price*(1+slip);notional=a/(1+fee)
        fill={'version':1,'entry_sol_price_usd':sol_usd,'quantity':notional*sol_usd/execution,'entry_fee_sol':a-notional,'fee_bps':fee*10000,'slippage_bps':slip*10000,'scope':'Estimated proportional fees/slippage; no execution guarantee.'}
        evidence=t.get('research') or {}
        policy=bool((evidence.get('narrative_rotation') or {}).get('small_cap_rotation_candidate') or ((evidence.get('exit_learning') or {}).get('user_feedback') or {}).get('moonbag_candidate'))
        context=dict(c,paper_fill=fill,paper_narrative_scaleout=policy)
        entered=time.time()
        trade_id=self.store.create_trade({"mint":t["mint"],"symbol":t.get("symbol"),"entry_price_usd":execution,"amount_sol":a,"entry_time":entered,"context":context,"market_cap_usd":t.get("market_cap_usd"),"market_cap_is_fdv":t.get("market_cap_is_fdv",False)})
        from intelligence.trade_evaluation import snapshot,safe_record
        from intelligence.policy_trials import safe_start
        safe_record(self.store.trade_table,trade_id['id'],t['mint'],'entry',{'action':'buy','amount_sol':a,'evidence':snapshot(t),'cost_model':fill,'entry_learning':t.get('entry_learning') or {'action':'not_assessed'},'team':(c.get('entry_team') or c.get('fast') or {}).get('team'), 'execution_reason':c.get('strategy') or 'Original combined strategy and independent risk gates'})
        safe_start(self.store.trade_table,trade_id['id'],t,a,execution,fill,entered)
        return trade_id
    def sell(self,p,t,reason,fraction=1):
        # A protective task may have closed/reduced this position while AI awaited.
        # This synchronous reload and write have no async interleaving point.
        current=next((x for x in self.store.open() if x['id']==p['id']),None)
        if current is None:return False
        if current['amount_sol']!=p['amount_sol']:return False
        p=current
        if not isinstance(fraction,(int,float)) or not math.isfinite(fraction) or not 0<fraction<=1:return False
        if fraction<1 and not settings.paper_mode:return False
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
        sol=(proceeds-a)*fraction;pct=100*sol/(a*fraction)
        protective=reason in ('hard stop','maximum holding time','Security provider reports danger') or 'user-requested' in reason.lower()
        self.store.save_execution_audit(p['id'],{'time':time.time(),'fraction':fraction,'reason':reason,'risk_override':protective,'rule':reason if protective else None,'last_ai_review':{k:(p.get('exit_decision') or {}).get(k) for k in ('provider','action','checked_at')},'evidence':{'price_usd':price,'market_cap_usd':t.get('market_cap_usd'),'timestamp':t.get('timestamp')},'scope':'Execution evidence; a protective exit is independent of the last AI recommendation.'})
        if fraction<1:
            child=self.store.partial_close(p,execution,time.time(),pct,sol,reason,fraction,t.get('market_cap_usd'),t.get('market_cap_is_fdv',False))
            if child:
                from intelligence.exit_learning import start
                start(self.store.trade_table,child,t)
                from intelligence.trade_evaluation import snapshot,safe_record
                safe_record(self.store.trade_table,p['id'],t['mint'],'fill',{'action':'partial_sell','fraction':fraction,'pnl_sol':sol,'reason':reason,'evidence':snapshot(t)})
                logging.getLogger('uvicorn.error').info('NEXUS paper partial exit book=%s trade=%s symbol=%s fraction=%.2f pnl_sol=%.6f',self.store.trade_table,p['id'],p.get('symbol'),fraction,sol)
            return bool(child)
        closed=self.store.close_trade(int(p['id']),execution,time.time(),pct,sol,reason,t.get('market_cap_usd'),t.get('market_cap_is_fdv',False))
        if closed:
            from intelligence.exit_learning import start
            start(self.store.trade_table,int(p['id']),t)
            from intelligence.trade_evaluation import snapshot,safe_record
            safe_record(self.store.trade_table,p['id'],t['mint'],'fill',{'action':'sell_all','pnl_sol':sol,'reason':reason,'evidence':snapshot(t)})
        if closed:logging.getLogger('uvicorn.error').info('NEXUS paper exit book=%s symbol=%s mint=%s pnl_sol=%.6f reason=%s',self.store.trade_table,p.get('symbol'),p['mint'],sol,reason)
        return closed
paper_trader=PaperTrader()
