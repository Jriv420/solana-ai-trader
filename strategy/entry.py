from config.settings import settings
def should_enter(t,fast,wallet,social,risk):
    c=fast*.45+wallet*.25+social*.10+(100-risk)*.20; r=[]
    if c<settings.min_combined_score:r.append("combined score below threshold")
    if wallet<settings.min_wallet_score:r.append("wallet score below threshold")
    if risk>settings.max_risk_score:r.append("risk score above threshold")
    return {"enter":not r,"combined_score":round(c,1),"reasons":r}
