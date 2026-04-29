"""AT-3.* — storage layer unit tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fb_marketplace_search.normalize import NormalizedListing
from fb_marketplace_search.parser import ParsedQuery
from fb_marketplace_search.storage import (
    canonical_filters_json,
    filters_hash,
    init_db,
    listings_for_search,
    most_recent_search_with_filters_hash,
    open_db,
    record_search,
    record_search_results,
    upsert_listing,
)
from fb_marketplace_search.validate import ValidationFailure


def _listing(mid="1", **overrides) -> NormalizedListing:
    base = dict(
        marketplace_id=mid,
        url=f"https://example.com/{mid}",
        title="t",
        description="d",
        price=80.0,
        currency="CAD",
        location="Mtl",
        distance_km=5.0,
        listed_at=datetime(2026, 4, 29, tzinfo=timezone.utc),
        condition="new",
        seller_id="s1",
        image_url="img",
        raw_blob=b"\x1f\x8b",  # gz magic; arbitrary bytes ok
        position=0,
    )
    base.update(overrides)
    return NormalizedListing(**base)


@pytest.fixture
def db(tmp_path: Path):
    conn = open_db(tmp_path / "test.sqlite")
    init_db(conn)
    yield conn
    conn.close()


def test_at_3_1_schema_creates_all_three_tables(db):
    cur = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {r[0] for r in cur.fetchall()}
    assert {"listings", "searches", "search_results"}.issubset(tables)


def test_at_3_3_upsert_idempotent_on_marketplace_id(db):
    listing1 = _listing(price=80.0)
    upsert_listing(db, listing1)
    listing2 = _listing(price=80.0)  # same fields
    upsert_listing(db, listing2)
    cur = db.execute("SELECT COUNT(*) FROM listings WHERE marketplace_id='1'")
    assert cur.fetchone()[0] == 1
    cur = db.execute("SELECT first_seen_at, last_seen_at FROM listings WHERE marketplace_id='1'")
    row = cur.fetchone()
    # last_seen_at >= first_seen_at; both populated.
    assert row["first_seen_at"]
    assert row["last_seen_at"]


def test_at_3_4_price_change_updates(db):
    upsert_listing(db, _listing(price=80.0))
    upsert_listing(db, _listing(price=70.0))
    cur = db.execute("SELECT price FROM listings WHERE marketplace_id='1'")
    assert cur.fetchone()[0] == 70.0


def test_at_3_5_failed_validation_recorded(db):
    upsert_listing(db, _listing())
    sid = record_search(
        db,
        query_text="q",
        parsed_filters_json="{}",
        pages_fetched=1,
        total_returned=1,
        total_passed=0,
    )
    record_search_results(
        db,
        search_id=sid,
        rows=[("1", 0, False, [ValidationFailure(filter="size", reason="size_token_11_not_in_text")], 80.0, "CAD")],
    )
    db.commit()
    cur = db.execute(
        "SELECT validated_pass, validation_failures_json FROM search_results WHERE search_id=? AND listing_id=?",
        (sid, "1"),
    )
    row = cur.fetchone()
    assert row["validated_pass"] == 0
    payload = json.loads(row["validation_failures_json"])
    assert payload[0]["filter"] == "size"


def test_canonical_filters_json_stable_across_runs():
    q1 = ParsedQuery(keywords="x", size="11", price_min=50.0, price_max=100.0)
    q2 = ParsedQuery(keywords="y", size="11", price_min=50.0, price_max=100.0)  # different keywords
    j1 = canonical_filters_json(q1)
    j2 = canonical_filters_json(q2)
    assert j1 == j2, "filters_json must NOT depend on keywords (diff hashes filters only)"
    assert filters_hash(j1) == filters_hash(j2)


def test_at_5_5_diff_lookup_only_matches_same_filters(db):
    """Different parsed filters must NOT cross-match in the prior-search lookup."""
    fjson_a = canonical_filters_json(ParsedQuery(keywords="x", size="11"))
    sid_a = record_search(
        db,
        query_text="x",
        parsed_filters_json=fjson_a,
        pages_fetched=1,
        total_returned=0,
        total_passed=0,
    )
    fjson_b = canonical_filters_json(ParsedQuery(keywords="y", size="14"))
    prior = most_recent_search_with_filters_hash(
        db, filters_hash_value=filters_hash(fjson_b)
    )
    assert prior is None
    prior_a = most_recent_search_with_filters_hash(
        db, filters_hash_value=filters_hash(fjson_a)
    )
    assert prior_a is not None
    assert prior_a["id"] == sid_a
