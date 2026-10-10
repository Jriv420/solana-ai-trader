"""Read-only tracked-wallet token balances, cached per mint for one minute."""
import asyncio
import json
import re
import time
from collections import OrderedDict
from decimal import Decimal
import httpx
from config.settings import settings

_BASE58 = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
_cache = OrderedDict()
_inflight = {}
_semaphore = asyncio.Semaphore(4)

def valid_address(value):
    if not isinstance(value,str) or not _BASE58.fullmatch(value):
        return False
    alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    number=0
    for char in value:number=number*58+alphabet.index(char)
    size=(number.bit_length()+7)//8+len(value)-len(value.lstrip('1'))
    return size==32

def configured_wallets():
    raw=settings.tracked_wallets_json.strip()
    if not raw:raw="[]"
    items=json.loads(raw)
    if not isinstance(items,list) or len(items)>50:
        raise ValueError('TRACKED_WALLETS must be a JSON list of up to 50 wallets')
    wallets=[]; seen=set()
    for item in items:
        address=item if isinstance(item,str) else item.get('address') if isinstance(item,dict) else None
        if not valid_address(address):raise ValueError('Invalid tracked-wallet address')
        if address in seen:continue
        seen.add(address)
        label=item.get('label') if isinstance(item,dict) else None
        wallets.append({'address':address,'label':str(label or address[:6]+'…'+address[-4:])[:100]})
    from database.wallet_registry import wallet_registry
    registry=wallet_registry.tracking_wallets()
    manual=[w for w in registry if 'Manual' in w.get('tags',[])]
    disabled={w['address'] for w in wallet_registry.list() if w['disabled']}
    combined={w['address']:w for w in wallets if w['address'] not in disabled}
    for w in manual:combined[w['address']]=w
    if len(combined)>50:raise ValueError('Too many manually tracked wallets')
    for w in registry:
        if w['address'] not in combined and len(combined)<50:combined[w['address']]=w
    return list(combined.values())

async def _load(mint,wallets):
    async with httpx.AsyncClient(timeout=10) as client:
        async def fetch(wallet):
            async with _semaphore:
                try:
                    response=await client.post(settings.solana_rpc_url,json={
                        'jsonrpc':'2.0','id':1,'method':'getTokenAccountsByOwner',
                        'params':[wallet['address'],{'mint':mint},{'encoding':'jsonParsed','commitment':'confirmed'}]})
                    response.raise_for_status()
                    payload=response.json()
                    if payload.get('error'):raise ValueError('RPC request failed')
                    accounts=payload['result']['value']
                    balance=Decimal(0)
                    if not isinstance(accounts,list):raise ValueError('Invalid RPC response')
                    for account in accounts:
                        info=account['account']['data']['parsed']['info']
                        if info['mint']!=mint or info['owner']!=wallet['address']:
                            raise ValueError('Unexpected token account')
                        amount=info['tokenAmount']
                        balance+=Decimal(amount['amount'])/(Decimal(10)**int(amount['decimals']))
                    return dict(wallet,balance=format(balance,'f'),checked_at=time.time()),None
                except (httpx.HTTPError,ValueError,KeyError,TypeError,ArithmeticError):
                    return None,dict(wallet,reason='Balance check unavailable')
        results=await asyncio.gather(*(fetch(w) for w in wallets))
    holdings=[holder for holder,error in results if holder and Decimal(holder['balance'])>0]
    holdings.sort(key=lambda h:Decimal(h['balance']),reverse=True)
    failures=[error for holder,error in results if error]
    result={'status':'unavailable' if len(failures)==len(wallets) else 'partial' if failures else 'ok',
            'holders':holdings,'configured_count':len(wallets),'checked_count':len(wallets)-len(failures),
            'unavailable_wallets':failures,'checked_at':time.time(),'source':'Solana RPC · confirmed'}
    result['wallet_fingerprint']=tuple((w['address'],w['label']) for w in wallets)
    _cache[mint]=(time.monotonic(),result)
    _cache.move_to_end(mint)
    while len(_cache)>500:_cache.popitem(last=False)
    return result

async def get_tracked_wallet_holders(mint):
    if not valid_address(mint):raise ValueError('Invalid mint address')
    try:wallets=configured_wallets()
    except (ValueError,TypeError):return {'status':'invalid_configuration','holders':[],'message':'Tracked-wallet configuration needs correction.'}
    if not wallets:return {'status':'not_configured','holders':[],'configured_count':0,'message':'No tracked wallets configured.'}
    if not settings.solana_rpc_url:return {'status':'rpc_not_configured','holders':[],'configured_count':len(wallets),'message':'A Solana RPC connection is required to check balances.'}
    cached=_cache.get(mint)
    fingerprint=tuple((w['address'],w['label']) for w in wallets)
    if cached and cached[1].get('wallet_fingerprint')!=fingerprint:cached=None
    if cached and time.monotonic()-cached[0]<60:return cached[1]
    if mint not in _inflight:_inflight[mint]=asyncio.create_task(_load(mint,wallets))
    task=_inflight[mint]
    try:return await asyncio.shield(task)
    finally:
        if task.done():_inflight.pop(mint,None)
