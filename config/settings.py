from dataclasses import dataclass
import os
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
    solana_rpc_url: str=os.getenv("SOLANA_RPC_URL","")
    jev_api_key: str=os.getenv("JEV_API_KEY","")
    jev_endpoint: str=os.getenv("JEV_ENDPOINT","")
    jev_timeout_ms: int=_i("JEV_TIMEOUT_MS",1200)
    laya_api_key: str=os.getenv("LAYA_API_KEY","")
    laya_endpoint: str=os.getenv("LAYA_ENDPOINT","")
    laya_timeout_ms: int=_i("LAYA_TIMEOUT_MS",1200)
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
