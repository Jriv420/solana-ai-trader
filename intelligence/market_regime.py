"""Observed market cohorts, not viability or profit guarantees."""
from database.research import finite

def market_features(token,security):
    cap=finite(token.get('market_cap_usd'));volume=finite(token.get('volume_5m_usd'))
    cap_group='unknown' if cap is None or cap<=0 else 'under_4k' if cap<4000 else '4k_to_10k' if cap<=10000 else '10k_to_100k' if cap<100000 else '100k_to_1m' if cap<1000000 else '1m_plus'
    volume_group='unknown' if volume is None or volume<0 else 'under_1k' if volume<1000 else '1k_to_10k' if volume<10000 else '10k_plus'
    ratio=volume/cap if cap and cap>0 and volume is not None and volume>=0 else None
    risks=security.get('risks') or []
    concentrated=any(any(word in str(r.get('name','')).lower()+' '+str(r.get('description','')).lower() for word in ('large holder','top holder','concentration','single holder')) for r in risks)
    social=token.get('social_context') or {}
    attention='watched_kol_mention' if social.get('status')=='ok' and social.get('known_influencers') else 'none_in_sample' if social.get('status')=='ok' else 'unknown'
    return {'influencer_attention':attention,'market_cap_group':cap_group,'cap_basis':'fdv' if token.get('market_cap_is_fdv') else 'market_cap',
            'volume_5m_group':volume_group,'volume_to_cap_group':'unknown' if ratio is None else 'under_5pct' if ratio<.05 else '5pct_to_25pct' if ratio<.25 else '25pct_plus',
            'holder_concentration':'provider_indicator' if concentrated else 'no_provider_indicator' if security.get('status')=='ok' else 'unknown'}
