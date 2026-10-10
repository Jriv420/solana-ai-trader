import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import app
import database.store as db
from database.store import Store
from data.token_stream import remember_launch, _recent

class DashboardFeeds(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.dbpatch=patch.object(db,'DB',Path(self.tmp.name)/'test.sqlite3');self.dbpatch.start()
        self.store=Store();self.store.ensure_observations()
        from database.wallet_registry import wallet_registry
        wallet_registry.ensure()
        self.apppatch=patch.object(app,'store',self.store);self.apppatch.start()
        self.envpatch=patch.dict(os.environ,{'NEXUS_PASSWORD':'test-password'});self.envpatch.start()
        self.client=TestClient(app.app)
    def tearDown(self):
        self.client.close();self.envpatch.stop();self.apppatch.stop();self.dbpatch.stop();self.tmp.cleanup()
    def get(self,path):
        r=self.client.get(path,auth=('nexus','test-password'));self.assertEqual(r.status_code,200);return r.json()
    def sample(self,mint,volume,cap):
        return {'token':{'mint':mint,'symbol':mint,'volume_5m_usd':volume,'volume_1h_usd':volume*10,'volume_24h_usd':volume*100,'market_cap_usd':cap},'status':'watch','entry':{'combined_score':40,'reasons':['below threshold']}}
    def test_real_launch_is_separate_from_older_discovery(self):
        self.store.record_observation(self.sample('OLD',100,1000))
        with patch('data.token_stream.store',self.store):
            remember_launch({'mint':'NEW','symbol':'$NEW','name':'New','txType':'create'})
        self.assertEqual([x['token']['mint'] for x in self.get('/api/new-pairs')['items']],['NEW'])
        _recent.pop('NEW',None)
    def test_trending_volume_dominates_cap_and_windows(self):
        self.store.record_observation(self.sample('VOLUME',1000,100))
        self.store.record_observation(self.sample('CAP',10,10000))
        for window in ('5m','1h','24h'):
            items=self.get('/api/trending?window='+window)['items']
            self.assertEqual(items[0]['token']['mint'],'VOLUME')
        with self.store.conn() as c:c.execute('UPDATE watched SET last_seen=? WHERE mint=?',(time.time()-601,'VOLUME'))
        self.assertEqual(len(self.get('/api/trending')['items']),1)
    def test_history_survives_reopen_and_records_rejections(self):
        item=self.sample('WATCH',50,100);self.store.record_observation(item)
        item['status']='rejected';item['filter']={'reasons':['liquidity below hard minimum']};item.pop('entry')
        self.store.record_observation(item)
        reopened=Store();reopened.ensure_observations()
        self.assertEqual(reopened.watch_history()[0]['observations'],2)
        history=self.get('/api/watch-history?mint=WATCH')
        self.assertEqual(len(history),2);self.assertEqual(history[0]['status'],'rejected')
        self.assertNotIn('entry',history[0])
    def test_auth_and_all_tabs(self):
        self.assertEqual(self.client.get('/api/watch-history').status_code,401)
        page=self.client.get('/',auth=('nexus','test-password')).text
        for tab in ('scan','positions','agents','routes','history','new','trending','watch'):
            self.assertIn('data-v="'+tab+'"',page)

if __name__=='__main__':unittest.main()
