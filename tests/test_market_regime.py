import unittest
from intelligence.market_regime import market_features
from intelligence.risk_ai import score_contextual_risk

class MarketRegimeTests(unittest.TestCase):
    def test_small_and_large_cohorts_are_separate(self):
        small=market_features({'market_cap_usd':4000,'volume_5m_usd':200},{'status':'ok','risks':[]})
        self.assertEqual(small['market_cap_group'],'4k_to_10k')
        self.assertEqual(small['volume_5m_group'],'under_1k')
        large=market_features({'market_cap_usd':2000000,'volume_5m_usd':100000,'market_cap_is_fdv':True},{'status':'ok'})
        self.assertEqual(large['market_cap_group'],'1m_plus');self.assertEqual(large['cap_basis'],'fdv')
        self.assertEqual(market_features({'market_cap_usd':10000},{})['market_cap_group'],'4k_to_10k')
    def test_unknown_is_not_zero_or_safe(self):
        result=market_features({'market_cap_usd':float('nan'),'volume_5m_usd':None},{'status':'unavailable'})
        self.assertEqual(result['market_cap_group'],'unknown');self.assertEqual(result['volume_5m_group'],'unknown')
        self.assertEqual(result['holder_concentration'],'unknown')
        self.assertEqual(result['influencer_attention'],'unknown')
        observed=market_features({'social_context':{'status':'ok','known_influencers':['kol']}},{})
        self.assertEqual(observed['influencer_attention'],'watched_kol_mention')
    def test_provider_concentration_adds_risk(self):
        features=market_features({}, {'status':'ok','risks':[{'name':'Top holders concentration'}]})
        self.assertEqual(features['holder_concentration'],'provider_indicator')
        token={'liquidity_usd':50000,'buys_5m':10,'sells_5m':5,'price_change_5m_pct':0}
        baseline=score_contextual_risk(token)['score']
        token['research']={'features':features}
        self.assertEqual(score_contextual_risk(token)['score'],baseline+10)
