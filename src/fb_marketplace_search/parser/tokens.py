"""Regex catalog — single source of truth for what v1 understands as a filter.

Each TOKEN_* is an `(re.Pattern, group_name -> field_name)` pair. The parser
walks the input once per token, consuming matches into structured filters.

Numeric size tokens require a non-digit boundary on each side (regex anchored
with `(?<![\\d.])` / `(?![\\d.])`) so `11` does not steal `110`/`11.5`. Alpha
sizes use case-insensitive whole-word match. The size validator at runtime
re-applies the same boundary discipline against the listing text — this file
is *only* the parser side (extracting the user's intent from the query).
"""

from __future__ import annotations

import re

# --- size --------------------------------------------------------------------
# Order matters: try `11"` and `11 inch` BEFORE bare `11`, so the inch suffix
# is consumed too (otherwise we'd leave a stray `"` in the keyword string).
SIZE_NUMERIC_INCH = re.compile(
    r'(?<![\d.])(?P<size>\d{1,3})\s*(?:"|inch(?:es)?|in\.?)(?![\w])',
    re.IGNORECASE,
)
SIZE_NUMERIC_BARE = re.compile(r'(?<![\d.\w])(?P<size>\d{1,3})(?![\d.\w])')
SIZE_ALPHA = re.compile(r'(?<![A-Za-z])(?P<size>XS|XXL|XL|L|M|S)(?![A-Za-z])')

# --- price -------------------------------------------------------------------
PRICE_DOLLAR_RANGE = re.compile(
    r'\$\s*(?P<lo>\d+(?:\.\d+)?)\s*-\s*(?P<hi>\d+(?:\.\d+)?)\b',
)
PRICE_RANGE_DOLLAR_SUFFIX = re.compile(
    r'\b(?P<lo>\d+(?:\.\d+)?)\s*-\s*(?P<hi>\d+(?:\.\d+)?)\s*\$',
)
PRICE_BETWEEN = re.compile(
    r'\bbetween\s+\$?(?P<lo>\d+(?:\.\d+)?)\s+and\s+\$?(?P<hi>\d+(?:\.\d+)?)\b',
    re.IGNORECASE,
)
PRICE_UNDER = re.compile(r'\bunder\s+\$?(?P<hi>\d+(?:\.\d+)?)\b', re.IGNORECASE)
PRICE_OVER = re.compile(r'\bover\s+\$?(?P<lo>\d+(?:\.\d+)?)\b', re.IGNORECASE)

# --- distance ----------------------------------------------------------------
DISTANCE_WITHIN = re.compile(
    r'\bwithin\s+(?P<km>\d+(?:\.\d+)?)\s*km\b', re.IGNORECASE,
)
DISTANCE_PLAIN = re.compile(r'\b(?P<km>\d+(?:\.\d+)?)\s*km\b', re.IGNORECASE)

# --- recency -----------------------------------------------------------------
# These map natural-language windows to integer days. `today`=0, `past 24h`=1.
RECENCY_TODAY = re.compile(r'\btoday\b', re.IGNORECASE)
RECENCY_PAST_HOURS = re.compile(
    r'\bpast\s+(?P<h>\d+)\s*h(?:ours?)?\b', re.IGNORECASE,
)
RECENCY_LISTED_IN = re.compile(
    r'\blisted\s+in\s+(?P<n>\d+)\s+(?P<unit>day|days|week|weeks|month|months)\b',
    re.IGNORECASE,
)
RECENCY_LAST_N = re.compile(
    r'\blast\s+(?P<n>\d+)\s+(?P<unit>day|days|week|weeks|month|months)\b',
    re.IGNORECASE,
)

# --- condition ---------------------------------------------------------------
# Order matters: `like new` must be tried before bare `new`.
CONDITION_LIKE_NEW = re.compile(r'\blike\s+new\b', re.IGNORECASE)
CONDITION_NEW = re.compile(r'\bnew\b', re.IGNORECASE)
CONDITION_USED_GOOD = re.compile(r'\b(?:used\s+)?good\b', re.IGNORECASE)
CONDITION_USED_FAIR = re.compile(r'\b(?:used\s+)?fair\b', re.IGNORECASE)
CONDITION_USED = re.compile(r'\bused\b', re.IGNORECASE)


CONDITION_VALUES = {
    "like new": "used-like-new",
    "new": "new",
    "used": "used-good",
    "good": "used-good",
    "fair": "used-fair",
}


def days_from_unit(n: int, unit: str) -> int:
    u = unit.lower()
    if u.startswith("day"):
        return n
    if u.startswith("week"):
        return n * 7
    if u.startswith("month"):
        return n * 30
    raise ValueError(f"unknown recency unit: {unit}")
