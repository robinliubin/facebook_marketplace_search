"""§3 — non-size filter validators (price/distance/recency/condition + combo)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from fb_marketplace_search.normalize import NormalizedListing
from fb_marketplace_search.parser import ParsedQuery
from fb_marketplace_search.validate import validate_all
from fb_marketplace_search.validate.validators import (
    validate_condition,
    validate_distance,
    validate_price,
    validate_recency,
)


def _listing(**overrides):
    base = dict(
        marketplace_id="1",
        url="https://www.facebook.com/marketplace/item/1",
        title=None,
        description=None,
        price=None,
        currency=None,
        location=None,
        distance_km=None,
        listed_at=None,
        condition=None,
        seller_id=None,
        image_url=None,
        raw_blob=b"",
        position=0,
    )
    base.update(overrides)
    return NormalizedListing(**base)


# Price ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "case_id,price,expected_pass,reason_substr",
    [
        ("PRICE-1", 75.0, True, None),
        ("PRICE-2", 50.0, True, None),
        ("PRICE-3", 100.0, True, None),
        ("PRICE-4", 49.99, False, "below_min"),
        ("PRICE-5", 100.01, False, "above_max"),
        ("PRICE-6", None, False, "no_price"),
    ],
)
def test_price_range_50_100(case_id, price, expected_pass, reason_substr):
    out = validate_price(price, "CAD", pmin=50.0, pmax=100.0)
    assert out.passed is expected_pass, f"{case_id}: got {out!r}"
    if reason_substr:
        assert reason_substr in (out.reason or "")


def test_price_under_100_zero_is_valid():
    """PRICE-7."""
    out = validate_price(0.0, "CAD", pmin=0.0, pmax=100.0)
    assert out.passed is True


def test_price_over_50_no_upper_bound():
    """PRICE-8."""
    out = validate_price(10000.0, "CAD", pmin=50.0, pmax=None)
    assert out.passed is True


def test_price_currency_mismatch():
    """PRICE-10 with architect §7.3 default (currency_mismatch)."""
    out = validate_price(80.0, "USD", pmin=50.0, pmax=100.0)
    assert out.passed is False
    assert out.reason == "currency_mismatch"


# Distance ------------------------------------------------------------------


def test_dist_inside_range():
    """DIST-1."""
    assert validate_distance(5.0, max_km=10.0).passed is True


def test_dist_inclusive_upper():
    """DIST-2."""
    assert validate_distance(10.0, max_km=10.0).passed is True


def test_dist_just_over():
    """DIST-3."""
    out = validate_distance(10.01, max_km=10.0)
    assert out.passed is False


def test_dist_missing():
    """DIST-4."""
    out = validate_distance(None, max_km=10.0)
    assert out.passed is False
    assert out.reason == "no_distance"


def test_dist_marketplace_lied():
    """DIST-5: Marketplace's own filter is leaky and returns a tile reporting
    distance_km=15 when we asked for ≤10.
    """
    out = validate_distance(15.0, max_km=10.0)
    assert out.passed is False
    assert "exceeds" in (out.reason or "")


# Recency -------------------------------------------------------------------


_NOW = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "case_id,listed_at,max_days,expected",
    [
        ("RECENT-1", _NOW - timedelta(days=7), 7, True),
        ("RECENT-2", _NOW - timedelta(days=8), 7, False),
        ("RECENT-3", _NOW, 7, True),  # 'just listed'
        ("RECENT-4", _NOW - timedelta(hours=3), 7, True),
        ("RECENT-6", _NOW - timedelta(days=1), 0, False),  # filter=today
        ("RECENT-7", _NOW - timedelta(hours=23), 1, True),
    ],
)
def test_recency(case_id, listed_at, max_days, expected):
    out = validate_recency(listed_at, max_days=max_days, now=_NOW)
    assert out.passed is expected, f"{case_id}: {out}"


def test_recency_missing():
    """RECENT-5."""
    out = validate_recency(None, max_days=7, now=_NOW)
    assert out.passed is False
    assert out.reason == "no_listed_at"


# Condition -----------------------------------------------------------------


def test_condition_match():
    """COND-1."""
    out = validate_condition("new", target="new")
    assert out.passed is True


def test_condition_mismatch_exact():
    """COND-2."""
    out = validate_condition("used-like-new", target="new")
    assert out.passed is False


def test_condition_missing():
    """COND-4."""
    out = validate_condition(None, target="new")
    assert out.passed is False
    assert out.reason == "no_condition"


# Combo --------------------------------------------------------------------


def _query(**overrides) -> ParsedQuery:
    base = dict(
        keywords="gants",
        size=None,
        price_min=None,
        price_max=None,
        distance_km=None,
        recency_days=None,
        condition=None,
    )
    base.update(overrides)
    return ParsedQuery(**base)


def test_combo_all_pass():
    """COMBO-3."""
    q = _query(
        size="11",
        price_min=50.0,
        price_max=100.0,
        distance_km=10.0,
        recency_days=7,
        condition="new",
    )
    listing = _listing(
        title="Bauer hockey gloves size 11 like new",  # title carries "size 11"
        description=None,
        price=80.0,
        currency="CAD",
        distance_km=5.0,
        listed_at=_NOW - timedelta(days=2),
        condition="new",
    )
    ok, failures = validate_all(listing, q, now=_NOW)
    assert ok is True
    assert failures == []


def test_combo_three_failures_recorded():
    """COMBO-2 / AT-4.2 — every failing filter is recorded, not just the first."""
    q = _query(
        size="11",
        price_min=50.0,
        price_max=100.0,
        distance_km=10.0,
        recency_days=7,
        condition="new",
    )
    listing = _listing(
        title="Bauer gloves size 14",
        description=None,
        price=120.0,  # above max
        currency="CAD",
        distance_km=15.0,  # exceeds
        listed_at=_NOW - timedelta(days=3),
        condition="new",
    )
    ok, failures = validate_all(listing, q, now=_NOW)
    assert ok is False
    filters_failed = {f.filter for f in failures}
    assert filters_failed == {"size", "price", "distance"}


def test_condition_only_evaluated_when_user_specified():
    """COND-5."""
    q = _query(price_min=50.0, price_max=100.0)  # condition NOT specified
    listing = _listing(price=80.0, currency="CAD", condition=None)
    ok, failures = validate_all(listing, q, now=_NOW)
    assert ok is True
    assert failures == []
