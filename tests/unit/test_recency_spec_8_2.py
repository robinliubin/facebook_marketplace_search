"""RECENT-5b / RECENT-8a-g — spec §8.2 listed-at mappings.

`a week ago` / `1 week ago` / `last week` -> 7d (lenient).
`n weeks ago` -> n*7 days.
`X days ago` -> literal.
`just listed` / `today` / sub-day -> 0 days at the validator level.
Anything else -> NULL -> validator fails `no_listed_at`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from fb_marketplace_search.normalize.listing import parse_listed_at
from fb_marketplace_search.validate.validators import validate_recency


_NOW = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)


def _check(raw: str, recency_days: int, *, expected_pass: bool) -> None:
    listed_at = parse_listed_at(raw, now=_NOW)
    if listed_at is None and expected_pass:
        pytest.fail(f"parse_listed_at({raw!r}) returned None unexpectedly")
    out = validate_recency(listed_at, max_days=recency_days, now=_NOW)
    assert out.passed is expected_pass, f"raw={raw!r} max_days={recency_days}: {out}"


def test_recent_5b_anything_else_is_no_listed_at():
    """RECENT-5b: 'around a fortnight' (not on the allow-list) -> NULL ->
    fail with no_listed_at.
    """
    listed_at = parse_listed_at("around a fortnight", now=_NOW)
    assert listed_at is None
    out = validate_recency(listed_at, max_days=7, now=_NOW)
    assert out.passed is False
    assert out.reason == "no_listed_at"


def test_recent_8_a_week_ago_passes_7():
    """RECENT-8: filter=7, listed='a week ago' -> pass."""
    _check("a week ago", 7, expected_pass=True)


def test_recent_8b_1_week_ago_passes_7():
    _check("1 week ago", 7, expected_pass=True)


def test_recent_8c_last_week_passes_7():
    _check("last week", 7, expected_pass=True)


def test_recent_8d_2_weeks_ago_passes_14():
    _check("2 weeks ago", 14, expected_pass=True)


def test_recent_8e_2_weeks_ago_fails_13():
    _check("2 weeks ago", 13, expected_pass=False)


def test_recent_8f_3_days_ago_passes_7():
    _check("3 days ago", 7, expected_pass=True)


def test_recent_8g_8_days_ago_fails_7():
    _check("8 days ago", 7, expected_pass=False)
