"""Bounded model discretion over strategy thresholds in paper mode only."""
import math
from config.settings import settings,trading_settings

def eligible(token,filtered):
    rules=trading_settings(settings)
    security=(token.get('research') or {}).get('security',{})
    price=float(token.get('price_usd') or 0);li=float(token.get('liquidity_usd') or 0)
    return (rules.paper_mode and security.get('status')=='ok' and not security.get('danger')
        and not token.get('error') and math.isfinite(price) and price>0
        and math.isfinite(li) and li>=rules.min_liquidity_usd
        and float(token.get('volume_5m_usd') or 0)>=1000
        and int(token.get('buys_5m') or 0)>int(token.get('sells_5m') or 0))

def decide(token,filtered,entry,assessment,risk):
    rules=trading_settings(settings)
    allowed=(eligible(token,filtered) and assessment.get('provider') in {'jev','laya','darwin'}
        and float(assessment.get('score') or 0)>=(65 if rules is not settings else 75) and risk<=rules.max_risk_score)
    return {'allowed':allowed,'type':'AI paper exception','waived_reasons':filtered.get('reasons',[])+entry.get('reasons',[]) if allowed else [],'model':assessment.get('provider'),'score':assessment.get('score')}
