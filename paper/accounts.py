"""Persistent independent paper-entry controls; exits are never paused."""
import logging,time
from database.store import store
BOOKS={'original':'trades','aggressive':'shadow_trades'}
def ensure():
    with store.conn() as c:
        c.execute('CREATE TABLE IF NOT EXISTS paper_account_controls(account TEXT PRIMARY KEY,enabled INTEGER NOT NULL,updated_at REAL NOT NULL)')
        for account in BOOKS:c.execute('INSERT OR IGNORE INTO paper_account_controls VALUES(?,1,?)',(account,time.time()))
def summary():
    ensure()
    with store.conn() as c:rows=c.execute('SELECT * FROM paper_account_controls').fetchall()
    return {r['account']:{'entries_enabled':bool(r['enabled']),'updated_at':r['updated_at'],'scope':'Stop pauses new buys. Open positions keep AI and protective exits. Shared learning continues.'} for r in rows}
def enabled(book):
    account=next((a for a,b in BOOKS.items() if b==book),None)
    if account is None:raise ValueError('Invalid paper account')
    return summary()[account]['entries_enabled']
def set_enabled(account,value):
    if account not in BOOKS or type(value) is not bool:raise ValueError('Invalid account control')
    ensure()
    with store.conn() as c:c.execute('UPDATE paper_account_controls SET enabled=?,updated_at=? WHERE account=?',(int(value),time.time(),account))
    logging.getLogger('uvicorn.error').info('NEXUS paper account control account=%s entries_enabled=%s exits_continue=True',account,value)
    return summary()
