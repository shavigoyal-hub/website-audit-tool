"""Per-run cost + call-count tracking.

Counters live on a module-level dict so a single Flask request can accumulate
them across every module it touches (composio_exec, pagespeed, crawler).
Cost rates come from env so ops can tune without a code change.
"""
import os

# Per-call rate (USD). Override in Vercel env if the real Composio price
# is different — the placeholder is a rough steady-state estimate.
COMPOSIO_RATE = float(os.environ.get("COMPOSIO_COST_PER_CALL_USD") or 0.001)
PSI_RATE      = float(os.environ.get("PSI_COST_PER_CALL_USD") or 0.0)

_COUNTERS = {
    "composio_calls": 0,
    "psi_calls":      0,
    "pages_crawled":  0,
}


def reset():
    for k in _COUNTERS:
        _COUNTERS[k] = 0


def incr(key, n=1):
    if key in _COUNTERS:
        _COUNTERS[key] += n


def set_value(key, n):
    if key in _COUNTERS:
        _COUNTERS[key] = int(n)


def snapshot():
    """Return {counts, rates, est_cost_usd} for the current run."""
    counts = dict(_COUNTERS)
    est = counts["composio_calls"] * COMPOSIO_RATE + counts["psi_calls"] * PSI_RATE
    return {
        "counts":        counts,
        "rates":         {"composio": COMPOSIO_RATE, "psi": PSI_RATE},
        "est_cost_usd":  round(est, 4),
    }
