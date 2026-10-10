# Solana AI Trader

Paper-first Solana/Pump.fun AI trading research bot with a phone-friendly dashboard.

Included:
- Autonomous paper-trading loop
- Hard deterministic filters before AI
- Jev primary, Laya fallback, Darwin/general-model scaffold
- Wallet AI, Social AI, Risk AI
- Wallet profiler and overlap graph
- Entry, exit, sizing, and hard-risk engines
- SQLite trade history and performance stats
- Pump/PumpSwap/Jupiter/Jito execution-routing scaffold
- Clean dark mobile dashboard
- Live execution disabled by default

## Mac setup

```bash
git clone https://github.com/Jriv420/solana-ai-trader.git
cd solana-ai-trader
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app:app --reload
```

Open http://127.0.0.1:8000

If WATCHLIST_MINTS is blank, the app uses demo tokens so you can test immediately.

Never commit `.env`, API keys, wallet private keys, or seed phrases.
