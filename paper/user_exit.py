"""Operator-requested simulated exits, not independently verified scam labels."""
import os

def exit_requested(token):
    symbols={s.strip().lstrip('$').upper() for s in os.getenv('PAPER_EXIT_SYMBOLS','').split(',') if s.strip()}
    return str(token.get('symbol') or '').strip().lstrip('$').upper() in symbols

REASON='User-requested risk exit: reported social, holder and chart concerns (unverified)'
