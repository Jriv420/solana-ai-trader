# Setup order

1. Clone the repo on the Mac.
2. Create `.venv`.
3. Install `requirements.txt`.
4. Copy `.env.example` to `.env`.
5. Keep `PAPER_MODE=true`.
6. Never place secrets in GitHub.
7. Run `uvicorn app:app --reload`.
8. Open `http://127.0.0.1:8000`.
9. Test demo mode first.
10. Add real token mints to `WATCHLIST_MINTS`.
11. Add Helius/RPC credentials when ready.
12. Add current Jev, Laya, and Darwin endpoint/key details only after confirming their current APIs.
13. Paper trade for a meaningful sample.
14. Review failures, fees/slippage assumptions, and calibration.
15. Only then implement real transaction adapters.
16. Use a dedicated low-balance trading wallet, never your primary wallet.
