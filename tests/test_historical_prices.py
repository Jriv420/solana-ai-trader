import time,unittest
from data.historical_prices import pool_for,normalize_candles,comparison
MINT='So11111111111111111111111111111111111111112'
QUOTE='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
POOL='Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE'
class HistoricalPrices(unittest.TestCase):
 def pool(self,base=MINT,created='2023-07-05T14:34:02Z'):
  return {'attributes':{'address':POOL,'pool_created_at':created,'reserve_in_usd':'100'},'relationships':{'base_token':{'data':{'id':'solana_'+base}},'quote_token':{'data':{'id':'solana_'+QUOTE}}}}
 def test_wrong_token_and_later_pool_rejected(self):
  self.assertIsNotNone(pool_for({'data':[self.pool()]},MINT,time.time()))
  self.assertIsNone(pool_for({'data':[self.pool()]},MINT,100))
  self.assertIsNone(pool_for({'data':[self.pool(base=QUOTE)]},MINT,time.time()))
 def test_candle_identity_ohlc_and_nonfinite_validation(self):
  p={'base':MINT,'quote':QUOTE};d={'meta':{'base':{'address':MINT},'quote':{'address':QUOTE}},'data':{'attributes':{'ohlcv_list':[[100,1,2,.5,1.5,100]]}}}
  self.assertEqual(len(normalize_candles(d,MINT,p)),1)
  d['meta']['base']['address']='other'
  with self.assertRaises(ValueError):normalize_candles(d,MINT,p)
  d['meta']['base']['address']=MINT;d['data']['attributes']['ohlcv_list'][0][2]=float('nan')
  with self.assertRaises(ValueError):normalize_candles(d,MINT,p)
 def test_boundary_and_post_exit_highs_do_not_leak_into_held_peak(self):
  c=[[0,1,100,.5,1,1],[60,1,2,.5,1,1],[120,1,3,.5,1.5,1],[180,1,50,.5,1,1],[240,1,70,.5,1,1]]
  a=comparison(c,30,180,60)
  self.assertEqual(a['sampled_high_usd'],3);self.assertEqual(a['held_full_candles'],2)
  self.assertEqual(a['post_exit_high_vs_last_sampled_close_pct'],100*(70/1.5-1))
  self.assertNotIn('sampled_high_usd',comparison(c,31,59,60))
