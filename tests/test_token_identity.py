import unittest
from intelligence.token_identity import annotate
from strategy.token_filter import evaluate_token

class TokenIdentityTests(unittest.TestCase):
    def token(self,mint,name='Reels',symbol='REELS'):
        return {'mint':mint,'name':name,'symbol':symbol,'price_usd':1,'liquidity_usd':100000,'age_minutes':1}
    def test_known_match_warns_without_guessing_original(self):
        tokens=annotate([self.token('A'),self.token('B',' Ｒｅｅｌｓ ','$reels')],[])
        for token in tokens:
            self.assertEqual(token['identity_check']['status'],'ambiguous')
            self.assertTrue(evaluate_token(token)['pass'])
            token['research']={'security':{'status':'pending'}}
            self.assertFalse(evaluate_token(token)['pass'])
        later=annotate([self.token('C')],[self.token('A')])[0]
        self.assertEqual(later['identity_check']['matching_contracts'],['A'])
    def test_repeated_mint_not_copy_and_symbol_alone_not_proof(self):
        tokens=annotate([self.token('A'),self.token('A'),self.token('B','Different')],[])
        self.assertEqual(len(tokens),2)
        self.assertTrue(all(x['identity_check']['status']=='no_match_observed' for x in tokens))
    def test_unknown_metadata_not_grouped(self):
        tokens=annotate([self.token('A','Unknown'),self.token('B','Unknown')],[])
        self.assertTrue(all(x['identity_check']['matching_count']==0 for x in tokens))
