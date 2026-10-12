"""Cached, attributed launch evidence from Is It Bundled's public v1 API."""
import asyncio
import json
import logging
import time

import httpx

from database.store import store
from database.research import finite
from data.tracked_wallets import valid_address

BASE = 'https://isitbundled.com'
STATUS = {'status': 'starting', 'source': 'Is It Bundled?', 'key_required': False}
VALID_STATUSES = {'proxima', 'sumo', 'proxima_after_launch', 'bundled', 'no_bundle', 'unscanned'}
PERCENT_FIELDS = ('bundledPct', 'creatorBundlePct', 'otherBundlesPct', 'firstSecondPct',
                  'devBoughtPct', 'insidersHoldPct', 'flaggedHoldPct')
COUNT_FIELDS = ('bundleWallets', 'devLaunches7d', 'devBundled7d', 'fundedTogether',
                'throwawayFunded', 'wokenWallets')


def ensure():
    with store.conn() as c:
        c.execute('CREATE TABLE IF NOT EXISTS bundle_checks(mint TEXT PRIMARY KEY,checked_at REAL,payload_json TEXT)')


def normalize(data, mint):
    if not isinstance(data, dict) or data.get('mint') != mint or data.get('status') not in VALID_STATUSES:
        raise ValueError('Invalid bundle report')
    result = {'status': data['status'], 'source': 'Is It Bundled?', 'report': BASE + '/' + mint,
              'scope': 'Provider launch analysis; not proof of fraud or current sellability. Missing fields remain unknown.'}
    for key in PERCENT_FIELDS:
        n = finite(data.get(key)) if not isinstance(data.get(key), bool) else None
        result[key] = n if n is not None and 0 <= n <= 100 else None
    for key in COUNT_FIELDS:
        n = finite(data.get(key)) if not isinstance(data.get(key), bool) else None
        result[key] = int(n) if n is not None and n >= 0 and n.is_integer() else None
    for key in ('estimate', 'madeWithProxima', 'proximaAfterLaunch', 'madeWithSumo', 'madeWithUxento'):
        result[key] = data.get(key) if isinstance(data.get(key), bool) else None
    result['risk'] = data.get('risk') if data.get('risk') in {'low', 'medium', 'high', 'extreme'} else None
    report_at = finite(data.get('reportAt'))
    result['reportAt'] = report_at if report_at and report_at > 0 else None
    if result['status'] == 'unscanned':
        for key in PERCENT_FIELDS + COUNT_FIELDS + ('risk', 'reportAt', 'estimate', 'madeWithProxima', 'proximaAfterLaunch', 'madeWithSumo', 'madeWithUxento'):
            result[key] = None
    return result


def save(mint, payload):
    ensure()
    with store.conn() as c:
        c.execute('INSERT INTO bundle_checks VALUES(?,?,?) ON CONFLICT(mint) DO UPDATE SET checked_at=excluded.checked_at,payload_json=excluded.payload_json',
                  (mint, time.time(), json.dumps(payload)))
        c.execute('DELETE FROM bundle_checks WHERE mint NOT IN (SELECT mint FROM bundle_checks ORDER BY checked_at DESC LIMIT 2000)')


def cached(mint):
    ensure()
    with store.conn() as c:
        row = c.execute('SELECT * FROM bundle_checks WHERE mint=?', (mint,)).fetchone()
    if not row:
        return {'status': 'pending', 'source': 'Is It Bundled?', 'report': BASE + '/' + mint}
    result = dict(json.loads(row['payload_json']), checked_at=row['checked_at'])
    if time.time() - row['checked_at'] > 600:
        result.update(status='stale', previous_status=result['status'])
    # Current holdings age is the provider's report time, not our fetch time.
    report_at = result.get('reportAt')
    result['holdings_fresh'] = bool(report_at and 0 <= time.time() - report_at <= 600 and result['status'] not in {'stale', 'unavailable', 'unscanned'})
    if not result['holdings_fresh']:
        result['insidersHoldPct'] = result['flaggedHoldPct'] = result['risk'] = None
    return result


def evidence_flags(report):
    # Launch bundling and current linked holdings are different propositions.
    if report.get('status') not in VALID_STATUSES-{'unscanned'}:return []
    flags=[]
    if report.get('madeWithProxima') is True or report.get('proximaAfterLaunch') is True:
        flags.append({'name':'Provider Proxima launch-tool classification','description':'Launch-tool evidence, not proof of fraud or common ownership.','source':'Is It Bundled?'})
    if report.get('holdings_fresh'):
        values=[report.get(k) for k in ('insidersHoldPct','flaggedHoldPct')]
        values=[v for v in values if isinstance(v,(int,float)) and not isinstance(v,bool) and 0<=v<=100]
        if values and max(values)>=50:
            flags.append({'name':'Provider flagged holding concentration','description':'Provider reports at least 50% flagged/insider holdings. A no_bundle launch result does not clear current concentration. Categories may overlap; do not add them or assume verified common ownership.','maximum_reported_pct':max(values),'source':'Is It Bundled?'})
    return flags

def features(report):
    available = report.get('status') in VALID_STATUSES - {'unscanned'}
    pct = report.get('bundledPct') if available else None
    group = 'unknown' if pct is None else 'under_5' if pct < 5 else '5_to_20' if pct < 20 else '20_plus'
    return {'launch_bundle_group': group, 'bundle_provider_status': report.get('status', 'pending'),
            'bundle_estimate': 'yes' if report.get('estimate') is True else 'no' if report.get('estimate') is False and available else 'unknown',
            'bundle_current_risk': report.get('risk') or 'unknown','current_flagged_majority':any(x['name']=='Provider flagged holding concentration' for x in evidence_flags(report))}


async def check_batch(mints):
    mints = list(dict.fromkeys(m for m in mints if valid_address(m)))[:100]
    if not mints:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(BASE + '/api/v1/tokens', json={'mints': mints})
            response.raise_for_status()
            rows = response.json().get('tokens')
            if not isinstance(rows, list) or len(rows) != len(mints):
                raise ValueError('Incomplete batch')
            # Validate all identities before persisting; never attach one mint's data to another.
            reports = [normalize(row, mint) for row, mint in zip(rows, mints)]
        for mint, report in zip(mints, reports):
            save(mint, report)
        STATUS.update(status='active', checked_at=time.time(), tokens_checked=len(mints))
        logging.getLogger('uvicorn.error').info('NEXUS bundle reports received: %s tokens', len(mints))
    except Exception as exc:
        code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        reason = 'http_' + str(code) if code else type(exc).__name__
        # Replace old positive/negative conclusions with unavailable, not "no bundle".
        for mint in mints:
            save(mint, {'status': 'unavailable', 'source': 'Is It Bundled?', 'failure_type': reason, 'report': BASE + '/' + mint})
        STATUS.update(status='unavailable', last_failure_type=reason, checked_at=time.time())
        logging.getLogger('uvicorn.error').warning('NEXUS bundle reports unavailable: %s', reason)


async def bundle_loop():
    while True:
        try:
            from paper.shadow import BOOK
            positions = store.open() + BOOK.open()
            watched = store.watch_history(limit=100)
            # Open positions first; one batch/30s, refresh findings/5m, unknowns/1m.
            mints = [p['mint'] for p in positions] + [x['token']['mint'] for x in watched if time.time() - x.get('last_seen', 0) < 600]
            due = []
            for mint in dict.fromkeys(mints):
                report = cached(mint)
                ttl = 60 if report['status'] in {'pending', 'unscanned', 'unavailable'} else 300
                if time.time() - report.get('checked_at', 0) > ttl:
                    due.append(mint)
            await check_batch(due)
        except Exception as exc:
            STATUS.update(status='unavailable', last_failure_type=type(exc).__name__)
            logging.getLogger('uvicorn.error').warning('NEXUS bundle loop failure: %s', type(exc).__name__)
        await asyncio.sleep(30)
