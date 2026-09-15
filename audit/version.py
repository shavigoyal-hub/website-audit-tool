"""Audit tool version — stamped on every XLSX, Sheet and Deck.

Bump when observation rules, catalog copy, or output structure change so
you can tell which build produced a given audit artifact.
"""
VERSION = "2026-09-15.14"

# Plan tier → expected leads per month at month 3-4 / 6-7 / 9-10
# Source: internal Gushwork projection chart. Plan number = $ / month spend.
PLAN_TIERS = {
    100: {"M3-4": 6,  "M6-7": 11, "M9-10": 17},
    200: {"M3-4": 8,  "M6-7": 15, "M9-10": 25},
    400: {"M3-4": 14, "M6-7": 23, "M9-10": 34},
}

# CPL reduction that we commit to for the deck lead-math slide.
CPL_REDUCTION_PCT = 5


def resolve_plan(plan_input):
    """Snap arbitrary plan spend to the nearest tier bucket."""
    try:
        n = int(plan_input)
    except (TypeError, ValueError):
        return None
    return min(PLAN_TIERS.keys(), key=lambda k: abs(k - n))
