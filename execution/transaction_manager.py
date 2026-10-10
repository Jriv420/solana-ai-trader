from config.settings import settings
def assert_live_execution_allowed():
    if settings.paper_mode or not settings.live_trading_enabled:
        raise RuntimeError("Live execution disabled. Keep PAPER_MODE=true until testing is complete.")
