"""normalize.listing — typed projection of harvested dicts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from fb_marketplace_search.normalize import normalize
from fb_marketplace_search.normalize.listing import parse_listed_at


_NOW = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)


def test_normalize_minimal_required_fields():
    raw = {"marketplace_id": "1", "url": "https://x/1"}
    n = normalize(raw, raw_blob=b"x", position=0)
    assert n.marketplace_id == "1"
    assert n.url == "https://x/1"
    assert n.title is None
    assert n.price is None


def test_normalize_missing_id_raises():
    with pytest.raises(ValueError):
        normalize({"url": "x"}, raw_blob=b"", position=0)


@pytest.mark.parametrize(
    "raw,expected_delta",
    [
        ("just listed", timedelta(0)),
        ("3 hours ago", timedelta(hours=3)),
        ("2 days ago", timedelta(days=2)),
        ("a week ago", timedelta(days=7)),
        ("1 week ago", timedelta(weeks=1)),
        ("yesterday", timedelta(days=1)),
    ],
)
def test_parse_listed_at(raw, expected_delta):
    got = parse_listed_at(raw, now=_NOW)
    assert got is not None
    assert _NOW - got == expected_delta


def test_parse_listed_at_none():
    assert parse_listed_at(None) is None
    assert parse_listed_at("") is None
    assert parse_listed_at("nonsense") is None
