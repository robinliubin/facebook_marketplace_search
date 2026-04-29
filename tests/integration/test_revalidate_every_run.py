"""AT-5.6 — every run revalidates from scratch.

A listing with `validated_pass=true` in run T1 (because the validator was
buggy) must be re-evaluated in run T2 (after a validator fix). The
listing's run-T2 search_results row reflects the CURRENT validator state,
not the cached prior pass.

We simulate the "validator bugfix" by changing the query's filter set
between runs (size=11 then size=14) — same listing, different pass result.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fb_marketplace_search.driver.search_runner import harvest_from_html
from fb_marketplace_search.normalize import normalize
from fb_marketplace_search.parser import ParsedQuery
from fb_marketplace_search.storage import (
    canonical_filters_json,
    init_db,
    open_db,
    record_search,
    record_search_results,
    upsert_listing,
)
from fb_marketplace_search.validate import validate_all


FIX = Path(__file__).resolve().parent.parent / "fixtures"
NOW = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)


def _run_pipeline(conn, html: str, query: ParsedQuery) -> int:
    cards = harvest_from_html(html)
    listings = []
    for i, raw in enumerate(cards):
        blob = gzip.compress(json.dumps(raw, default=str).encode("utf-8"))
        listings.append(normalize(raw, raw_blob=blob, position=i, now=NOW))
    rows = []
    passed = 0
    for listing in listings:
        upsert_listing(conn, listing)
        ok, failures = validate_all(listing, query, now=NOW)
        if ok:
            passed += 1
        rows.append(
            (listing.marketplace_id, listing.position, ok, failures, listing.price, listing.currency)
        )
    sid = record_search(
        conn,
        query_text="x",
        parsed_filters_json=canonical_filters_json(query),
        pages_fetched=1,
        total_returned=len(listings),
        total_passed=passed,
    )
    record_search_results(conn, search_id=sid, rows=rows)
    conn.commit()
    return sid


def test_at_5_6_revalidation_every_run(tmp_path: Path):
    """Listing 1001 passes size=11 in run T1; reruns with size=14 in T2 must
    show validated_pass=0 for the same listing — the cached T1 pass result
    is NOT reused.
    """
    html = (FIX / "results_page_size11_clean.html").read_text()
    conn = open_db(tmp_path / "t.sqlite")
    init_db(conn)

    sid_t1 = _run_pipeline(conn, html, ParsedQuery(keywords="x", size="11"))
    cur = conn.execute(
        "SELECT validated_pass FROM search_results WHERE search_id=? AND listing_id=?",
        (sid_t1, "1001"),
    )
    assert cur.fetchone()["validated_pass"] == 1

    # Run T2: same listings but stricter filter (size=14). The same
    # listing must now have validated_pass=0 in the T2 row, while the T1
    # row is unchanged.
    sid_t2 = _run_pipeline(conn, html, ParsedQuery(keywords="x", size="14"))
    cur = conn.execute(
        "SELECT validated_pass FROM search_results WHERE search_id=? AND listing_id=?",
        (sid_t2, "1001"),
    )
    assert cur.fetchone()["validated_pass"] == 0

    # T1 result is still preserved.
    cur = conn.execute(
        "SELECT validated_pass FROM search_results WHERE search_id=? AND listing_id=?",
        (sid_t1, "1001"),
    )
    assert cur.fetchone()["validated_pass"] == 1
