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
