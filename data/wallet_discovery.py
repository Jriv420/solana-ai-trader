"""Find large holders of scanned coins, exclude program owners, and refresh evidence."""
import asyncio
import time
from decimal import Decimal
import httpx
from config.settings import settings
from database.store import store
from database.wallet_registry import wallet_registry
from data.tracked_wallets import valid_address
from intelligence.wallet_learning import normalize_transaction,evaluate_evidence
SYSTEM='11111111111111111111111111111111'
STATUS={'discovery':'starting','learning':'starting','last_discovery':None,'last_learning':None}
_seen={}

async def rpc(client,method,params):
    response=await client.post(settings.solana_rpc_url,json={'jsonrpc':'2.0','id':1,'method':method,'params':params})
    response.raise_for_status();data=response.json()
    if data.get('error'):raise ValueError('RPC request failed')
    return data['result']

async def discover_holders(token):
    mint=token['mint'];price=float(token.get('price_usd') or 0)
    if not valid_address(mint) or price<=0:return
    async with httpx.AsyncClient(timeout=15) as client:
        accounts=(await rpc(client,'getTokenLargestAccounts',[mint,{'commitment':'confirmed'}]))['value']
        addresses=[x['address'] for x in accounts][:20]
        if not addresses:return
        details=(await rpc(client,'getMultipleAccounts',[addresses,{'encoding':'jsonParsed','commitment':'confirmed'}]))['value']
        balances={}
        for data in details:
            try:
                info=data['data']['parsed']['info']
                owner=info['owner'];amount=info['tokenAmount']
                if info['mint']!=mint or not valid_address(owner):continue
                balances[owner]=balances.get(owner,Decimal(0))+Decimal(amount['amount'])/(Decimal(10)**int(amount['decimals']))
            except (KeyError,TypeError,ArithmeticError):continue
        owners=list(balances)
        if not owners:return
        owner_details=(await rpc(client,'getMultipleAccounts',[owners,{'encoding':'base64','commitment':'confirmed'}]))['value']
        for owner,data in zip(owners,owner_details):
            # Liquidity pools, bonding curves, and other program-owned accounts are excluded.
            if not data or data.get('owner')!=SYSTEM or data.get('executable'):continue
            wallet_registry.add(owner)
            wallet_registry.position(owner,mint,balances[owner],float(balances[owner])*price)
    _seen[mint]=time.time()
    if len(_seen)>2000:_seen.pop(min(_seen,key=_seen.get))

async def learn_wallet(address):
    known=wallet_registry.events(address);signatures={e['signature'] for e in known};collected=[];cursor=None;overlap=False;parser_error=False
    async with httpx.AsyncClient(timeout=20) as client:
        for _ in range(2):
            body={'address':address,'limit':100,'sortOrder':'desc','commitment':'confirmed'}
            if cursor:body['paginationToken']=cursor
            response=await client.post('https://mainnet.helius-rpc.com/v1/parsed-events/transaction-history',params={'api-key':settings.helius_api_key},json=body)
            response.raise_for_status();data=response.json()
            items=data['data']
            for item in items:
                if item.get('signature') in signatures:overlap=True
                if item.get('parserStatus')!='OK':parser_error=True
                event=normalize_transaction(item,address)
                if event:collected.append(event)
            cursor=data.get('paginationToken')
            if overlap or not cursor:break
    # A missing window or an unparsed transaction can hide transfers and cost basis.
    # Reset evidence instead of crediting profitable sells against stale inventory.
    gap=bool(known and not overlap and cursor)
    wallet_registry.evidence(address,list(reversed(collected)),reset=gap or parser_error)
    profile=evaluate_evidence(wallet_registry.events(address),settings.wallet_min_matched_sells)
    profile.update(coverage_gap=gap,parser_errors=parser_error,history_truncated=bool(cursor and not overlap))
    if parser_error:profile.update(data_status='incomplete',qualified=False)
    wallet_registry.profile(address,profile)

async def wallet_learning_loop():
    while True:
        try:
            if settings.solana_rpc_url:
                items=store.watch_history(limit=100)
                for item in items:
                    token=item['token'];mint=token['mint']
                    if time.time()-_seen.get(mint,0)>300 and time.time()-(token.get('timestamp') or 0)<600:
                        await discover_holders(token)
                        STATUS.update(discovery='active',last_discovery=time.time())
                        break
            else:STATUS['discovery']='RPC not configured'
        except Exception:STATUS['discovery']='Discovery data unavailable'
        try:
            if settings.helius_api_key:
                for address in wallet_registry.candidates():
                    try:
                        await learn_wallet(address);STATUS.update(learning='active',last_learning=time.time())
                    except Exception:
                        previous=next((x['profile'] for x in wallet_registry.list() if x['address']==address),{})
                        wallet_registry.profile(address,dict(previous,data_status='unavailable',qualified=False))
                        STATUS['learning']='History unavailable'
            else:STATUS['learning']='Helius history connection not configured'
        except Exception:STATUS['learning']='History unavailable'
        await asyncio.sleep(30)
