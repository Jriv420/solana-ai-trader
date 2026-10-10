def score_social_context(s):
    o=float(s.get("organic_score",50)); m=int(s.get("mentions_5m",0)); u=int(s.get("unique_accounts_5m",0))
    b=min(u/max(m,1)*100,100) if m else 50
    return {"score":round(max(0,min(100,o*.7+b*.3)),1),"reason":"organic quality + breadth"}
