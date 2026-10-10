"""Flag ambiguous branding among observed contracts, without declaring an original."""
import unicodedata

def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKC',str(value or '')).casefold() if c.isalnum())

def identity_key(token):
    name,symbol=normalized(token.get('name')),normalized(token.get('symbol'))
    if name in ('','unknown') or not symbol:return None
    return name,symbol

def annotate(tokens,known):
    groups={}
    for token in [*known,*tokens]:
        key=identity_key(token);mint=token.get('mint')
        if key and mint:groups.setdefault(key,set()).add(mint)
    result=[];seen=set()
    for token in tokens:
        mint=token.get('mint')
        if mint in seen:continue
        seen.add(mint)
        matches=sorted(groups.get(identity_key(token),set())-{mint})
        result.append(dict(token,identity_check={'status':'ambiguous' if matches else 'no_match_observed',
            'matching_contracts':matches[:20],'matching_count':len(matches),
            'message':'Same name and ticker observed on different contracts; original unverified.' if matches else 'No matching name and ticker in observed tokens; authenticity not verified.'}))
    return result
