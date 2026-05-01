"""Per-filter validators. The wedge of v1.

Each public `validate_*` returns a `ValidationOutcome(passed, reason)`.
Reasons are short machine-readable strings (e.g. `no_price`, `out_of_range`,
`substring_match_blocked`) suitable for logging and for the success-metric
dashboard.

The size validator is the wedge — it MUST NOT accept substring matches.
See test plan §2 (WEDGE-NUM-* / WEDGE-ALPHA-*).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


@dataclass(frozen=True)
class ValidationOutcome:
    passed: bool
    reason: Optional[str] = None

    @classmethod
    def pass_(cls) -> "ValidationOutcome":
        return cls(True, None)

    @classmethod
    def fail(cls, reason: str) -> "ValidationOutcome":
        return cls(False, reason)


# ---------------------------------------------------------------------------
# size
# ---------------------------------------------------------------------------

# Pattern for a digit-range like `7-11` or `7 - 11`. The right-hand side is
# what we must NOT count as a clean size token.
_RANGE_RHS_RE = re.compile(r'(?P<lhs>\d+)\s*-\s*(?P<rhs>\d+)')


def _numeric_size_match(text: str, target: str) -> bool:
    """True iff `target` (a digit string) appears in `text` as a clean token,
    bounded on both sides by non-digit AND non-`.`, AND not as the RHS of a
    digit range like `7-11`.
    """
    if not text:
        return False
    # Build a boundary regex once per call. `target` is a small digit string,
    # safe to interpolate after re.escape.
    pat = re.compile(rf'(?<![\d.])(?:{re.escape(target)})(?![\d.])')

    # Collect spans of every digit-range RHS so we can exclude matches whose
    # start position falls inside one of those RHS spans.
    range_rhs_spans: list[tuple[int, int]] = []
    for rm in _RANGE_RHS_RE.finditer(text):
        rhs_start = rm.start("rhs")
        rhs_end = rm.end("rhs")
        range_rhs_spans.append((rhs_start, rhs_end))

    for m in pat.finditer(text):
        start = m.start()
        # Reject if this match coincides with a range RHS.
        in_range_rhs = any(rs <= start < re_ for rs, re_ in range_rhs_spans)
        if in_range_rhs:
            continue
        return True
    return False


def _alpha_size_match(text: str, target: str) -> bool:
    """Case-insensitive whole-token match for alpha sizes (XS/S/M/L/XL/XXL).
    Bounded by non-letter on both sides.
    """
    if not text:
        return False
    pat = re.compile(rf'(?<![A-Za-z])(?:{re.escape(target)})(?![A-Za-z])', re.IGNORECASE)
    return pat.search(text) is not None


def validate_size(text: Optional[str], target: str) -> ValidationOutcome:
    """Validate that `text` contains `target` size as a clean token.

    `target` may be numeric (`11`, `8`) or alpha (`XL`, `M`, ...).

    If `text` is empty / None, fail with `no_size_field` per spec §3 + WEDGE-NUM-11.
    """
    if not text:
        return ValidationOutcome.fail("no_size_field")
    if not target:
        # Defensive: an empty target shouldn't reach here.
        return ValidationOutcome.fail("empty_target")

    if target.isdigit():
        if _numeric_size_match(text, target):
            return ValidationOutcome.pass_()
        return ValidationOutcome.fail(f"size_token_{target}_not_in_text")

    # Alpha
    if _alpha_size_match(text, target):
        return ValidationOutcome.pass_()
    return ValidationOutcome.fail(f"size_token_{target}_not_in_text")


# ---------------------------------------------------------------------------
# price
# ---------------------------------------------------------------------------


def validate_price(
    price: Optional[float],
    currency: Optional[str],
    *,
    pmin: Optional[float],
    pmax: Optional[float],
    expected_currency: str = "CAD",
) -> ValidationOutcome:
    """Inclusive range check on structured price field.

    Per spec §3 + architect §7.3:
    - Missing structured price -> fail `no_price`. v1 does NOT parse description.
    - Currency mismatch -> fail `currency_mismatch`.
    """
    if price is None:
        return ValidationOutcome.fail("no_price")
    if currency is not None and currency.upper() != expected_currency.upper():
        return ValidationOutcome.fail("currency_mismatch")
    if pmin is not None and price < pmin:
        return ValidationOutcome.fail(f"price_{price}_below_min_{pmin}")
    if pmax is not None and price > pmax:
        return ValidationOutcome.fail(f"price_{price}_above_max_{pmax}")
    return ValidationOutcome.pass_()


# ---------------------------------------------------------------------------
# distance
# ---------------------------------------------------------------------------


def validate_distance(
    distance_km: Optional[float], *, max_km: float
) -> ValidationOutcome:
    if distance_km is None:
        return ValidationOutcome.fail("no_distance")
    if distance_km > max_km:
        return ValidationOutcome.fail(f"distance_{distance_km}_exceeds_{max_km}")
    return ValidationOutcome.pass_()


# ---------------------------------------------------------------------------
# recency
# ---------------------------------------------------------------------------


def validate_recency(
    listed_at: Optional[datetime],
    *,
    max_days: int,
    now: Optional[datetime] = None,
) -> ValidationOutcome:
    if listed_at is None:
        return ValidationOutcome.fail("no_listed_at")
    ref = now or datetime.now(timezone.utc)
    if listed_at.tzinfo is None:
        listed_at = listed_at.replace(tzinfo=timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    age = ref - listed_at
    if age < timedelta(0):
        # Future-dated; treat as just-listed (age 0).
        age = timedelta(0)
    if age > timedelta(days=max_days):
        return ValidationOutcome.fail(
            f"listed_{age.days}d_ago_exceeds_{max_days}d"
        )
    return ValidationOutcome.pass_()


# ---------------------------------------------------------------------------
# condition
# ---------------------------------------------------------------------------


def validate_condition(
    listing_condition: Optional[str], *, target: str
) -> ValidationOutcome:
    """Exact match against the structured condition field.

    Per spec §3: v1 does NOT infer condition from text. Missing structured
    field fails ONLY when the user specified a condition (handled by the
    pipeline — this function is called only when target != None).
    """
    if listing_condition is None:
        return ValidationOutcome.fail("no_condition")
    if listing_condition != target:
        return ValidationOutcome.fail(
            f"condition_{listing_condition}_not_{target}"
        )
    return ValidationOutcome.pass_()
