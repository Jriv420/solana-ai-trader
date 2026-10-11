import json,sqlite3,time,os,math
from datetime import datetime,timezone
from pathlib import Path
DEFAULT_DB=Path(__file__).resolve().parent/"trades.sqlite3"
DB=Path(os.getenv("DB_PATH") or (str(Path(os.environ["RAILWAY_VOLUME_MOUNT_PATH"])/"trades.sqlite3") if os.getenv("RAILWAY_VOLUME_MOUNT_PATH") else str(DEFAULT_DB)))
def valid_cap(value):
    try:
        n=float(value)
        return n if math.isfinite(n) and n>0 else None
    except (TypeError,ValueError):return None

class Store:
    def __init__(self,trade_table="trades"):
        if trade_table not in {"trades","shadow_trades"}:raise ValueError("Invalid trade table")
        self.trade_table=trade_table
        with self.conn() as c:c.execute(f'CREATE TABLE IF NOT EXISTS {self.trade_table}(id INTEGER PRIMARY KEY AUTOINCREMENT,mint TEXT,symbol TEXT,entry_price_usd REAL,exit_price_usd REAL,amount_sol REAL,entry_time REAL,exit_time REAL,status TEXT,pnl_pct REAL,pnl_sol REAL,exit_reason TEXT,context_json TEXT)')
        with self.conn() as c:
            if 'peak_price_usd' not in {r['name'] for r in c.execute(f'PRAGMA table_info({self.trade_table})')}:c.execute(f'ALTER TABLE {self.trade_table} ADD COLUMN peak_price_usd REAL')
        with self.conn() as c:
            columns={r['name'] for r in c.execute(f'PRAGMA table_info({self.trade_table})')}
            for field,kind in (('entry_market_cap_usd','REAL'),('exit_market_cap_usd','REAL'),('entry_cap_is_fdv','INTEGER'),('exit_cap_is_fdv','INTEGER')):
                if field not in columns:c.execute(f'ALTER TABLE {self.trade_table} ADD COLUMN {field} {kind}')
    def conn(self):
        DB.parent.mkdir(parents=True,exist_ok=True)
        c=sqlite3.connect(DB,timeout=15);c.row_factory=sqlite3.Row;return c
    def ai_request_count(self,provider,day):
        with self.conn() as c:
            c.execute('CREATE TABLE IF NOT EXISTS ai_requests(provider TEXT,day TEXT,attempts INTEGER,PRIMARY KEY(provider,day))')
            r=c.execute('SELECT attempts FROM ai_requests WHERE provider=? AND day=?',(provider,day)).fetchone()
        return r['attempts'] if r else 0
    def reserve_ai_request(self,provider,day,limit):
        # Count before sending, including failed requests and manual connection tests.
        with self.conn() as c:
            c.execute('CREATE TABLE IF NOT EXISTS ai_requests(provider TEXT,day TEXT,attempts INTEGER,PRIMARY KEY(provider,day))')
            c.execute('BEGIN IMMEDIATE')
            c.execute('INSERT OR IGNORE INTO ai_requests VALUES(?,?,0)',(provider,day))
            used=c.execute('SELECT attempts FROM ai_requests WHERE provider=? AND day=?',(provider,day)).fetchone()['attempts']
            if used>=max(0,limit):return False
            c.execute('UPDATE ai_requests SET attempts=attempts+1 WHERE provider=? AND day=?',(provider,day))
            c.execute('DELETE FROM ai_requests WHERE day<?',(day[:4]+'-01-01',))
        return True
    def row(self,r):
        x=dict(r);raw=x.pop("context_json",None);x["context"]=json.loads(raw) if raw else {}
        if x.get('entry_market_cap_usd') is None:
            # Old entry snapshots are historical evidence; never use today's cap.
            t=x['context'].get('entry_evidence') or x['context'].get('token') or {}
            cap=valid_cap(t.get('market_cap_usd'))
            if cap is not None:x.update(entry_market_cap_usd=cap,entry_cap_is_fdv=bool(t.get('market_cap_is_fdv')))
        x['risk_samples']=x['context'].get('risk_samples',[])
        x['exit_decision']=x['context'].get('exit_decision')
        x['partial_exit']=x['context'].get('partial_exit')
        x['paper_narrative_scaleout']=bool(x['context'].get('paper_narrative_scaleout'))
        x['entry_team']=(x['context'].get('entry_team') or x['context'].get('fast') or {}).get('team')
        x['execution_audit']=x['context'].get('execution_audit')
        x['entry_execution']={'reason':x['context'].get('strategy') or 'Combined entry scores and deterministic risk gates','rules':x['context'].get('rules'),'combined_score':(x['context'].get('entry') or {}).get('combined_score'),'risk':x['context'].get('risk'),'scope':'Recorded buy-time inputs; historical missing model reviews remain unknown.'}
        x['entry_method']=x['context'].get('strategy') or 'Original entry strategy'
        x['paper_scale_out_done']=bool(x['context'].get('paper_scale_out_done'))
        from intelligence.exit_learning import RUNNER,FEEDBACK
        if x.get('mint')==RUNNER:x['user_exit_feedback']=FEEDBACK
        if x.get('status')=='closed':
            from intelligence.exit_learning import review
            x['exit_review']=review(self.trade_table,x['id'])
        return x
    def create_trade(self,t):
        with self.conn() as c:
            cur=c.execute(f'INSERT INTO {self.trade_table}(mint,symbol,entry_price_usd,amount_sol,entry_time,status,context_json,entry_market_cap_usd,entry_cap_is_fdv) VALUES(?,?,?,?,?,"open",?,?,?)',(t["mint"],t.get("symbol"),t["entry_price_usd"],t["amount_sol"],t["entry_time"],json.dumps(t.get("context",{})),valid_cap(t.get("market_cap_usd")),int(bool(t.get("market_cap_is_fdv")))));t["id"]=cur.lastrowid
        return t
    def close_trade(self,i,price,tm,pct,sol,reason,market_cap_usd=None,cap_is_fdv=False):
        with self.conn() as c:
            result=c.execute(f"UPDATE {self.trade_table} SET exit_price_usd=?,exit_time=?,status='closed',pnl_pct=?,pnl_sol=?,exit_reason=?,exit_market_cap_usd=?,exit_cap_is_fdv=? WHERE id=? AND status='open'",(price,tm,pct,sol,reason,valid_cap(market_cap_usd),int(bool(cap_is_fdv)),i))
            return bool(result.rowcount)
    def partial_close(self,p,price,tm,pct,sol,reason,fraction,market_cap_usd,cap_is_fdv):
        if not 0<fraction<1:return None
        with self.conn() as c:
            c.execute('BEGIN IMMEDIATE')
            r=c.execute(f'SELECT * FROM {self.trade_table} WHERE id=? AND status="open"',(p['id'],)).fetchone()
            if not r or r['amount_sol']!=p['amount_sol']:return None
            context=json.loads(r['context_json'] or '{}')
            if context.get('paper_scale_out_done') and not reason.startswith('AI exit'):return None
            closed_context=dict(context,partial_exit={'parent_trade_id':p['id'],'fraction':fraction})
            remaining_context=dict(context,paper_scale_out_done=True)
            if context.get('paper_fill'):
                for target,ratio in ((closed_context,fraction),(remaining_context,1-fraction)):
                    target['paper_fill']=dict(context['paper_fill'])
                    for key in ('quantity','entry_fee_sol'):target['paper_fill'][key]*=ratio
            closed=dict(r);closed.pop('id')
            closed.update(amount_sol=r['amount_sol']*fraction,exit_price_usd=price,exit_time=tm,status='closed',pnl_pct=pct,pnl_sol=sol,exit_reason=reason,context_json=json.dumps(closed_context),exit_market_cap_usd=valid_cap(market_cap_usd),exit_cap_is_fdv=int(bool(cap_is_fdv)))
            keys=list(closed)
            cur=c.execute(f'INSERT INTO {self.trade_table}({",".join(keys)}) VALUES({",".join("?" for _ in keys)})',tuple(closed[k] for k in keys))
            c.execute(f'UPDATE {self.trade_table} SET amount_sol=?,context_json=? WHERE id=?',(r['amount_sol']*(1-fraction),json.dumps(remaining_context),p['id']))
            return cur.lastrowid
    def record_risk_sample(self,i,t):
        price=valid_cap(t.get('price_usd'));stamp=valid_cap(t.get('timestamp'))
        if price is None or stamp is None or not 0<=time.time()-stamp<=120:return
        with self.conn() as c:
            c.execute('BEGIN IMMEDIATE')
            r=c.execute(f'SELECT context_json FROM {self.trade_table} WHERE id=? AND status="open"',(i,)).fetchone()
            if not r:return
            context=json.loads(r['context_json'] or '{}');samples=context.get('risk_samples',[])
            if samples and samples[-1]['timestamp']>=stamp:return
            sample={k:t.get(k) for k in ('timestamp','price_usd','market_cap_usd','liquidity_usd','volume_5m_usd','buys_5m','sells_5m')}
            context['risk_samples']=(samples+[sample])[-12:]
            c.execute(f'UPDATE {self.trade_table} SET context_json=? WHERE id=?',(json.dumps(context),i))
    def save_exit_decision(self,i,decision):
        with self.conn() as c:
            c.execute('BEGIN IMMEDIATE')
            r=c.execute(f'SELECT context_json FROM {self.trade_table} WHERE id=? AND status="open"',(i,)).fetchone()
            if not r:return False
            context=json.loads(r['context_json'] or '{}');context['exit_decision']=decision
            c.execute(f'UPDATE {self.trade_table} SET context_json=? WHERE id=?',(json.dumps(context),i))
            c.execute('CREATE TABLE IF NOT EXISTS exit_decisions(id TEXT PRIMARY KEY,book TEXT,trade_id INTEGER,checked_at REAL,payload_json TEXT)')
            c.execute('INSERT INTO exit_decisions VALUES(?,?,?,?,?)',(decision['id'],self.trade_table,i,decision['checked_at'],json.dumps(decision)))
            c.execute('DELETE FROM exit_decisions WHERE id NOT IN (SELECT id FROM exit_decisions ORDER BY checked_at DESC LIMIT 2000)')
        return True
    def consume_exit_decision(self,i,decision_id):
        # Persist before applying: a restart cannot replay the same partial sale.
        with self.conn() as c:
            c.execute('BEGIN IMMEDIATE')
            r=c.execute(f'SELECT context_json FROM {self.trade_table} WHERE id=? AND status="open"',(i,)).fetchone()
            if not r:return False
            context=json.loads(r['context_json'] or '{}');d=context.get('exit_decision') or {}
            if d.get('id')!=decision_id or d.get('consumed'):return False
            d['consumed']=True
            c.execute(f'UPDATE {self.trade_table} SET context_json=? WHERE id=?',(json.dumps(context),i))
        return True
    def open(self):
        with self.conn() as c:rows=c.execute(f"SELECT * FROM {self.trade_table} WHERE status='open'").fetchall()
        return [self.row(r) for r in rows]
    def all(self):
        with self.conn() as c:rows=c.execute(f"SELECT * FROM {self.trade_table} ORDER BY entry_time DESC LIMIT 200").fetchall()
        result=[self.row(r) for r in rows];previous={}
        for row in sorted(result,key=lambda x:(x['entry_time'],x['id'])):
            if row['partial_exit']:continue
            if row['mint'] in previous:row['previous_entry']=previous[row['mint']]
            previous[row['mint']]={k:row.get(k) for k in ('id','entry_time','entry_market_cap_usd','entry_cap_is_fdv')}
        return result
    def position_history(self,limit=200):
        # Select complete position groups before limiting; never lose earlier partial fills.
        with self.conn() as c:
            roots=c.execute(f"SELECT * FROM {self.trade_table} WHERE json_extract(COALESCE(context_json,'{{}}'),'$.partial_exit') IS NULL ORDER BY entry_time DESC,id DESC LIMIT ?",(max(1,min(200,limit)),)).fetchall()
            if not roots:return []
            ids=[r['id'] for r in roots]
            children=c.execute(f"SELECT * FROM {self.trade_table} WHERE json_extract(COALESCE(context_json,'{{}}'),'$.partial_exit.parent_trade_id') IN ({','.join('?' for _ in ids)})",ids).fetchall()
        groups={i:[] for i in ids}
        for r in children:
            child=self.row(r);groups[child['partial_exit']['parent_trade_id']].append(child)
        result=[];previous={}
        for raw in reversed(roots):
            root=self.row(raw);legs=groups[root['id']]+[root]
            amount=sum(float(x['amount_sol']) for x in legs)
            realized=sum(float(x['pnl_sol'] or 0) for x in legs if x['status']=='closed')
            fields=('id','amount_sol','exit_time','exit_market_cap_usd','exit_cap_is_fdv','pnl_sol','pnl_pct','exit_reason','exit_decision','execution_audit')
            fills=[dict({k:x.get(k) for k in fields},fraction_of_remainder=(x.get('partial_exit') or {}).get('fraction',1),kind='partial sale' if x.get('partial_exit') else 'final exit') for x in legs if x['status']=='closed']
            fills.sort(key=lambda x:(x['exit_time'],x['id']))
            sold=sum(float(x['amount_sol']) for x in fills)
            caps_valid=bool(fills) and all(valid_cap(x['exit_market_cap_usd']) for x in fills) and len({bool(x['exit_cap_is_fdv']) for x in fills})==1
            average_cap=sum(float(x['exit_market_cap_usd'])*float(x['amount_sol']) for x in fills)/sold if sold and caps_valid else None
            root['position_history']={'original_amount_sol':amount,'remaining_amount_sol':float(root['amount_sol']) if root['status']=='open' else 0,'remaining_pct':100*float(root['amount_sol'])/amount if amount and root['status']=='open' else 0,'remaining_token_quantity':(root['context'].get('paper_fill') or {}).get('quantity') if root['status']=='open' else 0,'realized_net_pnl_sol':realized,'return_pct':100*realized/amount if amount and root['status']=='closed' else None,'complete':root['status']=='closed','buys':[{'time':root['entry_time'],'amount_sol':amount,'market_cap_usd':root.get('entry_market_cap_usd'),'cap_is_fdv':bool(root.get('entry_cap_is_fdv')),'team':root.get('entry_team'),'method':root.get('entry_method')}],'average_entry_market_cap_usd':root.get('entry_market_cap_usd'),'average_entry_cap_is_fdv':bool(root.get('entry_cap_is_fdv')),'average_sell_market_cap_usd':average_cap,'average_sell_cap_is_fdv':bool(fills[0]['exit_cap_is_fdv']) if caps_valid else None,'fills':fills}
            if root['mint'] in previous:root['previous_entry']=previous[root['mint']]
            previous[root['mint']]={k:root.get(k) for k in ('id','entry_time','entry_market_cap_usd','entry_cap_is_fdv')}
            result.append({k:v for k,v in root.items() if k!='context'})
        return result[::-1]

    def save_execution_audit(self,i,audit):
        with self.conn() as c:
            r=c.execute(f'SELECT context_json FROM {self.trade_table} WHERE id=? AND status="open"',(i,)).fetchone()
            if not r:return False
            context=json.loads(r['context_json'] or '{}');context['execution_audit']=audit
            c.execute(f'UPDATE {self.trade_table} SET context_json=? WHERE id=?',(json.dumps(context),i))
        return True

    def mark_peak(self,i,price):
        with self.conn() as c:c.execute(f'UPDATE {self.trade_table} SET peak_price_usd=MAX(COALESCE(peak_price_usd,entry_price_usd),?) WHERE id=? AND status="open"',(price,i))
    def daily_realized(self,now=None):
        now=time.time() if now is None else now
        start=datetime.fromtimestamp(now,timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        with self.conn() as c:r=c.execute(f'SELECT COALESCE(SUM(pnl_sol),0) p FROM {self.trade_table} WHERE exit_time>=? AND exit_time<=? AND status="closed"',(start,now)).fetchone()
        return float(r['p'])
    def paper_metrics(self):
        with self.conn() as c:
            rows=c.execute(f'SELECT pnl_sol,context_json FROM {self.trade_table} WHERE status="closed"').fetchall()
        pnl=[float(r['pnl_sol'] or 0) for r in rows];n=len(pnl)
        fills=sum(bool(json.loads(r['context_json'] or '{}').get('paper_fill')) for r in rows)
        from intelligence.trade_evaluation import positions,metrics
        position_metrics=metrics(positions(self.trade_table))
        return {'position_metrics':position_metrics,'fill_win_rate_pct':round(100*sum(x>0 for x in pnl)/n,1) if n else None,'closed_trades':n,'cost_model_trades':fills,'legacy_trades':n-fills,'win_rate_pct':position_metrics['win_rate_pct'],'net_pnl_sol':sum(pnl),'daily_realized_sol':self.daily_realized(),'daily_window':'UTC calendar day','scope':'Simulated fills; not executable profit.'}
    def realized(self):
        with self.conn() as c:r=c.execute(f"SELECT COALESCE(SUM(pnl_sol),0) p FROM {self.trade_table} WHERE status='closed'").fetchone()
        return float(r["p"] or 0)
    def ensure_observations(self):
        with self.conn() as c:
            c.execute('CREATE TABLE IF NOT EXISTS watched(mint TEXT PRIMARY KEY, first_seen REAL, last_seen REAL, observations INTEGER, creation_time REAL, latest_json TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY AUTOINCREMENT, mint TEXT, observed_at REAL, payload_json TEXT)')
    def record_launch(self, token):
        now=time.time()
        payload={"token":token,"status":"awaiting_data","observed_at":now}
        with self.conn() as c:
            c.execute('INSERT OR IGNORE INTO watched VALUES(?,?,?,?,?,?)', (token['mint'],now,now,0,token['created_at'],json.dumps(payload)))
            c.execute('UPDATE watched SET creation_time=COALESCE(creation_time,?) WHERE mint=?', (token['created_at'],token['mint']))
            self._prune(c)
    def record_observation(self, payload):
        now=time.time(); token=payload['token']; payload=dict(payload,observed_at=now)
        raw=json.dumps(payload)
        with self.conn() as c:
            c.execute('INSERT INTO watched VALUES(?,?,?,?,?,?) ON CONFLICT(mint) DO UPDATE SET last_seen=excluded.last_seen, observations=watched.observations+1, latest_json=excluded.latest_json', (token['mint'],now,now,1,token.get('created_at'),raw))
            c.execute('INSERT INTO observations(mint,observed_at,payload_json) VALUES(?,?,?)',(token['mint'],now,raw))
            self._prune(c)
    def _prune(self,c):
        c.execute('DELETE FROM watched WHERE mint NOT IN (SELECT mint FROM watched ORDER BY last_seen DESC LIMIT 2000)')
        c.execute('DELETE FROM observations WHERE id NOT IN (SELECT id FROM observations ORDER BY id DESC LIMIT 5000)')
    def watch_history(self, limit=200, mint=None):
        with self.conn() as c:
            if mint:
                rows=c.execute('SELECT payload_json FROM observations WHERE mint=? ORDER BY id DESC LIMIT ?', (mint,limit)).fetchall()
                return [json.loads(r['payload_json']) for r in rows]
            rows=c.execute('SELECT * FROM watched ORDER BY last_seen DESC LIMIT ?', (limit,)).fetchall()
        return [dict(json.loads(r['latest_json']), first_seen=r['first_seen'], last_seen=r['last_seen'], observations=r['observations']) for r in rows]
    def new_pairs(self):
        with self.conn() as c:
            rows=c.execute('SELECT * FROM watched WHERE creation_time>? ORDER BY creation_time DESC LIMIT 100', (time.time()-3600,)).fetchall()
        return [dict(json.loads(r['latest_json']), created_at=r['creation_time']) for r in rows]
    def watched_mints(self, limit=10, offset=0):
        with self.conn() as c:
            rows=c.execute('SELECT mint FROM watched WHERE observations>0 ORDER BY last_seen ASC').fetchall()
        return [rows[(offset+i)%len(rows)]['mint'] for i in range(min(limit,len(rows)))]
store=Store()
store.ensure_observations()
