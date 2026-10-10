"""Conservative reputation from matched SOL-quoted swaps, never a lifetime PnL claim."""
from collections import defaultdict
from decimal import Decimal
import math
WSOL='So11111111111111111111111111111111111111112'

def normalize_transaction(item,address):
    signature=item.get('signature')
    tx=item.get('parsed') or {}
    if not signature or item.get('parserStatus')!='OK' or tx.get('transactionStatus')!='OK' or not tx.get('blockTime'):
        return None
    touched=list({t.get('mint') for t in tx.get('tokenTransfers',[]) if t.get('mint') and address in (t.get('toUserAccount'),t.get('fromUserAccount'))})
    invalid={'signature':signature,'timestamp':tx['blockTime'],'slot':tx.get('slot',0),'kind':'invalidate','mints':touched}
    deltas=defaultdict(Decimal)
    try:
        for t in tx.get('tokenTransfers',[]):
            if address not in (t.get('toUserAccount'),t.get('fromUserAccount')):continue
            amount=Decimal(str(t['rawTokenAmount']))/(Decimal(10)**int(t['decimals']))
            if int(t['rawTokenAmount'])>2**53-1 or amount<0:return invalid
            if t.get('toUserAccount')==address:deltas[t['mint']]+=amount
            if t.get('fromUserAccount')==address:deltas[t['mint']]-=amount
        deltas={mint:amount for mint,amount in deltas.items() if amount}
        tokens={m:q for m,q in deltas.items() if m!=WSOL}
        if not tokens:return None
        event={'signature':signature,'timestamp':tx['blockTime'],'slot':tx.get('slot',0),'kind':'invalidate','mints':list(tokens)}
        summary=tx.get('summary') or {}
        if summary.get('type')!='swap' or len(tokens)!=1:return event
        native=Decimal(0)
        for transfer in tx.get('nativeTransfers',[]):
            amount=Decimal(str(transfer['amount']))/Decimal(10**9)
            if transfer.get('toUserAccount')==address:native+=amount
            if transfer.get('fromUserAccount')==address:native-=amount
        wrapped=deltas.get(WSOL,Decimal(0))
        # Do not double-count SOL wrapping or assign ambiguous quote flows a cost.
        if native and wrapped:return event
        quote=native or wrapped
        mint,quantity=next(iter(tokens.items()))
        if not quote or quote*quantity>=0:return event
        fee=Decimal(str(tx.get('fee') or 0))/Decimal(10**9) if tx.get('feePayer')==address else Decimal(0)
        cash=abs(quote)+fee if quantity>0 else abs(quote)-fee
        if cash<=0:return event
        event.update(kind='buy' if quantity>0 else 'sell',mint=mint,quantity=str(abs(quantity)),sol=str(cash))
        return event
    except (KeyError,ValueError,TypeError,ArithmeticError):return invalid if touched else None

def evaluate_evidence(events,min_samples=10):
    books={};results=[];excluded=0
    for e in events:
        if e['kind']=='invalidate':
            for m in e['mints']:books.pop(m,None)
            excluded+=1;continue
        mint=e['mint'];quantity=Decimal(e['quantity']);sol=Decimal(e['sol'])
        qty,cost=books.get(mint,(Decimal(0),Decimal(0)))
        if e['kind']=='buy':books[mint]=(qty+quantity,cost+sol);continue
        if quantity>qty or qty<=0:
            books.pop(mint,None);excluded+=1;continue
        basis=cost*quantity/qty;profit=sol-basis
        results.append((mint,float(profit),float(basis)))
        books[mint]=(qty-quantity,cost-basis)
    n=len(results);wins=sum(p>0 for m,p,b in results);total=sum(p for m,p,b in results);basis=sum(b for m,p,b in results)
    win_rate=wins/n if n else 0;roi=total/basis*100 if basis else None;tokens=len({m for m,p,b in results})
    # Wilson lower bound downweights lucky streaks with little evidence.
    z=1.96
    lower=(win_rate+z*z/(2*n)-z*math.sqrt((win_rate*(1-win_rate)+z*z/(4*n))/n))/(1+z*z/n) if n else 0
    score=round(100*(.6*lower+.2*min(max((roi or 0)/100,0),1)+.2*min(n/30,1)),1)
    qualified=n>=min_samples and tokens>=3 and total>0 and win_rate>=.6 and (roi or 0)>=10
    return {'data_status':'ok','matched_sells':n,'distinct_tokens':tokens,'win_rate_pct':round(win_rate*100,1) if n else None,'estimated_pnl_sol':round(total,6) if n else None,'roi_pct':round(roi,1) if roi is not None else None,'score':score,'qualified':qualified,'excluded_events':excluded,'scope':'Matched observed SOL swaps only; partial history, not lifetime PnL'}
