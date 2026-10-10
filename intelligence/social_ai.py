def score_social_context(s):
    if s.get('status')!='ok':return {'score':40,'status':s.get('status','unknown'),'reason':'Live social evidence unavailable; no synthetic mentions.'}
    mentions=int(s.get('mentions_5m') or 0);unique=int(s.get('unique_accounts_5m') or 0);growth=s.get('mention_growth') or 0
    score=40+min(20,unique*2)+min(15,max(0,growth-1)*5)+min(10,len(s.get('known_influencers') or [])*5)
    return {'score':min(85,score),'status':'observed','mentions_5m':mentions,'unique_accounts_5m':unique,'known_influencers':s.get('known_influencers',[]),'sample_truncated':s.get('sample_truncated',False),'reason':'Sampled mint-specific breadth/growth and user-selected KOL mentions; mentions are not endorsements.'}
