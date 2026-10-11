from dataclasses import dataclass
import os
from urllib.parse import quote
from dotenv import load_dotenv
load_dotenv()

def _b(n,d):
    v=os.getenv(n)
    return d if v is None else v.strip().lower() in {"1","true","yes","on"}
def _f(n,d):
    try:return float(os.getenv(n,d))
    except:return d
def _i(n,d):
    try:return int(os.getenv(n,d))
    except:return d

@dataclass(frozen=True)
class Settings:
    paper_mode: bool=_b("PAPER_MODE",True)
    live_trading_enabled: bool=_b("LIVE_TRADING_ENABLED",False)
    app_host: str=os.getenv("APP_HOST","127.0.0.1")
    app_port: int=_i("APP_PORT",8000)
    scan_interval_seconds: int=_i("SCAN_INTERVAL_SECONDS",10)
    watchlist_mints: tuple=tuple(x.strip() for x in os.getenv("WATCHLIST_MINTS","").split(",") if x.strip())
    helius_api_key: str=os.getenv("HELIUS_API_KEY","")
    solana_rpc_url: str=os.getenv("SOLANA_RPC_URL","") or ("https://mainnet.helius-rpc.com/?api-key="+quote(os.getenv("HELIUS_API_KEY",""),safe='') if os.getenv("HELIUS_API_KEY") else "")
    whale_portfolio_usd: float=_f("WHALE_PORTFOLIO_USD",100000)
    whale_position_usd: float=_f("WHALE_POSITION_USD",25000)
    wallet_min_matched_sells: int=_i("WALLET_MIN_MATCHED_SELLS",10)
    x_bearer_token: str=os.getenv("X_BEARER_TOKEN","")
    x_kol_ids: tuple=tuple(x.strip() for x in os.getenv("X_KOL_IDS","").split(",") if x.strip())
    revival_min_volume_5m_usd: float=_f("REVIVAL_MIN_VOLUME_5M_USD",5000)
    revival_volume_ratio: float=_f("REVIVAL_VOLUME_RATIO",2)
    paper_fee_bps: float=_f("PAPER_FEE_BPS",100)
    paper_slippage_bps: float=_f("PAPER_SLIPPAGE_BPS",100)
    stop_loss_pct: float=_f("STOP_LOSS_PCT",20)
    take_profit_pct: float=_f("TAKE_PROFIT_PCT",50)
    trailing_stop_pct: float=_f("TRAILING_STOP_PCT",20)
    paper_max_hold_minutes: float=_f("PAPER_MAX_HOLD_MINUTES",1440)
    tracked_wallets_json: str=os.getenv("TRACKED_WALLETS", "[]")
    jev_api_key: str=os.getenv("JEV_API_KEY","")
    jev_endpoint: str=os.getenv("JEV_ENDPOINT","")
    jev_timeout_ms: int=_i("JEV_TIMEOUT_MS",10000)
    openai_api_key: str=os.getenv("OPENAI_API_KEY","")
    openai_endpoint: str="https://api.openai.com/v1/responses"
    openai_model: str=os.getenv("OPENAI_MODEL","gpt-5.6-terra")
    openai_timeout_ms: int=_i("OPENAI_TIMEOUT_MS",15000)
    openai_daily_request_limit: int=_i("OPENAI_DAILY_REQUEST_LIMIT",10)
    gemini_api_key: str=os.getenv("GEMINI_API_KEY","")
    gemini_model: str=os.getenv("GEMINI_MODEL","gemini-3.5-flash-lite")
    gemini_endpoint: str="https://generativelanguage.googleapis.com/v1beta/models/"
    gemini_timeout_ms: int=_i("GEMINI_TIMEOUT_MS",15000)
    gemini_daily_request_limit: int=_i("GEMINI_DAILY_REQUEST_LIMIT",100)
    laya_api_key: str=os.getenv("LAYA_API_KEY","")
    laya_endpoint: str=os.getenv("LAYA_ENDPOINT","")
    laya_timeout_ms: int=_i("LAYA_TIMEOUT_MS",1200)
    tavily_api_key: str=os.getenv("TAVILY_API_KEY","")
    darwin_api_key: str=os.getenv("DARWIN_API_KEY","")
    darwin_endpoint: str=os.getenv("DARWIN_ENDPOINT","")
    darwin_timeout_ms: int=_i("DARWIN_TIMEOUT_MS",5000)
    paper_starting_sol: float=_f("PAPER_STARTING_SOL",10)
    default_buy_sol: float=_f("DEFAULT_BUY_SOL",0.05)
    max_trade_sol: float=_f("MAX_TRADE_SOL",0.10)
    max_open_positions: int=_i("MAX_OPEN_POSITIONS",5)
    max_daily_loss_sol: float=_f("MAX_DAILY_LOSS_SOL",0.50)
    min_liquidity_usd: float=_f("MIN_LIQUIDITY_USD",10000)
    max_token_age_minutes: int=_i("MAX_TOKEN_AGE_MINUTES",1440)
    min_combined_score: float=_f("MIN_COMBINED_SCORE",70)
    min_wallet_score: float=_f("MIN_WALLET_SCORE",50)
    max_risk_score: float=_f("MAX_RISK_SCORE",70)
settings=Settings()


def trading_settings(base=None,now=None):
    """A fixed-deadline paper trial, evaluated on every decision, survives restarts."""
    import math,time
    from dataclasses import replace
    base=base or settings
    now=time.time() if now is None else now
    until=_f('PAPER_RISK_TRIAL_UNTIL',0)
    if not base.paper_mode or not math.isfinite(until) or now>=until:return base
    return replace(base,min_liquidity_usd=min(base.min_liquidity_usd,5000),
        min_combined_score=min(base.min_combined_score,60),min_wallet_score=min(base.min_wallet_score,40),
        max_risk_score=max(base.max_risk_score,75),revival_min_volume_5m_usd=min(base.revival_min_volume_5m_usd,2000),
        revival_volume_ratio=min(base.revival_volume_ratio,1.5),default_buy_sol=min(base.default_buy_sol,.025),
        max_trade_sol=min(base.max_trade_sol,.025),max_open_positions=min(base.max_open_positions,3),
        max_daily_loss_sol=min(base.max_daily_loss_sol,.15))

def risk_trial_status(now=None):
    import time
    now=time.time() if now is None else now
    rules=trading_settings(now=now);until=_f('PAPER_RISK_TRIAL_UNTIL',0)
    return {'active':rules is not settings,'ends_at':until if until>0 else None,
        'min_liquidity_usd':rules.min_liquidity_usd,'min_combined_score':rules.min_combined_score,
        'min_wallet_score':rules.min_wallet_score,'max_trade_sol':rules.max_trade_sol,
        'max_open_positions':rules.max_open_positions,'max_daily_loss_sol':rules.max_daily_loss_sol}
