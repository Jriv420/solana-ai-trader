"""Refresh one coin's tracked holdings per minute for scoring, not only when UI opens."""
import asyncio,time
from data.tracked_wallets import get_tracked_wallet_holders,valid_address
from database.wallet_registry import wallet_registry
from database.store import store
from config.settings import settings
_seen={}
async def wallet_signals_loop():
    while True:
        try:
            if settings.solana_rpc_url:
                items=[x['token'] for x in store.watch_history(limit=50) if time.time()-x.get('last_seen',0)<600 and valid_address(x['token'].get('mint',''))]
                items.sort(key=lambda t:_seen.get(t['mint'],0))
                if items:
                    token=items[0];mint=token['mint'];price=float(token.get('price_usd') or 0)
                    if price>0 and time.time()-_seen.get(mint,0)>60:
                        result=await get_tracked_wallet_holders(mint)
                        if result['status'] in {'ok','partial'}:
                            failed={w['address'] for w in result.get('unavailable_wallets',[])}
                            holders={w['address']:w for w in result.get('holders',[])}
                            from data.tracked_wallets import configured_wallets
                            for wallet in configured_wallets():
                                address=wallet['address']
                                if address not in failed:
                                    balance=holders.get(address,{}).get('balance','0')
                                    wallet_registry.position(address,mint,balance,float(balance)*price)
                        _seen[mint]=time.time()
                        if len(_seen)>2000:_seen.pop(min(_seen,key=_seen.get))
        except Exception:pass
        await asyncio.sleep(60)
