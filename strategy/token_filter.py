import math,time
from config.settings import settings

def evaluate_token(t):
    r=[];li=float(t.get('liquidity_usd') or 0);age=t.get('age_minutes');price=float(t.get('price_usd') or 0)
    if t.get('error'):r.append('market data unavailable')
    if (t.get('identity_check') or {}).get('status')=='ambiguous':r.append('lookalike contracts: same name and ticker; original unverified')
    if not math.isfinite(li) or li<settings.min_liquidity_usd:r.append('liquidity below hard minimum')
    if not math.isfinite(price) or price<=0:r.append('price unavailable')
    research=t.get('research')
    if research is not None:
        security=research.get('security',{})
        if security.get('status')!='ok':r.append('security check pending, unavailable or stale')
        elif security.get('danger'):r.append('RugCheck danger or active mint/freeze authority')
    if age is None and t.get('created_at'):age=max(0,(time.time()-t['created_at'])/60)
    mode='revival' if age is None or float(age)>settings.max_token_age_minutes else 'new'
    signals=[]
    if mode=='revival':
        volume=float(t.get('volume_5m_usd') or 0);hour=float(t.get('volume_1h_usd') or 0)
        if not math.isfinite(volume) or not math.isfinite(hour):r.append('revival volume unavailable');volume=0;hour=0
        baseline=max(0,hour-volume)/11
        surge=baseline>0 and volume/baseline>=settings.revival_volume_ratio
        if surge:signals.append('volume acceleration')
        if (t.get('wallet_context') or {}).get('qualified_holders',0)>0:signals.append('qualified wallet holding')
        social=t.get('social_context') or {}
        if social.get('status')=='ok' and social.get('known_influencers'):signals.append('watched KOL mention')
        if research and research.get('claims'):signals.append('reviewed narrative evidence')
        if volume<settings.revival_min_volume_5m_usd:r.append('revival volume below minimum')
        if not signals:r.append('revival needs volume acceleration, qualified wallets, KOL attention or recorded narrative')
        if int(t.get('buys_5m') or 0)<=int(t.get('sells_5m') or 0):r.append('revival buy flow is not strengthening')
    return {'pass':not r,'reasons':r,'mode':mode,'revival_signals':signals}
