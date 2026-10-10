"""First rejection evidence and forward observations; never hindsight entries."""
import json,time
from statistics import median
from database.store import store
from database.research import finite

class Missed:
    def ensure(self):
        with store.conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS missed_cases(mint TEXT PRIMARY KEY,started_at REAL,last_seen REAL,baseline REAL,latest REAL,peak REAL,trough REAL,reasons_json TEXT,evidence_json TEXT)")
    def observe(self,token,reasons,now=None):
        now=time.time() if now is None else now
        price=finite(token.get('price_usd'));stamp=finite(token.get('timestamp'))
        if not price or price<=0 or stamp is None or not 0<=now-stamp<=120:return
        with store.conn() as c:
            if reasons:
                evidence={k:token.get(k) for k in ('market_cap_usd','volume_5m_usd','liquidity_usd','buys_5m','sells_5m','price_change_5m_pct')}
                evidence['features']=(token.get('research') or {}).get('features',{})
                c.execute('INSERT OR IGNORE INTO missed_cases VALUES(?,?,?,?,?,?,?,?,?)',(token['mint'],now,now,price,price,price,price,json.dumps(sorted(set(reasons))),json.dumps(evidence)))
            c.execute('UPDATE missed_cases SET last_seen=?,latest=?,peak=MAX(peak,?),trough=MIN(trough,?) WHERE mint=? AND started_at>=?',(now,price,price,price,token['mint'],now-86400))
            c.execute('DELETE FROM missed_cases WHERE mint NOT IN (SELECT mint FROM missed_cases ORDER BY started_at DESC LIMIT 2000)')
    def mints(self,now=None):
        now=time.time() if now is None else now
        with store.conn() as c:rows=c.execute('SELECT mint FROM missed_cases WHERE started_at>=? AND started_at<? ORDER BY last_seen LIMIT 5',(now-86400,now-60)).fetchall()
        return [r[0] for r in rows]
    def summary(self):
        with store.conn() as c:rows=c.execute('SELECT * FROM missed_cases ORDER BY started_at DESC LIMIT 2000').fetchall()
        groups={};surges=[]
        for r in rows:
            # Wait for at least five minutes of observations, including losers.
            if r['last_seen']-r['started_at']<300:continue
            gain=100*(r['peak']/r['baseline']-1);loss=100*(r['trough']/r['baseline']-1);change=100*(r['latest']/r['baseline']-1)
            reasons=json.loads(r['reasons_json'])
            for reason in reasons:groups.setdefault(reason,[]).append((gain,loss,change))
            if gain>=50:surges.append({'mint':r['mint'],'peak_gain_pct':round(gain,1),'latest_change_pct':round(change,1),'worst_from_baseline_pct':round(loss,1),'reasons':reasons,'at_rejection':json.loads(r['evidence_json'])})
        return {'surges':sorted(surges,key=lambda x:x['peak_gain_pct'],reverse=True)[:10],'by_reason':[{ 'reason':reason,'distinct_coins':len(items),'surged_50_pct':round(100*sum(x[0]>=50 for x in items)/len(items),1),'fell_30_pct':round(100*sum(x[1]<=-30 for x in items)/len(items),1),'median_latest_change_pct':round(median(x[2] for x in items),1)} for reason,items in sorted(groups.items())][:15],'scope':'First recorded rejection per coin, sampled prices over up to 24h. Different follow-up lengths; missing observations and fees prevent treating these as executable profits or causal proof.'}
missed=Missed();missed.ensure()
