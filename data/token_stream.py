"""Bounded Solana discovery, plus a separate real-time Pump.fun launch feed."""
import asyncio
import json
import time
from collections import OrderedDict
import httpx
import websockets
from config.settings import settings
from data.market_data import get_token_snapshot
from database.store import store

DISCOVERY_URLS = [
    'https://api.dexscreener.com/token-profiles/latest/v1',
    'https://api.dexscreener.com/token-boosts/latest/v1',
    'https://api.dexscreener.com/token-boosts/top/v1',
    'https://api.dexscreener.com/community-takeovers/latest/v1',
]
FEED = {'status': 'connecting', 'last_event': None, 'error': None}
_recent = OrderedDict()
_discovery_cache = []
_discovery_updated = 0
_cursor = 0
_new_cursor = 0

def remember_launch(event):
    mint = event.get('mint')
    if not mint or event.get('txType') != 'create':
        return
    if mint in _recent:
        return
    now = time.time()
    token = {'mint': mint, 'symbol': event.get('symbol') or mint[:6],
             'name': event.get('name') or 'Unknown', 'created_at': now,
             'creation_time_source': 'pumpportal_event_received',
             'source': 'pumpportal', 'discovery_source': 'pumpportal-new-token',
             'market_data_status': 'awaiting_indexing'}
    _recent[mint] = token
    while len(_recent) > 1000:
        _recent.popitem(last=False)
    store.record_launch(token)
    FEED.update(last_event=now, error=None)

async def stream_new_tokens():
    """One free creation subscription; no paid trade subscriptions."""
    delay = 2
    while True:
        try:
            async with websockets.connect('wss://pumpportal.fun/api/data',
                                          open_timeout=15, ping_interval=20) as ws:
                await ws.send(json.dumps({'method': 'subscribeNewToken'}))
                FEED.update(status='connected', error=None)
                delay = 2
                async for message in ws:
                    try:
                        event = json.loads(message)
                        if isinstance(event, dict):
                            remember_launch(event)
                    except (ValueError, TypeError):
                        continue
        except Exception as exc:
            FEED.update(status='reconnecting', error=type(exc).__name__)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

async def discover_tokens():
    global _discovery_cache, _discovery_updated
    if time.time() - _discovery_updated < 60:
        return _discovery_cache
    found = []
    async with httpx.AsyncClient(timeout=10) as client:
        for url in DISCOVERY_URLS:
            try:
                response = await client.get(url)
                response.raise_for_status()
                items = response.json()
                if isinstance(items, list):
                    found.extend(item['tokenAddress'] for item in items
                                 if isinstance(item, dict) and item.get('chainId') == 'solana'
                                 and item.get('tokenAddress'))
            except (httpx.HTTPError, ValueError):
                continue
    _discovery_updated = time.time()
    if found:
        _discovery_cache = list(dict.fromkeys(found))[:120]
    return _discovery_cache

async def scan_tokens():
    global _cursor, _new_cursor
    mints = await discover_tokens()
    selected = [mints[(_cursor + i) % len(mints)] for i in range(min(15, len(mints)))]
    _cursor += 15
    # Rotate launches too, so unindexed launches get another chance.
    recent = [m for m, t in _recent.items() if time.time() - t['created_at'] < 3600]
    if recent:
        selected += [recent[(_new_cursor + i) % len(recent)] for i in range(min(10, len(recent)))]
        _new_cursor += 10
    # Revisit watched coins and positions as well as fresh discoveries.
    selected += store.watched_mints(limit=10, offset=_cursor)
    selected += list(settings.watchlist_mints) + [p['mint'] for p in store.open()]
    semaphore = asyncio.Semaphore(5)
    async def fetch(mint):
        async with semaphore:
            try:
                token = await get_token_snapshot(mint)
                if token:
                    token['discovery_source'] = 'pumpportal-new-token' if mint in _recent else 'dexscreener'
                    if mint in _recent:
                        token['created_at'] = _recent[mint]['created_at']
                        token['creation_time_source'] = 'pumpportal_event_received'
                    return token
            except Exception:
                pass
            return None
    results = await asyncio.gather(*(fetch(m) for m in dict.fromkeys(selected)))
    return [t for t in results if t]
