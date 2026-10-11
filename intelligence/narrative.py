"""Evidence-aware narrative context. A transfer is never an endorsement."""
from collections import defaultdict
from decimal import Decimal
from database.research import research
from intelligence.wallet_learning import normalize_transaction
from intelligence.market_regime import market_features
from database.store import store
from data.web_research import cached as web_context,safe_url


def record_transaction(item,address):
    tx=item.get('parsed') or {}
    if item.get('parserStatus')!='OK' or tx.get('transactionStatus')!='OK' or not tx.get('blockTime') or not item.get('signature'):return
    normalized=normalize_transaction(item,address)
    swap=(tx.get('summary') or {}).get('type')=='swap'
    quantities=defaultdict(Decimal);parties=defaultdict(set);raws=defaultdict(Decimal);approx={}
    for t in tx.get('tokenTransfers') or []:
        if address not in (t.get('toUserAccount'),t.get('fromUserAccount')):continue
        if t.get('toUserAccount')==t.get('fromUserAccount'):continue
        try:
            raw=Decimal(str(t['rawTokenAmount']));decimals=int(t['decimals']);mint=t['mint']
            if not raw.is_finite() or raw<=0 or not 0<=decimals<=18:continue
            incoming=t.get('toUserAccount')==address;sign=1 if incoming else -1
            quantities[mint]+=sign*raw/(Decimal(10)**decimals);raws[mint]+=sign*raw
            parties[mint].add(t.get('fromUserAccount') if incoming else t.get('toUserAccount'))
            approx[mint]=approx.get(mint,False) or raw>2**53-1
        except (KeyError,ValueError,TypeError,ArithmeticError):continue
    for mint,quantity in quantities.items():
        if not quantity:continue
        kind='unknown_swap' if swap else 'received_transfer' if quantity>0 else 'sent_transfer'
        if normalized and normalized.get('mint')==mint and normalized.get('kind') in {'buy','sell'}:kind=normalized['kind']
        research.event({'signature':item['signature'],'timestamp':tx['blockTime'],'slot':tx.get('slot'),'mint':mint,'wallet':address,'kind':kind,'quantity':str(abs(quantity)),'raw_quantity':str(abs(raws[mint])),'amount_approximate':approx[mint],'counterparties':sorted(p for p in parties[mint] if p),'source':'Helius parsed transaction'})



def context(mint,token=None):
    claims=research.claims(mint);events=research.events(mint);security=research.security(mint)
    # Latest review per wallet; other wallets' claims must not overwrite this one.
    latest={}
    for c in claims:latest.setdefault(c.get('wallet') or '',c)
    reviews=list(latest.values())
    speculative=any(c.get('endorsement')!='confirmed' or c.get('identity')!='verified' for c in reviews)
    received=any(e['kind']=='received_transfer' for e in events)
    bought=any(e['kind']=='buy' for e in events)
    supply=security.get('supply_raw')
    for e in events:
        e['received_supply_pct']=float(Decimal(e.get('raw_quantity','0'))/Decimal(str(supply))*100) if supply and e['kind']=='received_transfer' else None
    large=any((e.get('received_supply_pct') or 0)>=5 for e in events)

    slots=defaultdict(set)
    for e in events:
        if e['kind']=='buy' and e.get('slot'):slots[e['slot']].add(e['wallet'])
    clusters=[{'slot':slot,'wallets':sorted(wallets)} for slot,wallets in slots.items() if len(wallets)>=3]
    provider_flags=[r for r in security.get('risks',[]) if any(word in (r.get('name','')+' '+r.get('description','')).lower() for word in ('bundle','insider','linked wallet'))]
    if (security.get('graph_insiders_detected') or 0)>0:provider_flags.append({'name':'Provider insider graph indicator','description':'RugCheck reports potential insider links; identity and coordination remain unverified.'})
    bundle={'status':'indicators_found' if clusters or provider_flags else 'not_detected_in_sample' if events or security.get('status')=='ok' else 'unknown','same_slot_buyer_groups':clusters[:10],'provider_flags':provider_flags,'scope':'Partial wallet history and provider flags; coordinated timing is not proof of a Jito bundle or common ownership.'}
    features={'security_status':security.get('status','pending'),'identity_status':','.join(sorted({c.get('identity','unknown') for c in reviews})) or 'unknown','endorsement_status':','.join(sorted({c.get('endorsement','unknown') for c in reviews})) or 'unknown','narrative':'speculative' if speculative else 'reviewed_confirmed' if reviews else 'unknown','acquisition':'transfer_and_buy' if received and bought else 'received_transfer' if received else 'buy' if bought else 'unknown','large_received_transfer':large,'bundle_indicator':bool(clusters or provider_flags),'rug_danger':bool(security.get('danger'))}
    if token is None:
        observations=store.watch_history(mint=mint,limit=1)
        token=observations[0]['token'] if observations else None
    if token is not None:features.update(market_features(token,security),bundle_status=bundle['status'],branding_status=(token.get('identity_check') or {}).get('status','unknown'))
    web=web_context(mint)
    links=[dict(url=safe_url(x.get('url')),label=str(x.get('label') or x.get('type') or 'Project link')[:100]) for x in (token or {}).get('source_links',[]) if isinstance(x,dict) and safe_url(x.get('url'))]
    features['web_evidence_status']=web['status']
    learning=research.learning(features)
    outcomes_by_horizon={h:research.learning(features,h) for h in ('5m','1h','24h')}
    return {'web_research':dict(web,message='Untrusted search excerpts linked to this exact contract; not authenticated identity or endorsement. Indexed coverage is incomplete; timestamps are search time, not publication time.'),'project_links':links,'claims':reviews,'events':events[:30],'security':security,'bundle':bundle,'features':features,'learning':learning,'outcomes_by_horizon':outcomes_by_horizon,'message':'User-reviewed source claims, not automatically authenticated endorsements. Token receipts may be unsolicited gifts or other transfers.'}
