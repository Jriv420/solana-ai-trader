def score_wallet_context(token,wallet_profile=None,overlap_count=0):
    p=wallet_profile or {}; win=float(p.get("win_rate",0)); pnl=float(p.get("realized_pnl",0))
    score=40+min(win,80)*.35+min(max(pnl,0),25)*.8+min(overlap_count*5,15)
    return {"score":round(max(0,min(100,score)),1),"reason":"wallet history + overlap"}
