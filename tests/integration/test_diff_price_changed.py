"""AT-5.2 regression — PRICE_CHANGED bucket must reflect prior-run price.

Bug #6: `passed_pairs_for_search` was reading `listings.price`, which UPSERT
overwrites on every run. Both prior and current calls returned the *current*
price, so old==new and PRICE_CHANGED was always empty. Fix: schema v2
adds `price_at_search` / `currency_at_search` to search_results, and the
diff helper reads from those.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from fb_marketplace_search.diff import compute_diff
from fb_marketplace_search.diff.differ import passed_pairs_for_search
from fb_marketplace_search.normalize import NormalizedListing
from fb_marketplace_search.parser import ParsedQuery
from fb_marketplace_search.storage import (
    canonical_filters_json,
    init_db,
    open_db,
    record_search,
    record_search_results,
    upsert_listing,
)


NOW = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)


def _listing(price: float) -> NormalizedListing:
    return NormalizedListing(
        marketplace_id="A2",
        url="https://example/A2",
        title="Bauer Pro size 11",
        description="Bauer Pro size 11 like new.",
        price=price,
        currency="CAD",
        location="Mtl",
        distance_km=3.0,
        listed_at=NOW,
        condition="used-like-new",
        seller_id="s_a2",
        image_url=None,
        raw_blob=b"x",
        position=0,
    )


def _record_run(conn, listing: NormalizedListing, query: ParsedQuery) -> int:
    upsert_listing(conn, listing)
    sid = record_search(
        conn,
        query_text="x",
        parsed_filters_json=canonical_filters_json(query),
        pages_fetched=1,
        total_returned=1,
        total_passed=1,
    )
    record_search_results(
        conn,
        search_id=sid,
        rows=[(listing.marketplace_id, 0, True, [], listing.price, listing.currency)],
    )
    conn.commit()
    return sid


def test_at_5_2_price_changed_old_and_new_recovered(tmp_path: Path):
    """Run 1 at price 80; run 2 at price 70. Diff must report
    PRICE_CHANGED(A2, old=80, new=70), and A2 must NOT also appear in
    still_there.
    """
    conn = open_db(tmp_path / "t.sqlite")
    init_db(conn)

    sid1 = _record_run(conn, _listing(80.0), ParsedQuery(keywords="x", size="11"))
    sid2 = _record_run(conn, _listing(70.0), ParsedQuery(keywords="x", size="11"))

    pairs1 = passed_pairs_for_search(conn, search_id=sid1)
    pairs2 = passed_pairs_for_search(conn, search_id=sid2)

    # First, the snapshots themselves are correct (this is the regression).
    assert pairs1 == [("A2", 80.0)], f"prior-run price snapshot wrong: {pairs1}"
    assert pairs2 == [("A2", 70.0)], f"current-run price snapshot wrong: {pairs2}"

    diff = compute_diff(pairs1, pairs2)
    assert len(diff.price_changed) == 1
    pc = diff.price_changed[0]
    assert pc.listing_id == "A2"
    assert pc.old_price == 80.0
    assert pc.new_price == 70.0
    assert "A2" not in diff.still_there


def test_at_5_2_unchanged_price_is_still_there(tmp_path: Path):
    """Sanity guard: if price is identical, listing falls in still_there,
    not price_changed (per DIFF-4 / AT-5.2 negative case).
    """
    conn = open_db(tmp_path / "t.sqlite")
    init_db(conn)
    sid1 = _record_run(conn, _listing(80.0), ParsedQuery(keywords="x", size="11"))
    sid2 = _record_run(conn, _listing(80.0), ParsedQuery(keywords="x", size="11"))
    pairs1 = passed_pairs_for_search(conn, search_id=sid1)
    pairs2 = passed_pairs_for_search(conn, search_id=sid2)
    diff = compute_diff(pairs1, pairs2)
    assert diff.price_changed == []
    assert "A2" in diff.still_there
