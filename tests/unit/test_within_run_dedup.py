"""Architecture §7.6 — within-run dedup at the SQL layer.

`record_search_results` uses INSERT OR IGNORE on the (search_id, listing_id)
PK so the earliest-seen position is retained. Returns the count of dropped
duplicates; the CLI logs that as `dedup: dropped N within-run duplicate listings`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fb_marketplace_search.storage import (
    init_db,
    open_db,
    record_search,
    record_search_results,
    upsert_listing,
)
from fb_marketplace_search.normalize import NormalizedListing
from fb_marketplace_search.validate import ValidationFailure


def _listing(mid: str) -> NormalizedListing:
    return NormalizedListing(
        marketplace_id=mid,
        url=f"https://example/{mid}",
        title="t",
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


@pytest.fixture
def db(tmp_path: Path):
    conn = open_db(tmp_path / "t.sqlite")
    init_db(conn)
    yield conn
    conn.close()


def test_within_run_duplicate_listing_keeps_first_position(db):
    """Same listing_id at positions 0 and 5 in one search → one row at position 0."""
    upsert_listing(db, _listing("L1"))
    sid = record_search(
        db,
        query_text="q",
        parsed_filters_json="{}",
        pages_fetched=1,
        total_returned=2,
        total_passed=2,
    )
    rows = [
        ("L1", 0, True, []),
        ("L1", 5, True, []),  # duplicate
    ]
    dropped = record_search_results(db, search_id=sid, rows=rows)
    db.commit()
    assert dropped == 1
    cur = db.execute(
        "SELECT position FROM search_results WHERE search_id = ? AND listing_id = ?",
        (sid, "L1"),
    )
    row = cur.fetchone()
    assert row is not None
    assert row["position"] == 0  # earliest, not 5


def test_no_duplicates_returns_zero_dropped(db):
    upsert_listing(db, _listing("A"))
    upsert_listing(db, _listing("B"))
    sid = record_search(
        db,
        query_text="q",
        parsed_filters_json="{}",
        pages_fetched=1,
        total_returned=2,
        total_passed=2,
    )
    dropped = record_search_results(
        db,
        search_id=sid,
        rows=[("A", 0, True, []), ("B", 1, True, [])],
    )
    db.commit()
    assert dropped == 0


def test_failure_payload_preserved_on_first_row(db):
    """The first row's validation_failures_json is the one stored, not the dup's."""
    upsert_listing(db, _listing("L1"))
    sid = record_search(
        db,
        query_text="q",
        parsed_filters_json="{}",
        pages_fetched=1,
        total_returned=2,
        total_passed=0,
    )
    rows = [
        ("L1", 0, False, [ValidationFailure(filter="size", reason="r1")]),
        ("L1", 5, True, []),
    ]
    dropped = record_search_results(db, search_id=sid, rows=rows)
    db.commit()
    assert dropped == 1
    cur = db.execute(
        "SELECT validated_pass, validation_failures_json FROM search_results WHERE search_id=?",
        (sid,),
    )
    row = cur.fetchone()
    assert row["validated_pass"] == 0
    assert "size" in (row["validation_failures_json"] or "")
