from config.settings import settings,trading_settings
def should_enter(t,fast,wallet,social,risk):
    rules=trading_settings(settings)
    c=fast*.45+wallet*.25+social*.10+(100-risk)*.20; r=[]
    if c<rules.min_combined_score:r.append("combined score below threshold")
    if wallet<rules.min_wallet_score:r.append("wallet score below threshold")
    if risk>rules.max_risk_score:r.append("risk score above threshold")
    return {"enter":not r,"combined_score":round(c,1),"reasons":r}
