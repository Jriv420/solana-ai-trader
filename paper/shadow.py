"""An isolated, deterministic aggressive paper benchmark; never a live order."""
import math,time
from collections import Counter
from config.settings import settings,risk_trial_status
from database.store import Store,store
from paper.paper_trader import PaperTrader
from strategy.exit import should_exit
from data.tracked_wallets import valid_address
from paper.user_exit import exit_requested
from strategy.sizing import position_size_sol
BOOK=Store('shadow_trades')
TRADER=PaperTrader(BOOK)
STATE={}

def initialize():
    # Tests may replace the DB; always ensure the isolated table in the current DB.
    BOOK.__init__('shadow_trades')
    with store.conn() as c:
        c.execute('CREATE TABLE IF NOT EXISTS shadow_meta(id INTEGER PRIMARY KEY,started_at REAL,ends_at REAL)')
        c.execute('INSERT OR IGNORE INTO shadow_meta VALUES(1,?,?)',(time.time(),risk_trial_status()['ends_at'] or time.time()+86400))
        return dict(c.execute('SELECT * FROM shadow_meta WHERE id=1').fetchone())

def eligible(t,now=None):
    now=time.time() if now is None else now
    if exit_requested(t):return False,'user-requested risk block'
    if not valid_address(t.get('mint','')):return False,'invalid contract'
    security=(t.get('research') or {}).get('security',{})
    if security.get('status')!='ok' or security.get('danger'):return False,'security pending or danger'
    keys=('price_usd','sol_price_usd','liquidity_usd','volume_5m_usd','price_change_5m_pct','timestamp')
    try:v={k:float(t.get(k) or 0) for k in keys}
    except (TypeError,ValueError):return False,'invalid market data'
    if not all(math.isfinite(x) for x in v.values()) or v['price_usd']<=0 or v['sol_price_usd']<=0 or not 0<=now-v['timestamp']<=120:return False,'no fresh price'
    if v['liquidity_usd']<5000:return False,'liquidity below 5000'
    if v['volume_5m_usd']<2000 or v['price_change_5m_pct']<5 or int(t.get('buys_5m') or 0)<=int(t.get('sells_5m') or 0):return False,'momentum or buy flow insufficient'
    return True,'momentum paper benchmark; AI and wallet score not required'

async def manage_exits(observations):
    from intelligence.exit_policy import decide
    by={o['token']['mint']:o['token'] for o in observations}
    for p in BOOK.open():
        t=by.get(p['mint'])
        if not t:continue
        BOOK.mark_peak(p['id'],t.get('price_usd') or 0)
        d=await decide(BOOK,p,t)
        if d['exit']:TRADER.sell(p,t,d['reason'],fraction=d.get('fraction',1))

def step(observations,process_exits=True):
    meta=initialize();by={o['token']['mint']:o['token'] for o in observations};now=time.time()
    for p in BOOK.open() if process_exits else []:
        t=by.get(p['mint'])
        if not t:continue
        BOOK.mark_peak(p['id'],t.get('price_usd') or 0)
        d=should_exit(p,t)
        if d['exit']:TRADER.sell(p,t,d['reason'],fraction=d.get('fraction',1))
    blockers=Counter();buys=0
    active=settings.paper_mode and now<meta['ends_at']
    daily=BOOK.daily_realized(now)
    pause=[]
    if not settings.paper_mode:pause.append('Paper trading disabled')
    elif not active:pause.append('Entry window ended')
    if daily<=-.15:pause.append('Daily realized loss limit reached (0.15 SOL)')
    if len(BOOK.open())>=3:pause.append('Maximum 3 open positions reached')
    if active and not pause:
        candidates=sorted(by.values(),key=lambda t:float(t.get('volume_5m_usd') or 0),reverse=True)
        for t in candidates:
            ok,why=eligible(t,now)
            if not ok:blockers[why]+=1;continue
            positions=BOOK.open()
            if t['mint'] in {p['mint'] for p in positions}:continue
            if len(positions)>=3:
                blockers['maximum open positions reached']+=1;break
            with store.conn() as c:last=c.execute('SELECT MAX(entry_time) n FROM shadow_trades WHERE mint=?',(t['mint'],)).fetchone()['n']
            if last and now-last<3600:
                blockers['same contract entry cooldown (1 hour)']+=1;continue
            from intelligence.entry_learning import safe_assess,safe_screen
            learning=safe_assess('shadow_trades',t)
            safe_screen('shadow_trades',t,learning)
            if learning['action']!='allow':
                blockers['entry learning: '+learning['reason']]+=1
                continue
            t=dict(t,entry_learning=learning)
            # Momentum strength controls simulated size; this is not an AI confidence score.
            strength=50+min(50,max(0,float(t.get('price_change_5m_pct') or 0)-5))
            amount=position_size_sol(strength,TRADER.balance_sol())
            if amount>0 and TRADER.buy(t,amount,{'strategy':'aggressive momentum benchmark','entry_evidence':t,'rules':{'min_liquidity':5000,'min_volume_5m':2000,'min_change_5m':5,'buys_over_sells':True,'wallet_or_ai_required':False}}):buys+=1
            else:blockers['balance or fresh fill unavailable']+=1
    STATE.update(active=active,paper_buys=buys,blockers=dict(blockers),checked_at=now,entry_pause_reasons=pause,daily_realized_sol=daily,daily_loss_limit_sol=.15,daily_limit_resets_at=(int(now//86400)+1)*86400)
    return dict(STATE)

def summary():
    meta=initialize()
    return dict(STATE,active=settings.paper_mode and time.time()<meta['ends_at'],started_at=meta['started_at'],ends_at=meta['ends_at'],balance_sol=TRADER.balance_sol(),min_buy_sol=settings.paper_min_buy_sol,max_buy_sol=min(settings.default_buy_sol,settings.max_trade_sol),metrics=BOOK.paper_metrics(),positions=[{k:v for k,v in p.items() if k!='context'} for p in BOOK.open()],trades=[{k:v for k,v in p.items() if k!='context'} for p in BOOK.all()[:20]],scope='Separate simulated account. Momentum entries with outcome-based paper entry restrictions and AI-reviewed exits. Estimated fees and slippage; protective limits and explicit rule fallbacks remain.')
