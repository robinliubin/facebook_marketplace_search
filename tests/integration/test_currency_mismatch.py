"""PRICE-10 — non-CAD listing fails price filter with reason `currency_mismatch`.

Architecture §7.8 / spec §8.1 ruling 8: structured price exists, currency
is not CAD → fail price filter with the exact reason string. v1 does NOT
do FX conversion. Pipeline writes:
  validation_failures_json = '[{"filter":"price","reason":"currency_mismatch"}]'
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

from fb_marketplace_search.driver.search_runner import harvest_from_html
from fb_marketplace_search.normalize import normalize
from fb_marketplace_search.parser import ParsedQuery
from fb_marketplace_search.storage import (
    canonical_filters_json,
    init_db,
    listings_for_search,
    open_db,
    record_search,
    record_search_results,
    upsert_listing,
)
from fb_marketplace_search.validate import validate_all


FIX = Path(__file__).resolve().parent.parent / "fixtures"
NOW = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)


def test_price_10_currency_mismatch_persists_correct_failure_reason(tmp_path: Path):
    html = (FIX / "listing_detail_currency_usd.html").read_text()
    cards = harvest_from_html(html)
    assert len(cards) == 1
    raw = cards[0]
    assert raw["currency"] == "USD"
    assert raw["price"] == 80.0

    blob = gzip.compress(json.dumps(raw, default=str).encode("utf-8"))
    listing = normalize(raw, raw_blob=blob, position=0, now=NOW)

    # User asked: CAD 50-100. Listing is USD 80.
    query = ParsedQuery(keywords="bauer", price_min=50.0, price_max=100.0)

    conn = open_db(tmp_path / "t.sqlite")
    init_db(conn)
    upsert_listing(conn, listing)
    ok, failures = validate_all(listing, query, now=NOW)
    sid = record_search(
        conn,
        query_text="bauer 50-100$",
        parsed_filters_json=canonical_filters_json(query),
        pages_fetched=1,
        total_returned=1,
        total_passed=1 if ok else 0,
    )
    record_search_results(
        conn,
        search_id=sid,
        rows=[(listing.marketplace_id, listing.position, ok, failures)],
    )
    conn.commit()

    assert ok is False
    rows = listings_for_search(conn, search_id=sid, only_passed=False)
    assert len(rows) == 1
    payload = json.loads(rows[0]["validation_failures_json"])
    # Architect §7.8: exactly this entry; no FX, no other failure reasons.
    assert payload == [{"filter": "price", "reason": "currency_mismatch"}]


def test_price_10_no_fx_conversion_done(tmp_path: Path):
    """80 USD ≈ 109 CAD at typical FX, which would fall outside CAD 50-100,
    but if we accidentally did FX conversion and got, say, 60 CAD, it would
    pass. v1 must NOT do this — the failure reason is currency_mismatch,
    not above_max.
    """
    from fb_marketplace_search.validate.validators import validate_price

    out = validate_price(80.0, "USD", pmin=50.0, pmax=100.0)
    assert out.passed is False
    assert out.reason == "currency_mismatch"

    # Also verify the price-range short-circuit ordering: a USD listing whose
    # price would have been *in range if it were CAD* must STILL fail with
    # currency_mismatch, not silently pass.
    out_in_range = validate_price(75.0, "USD", pmin=50.0, pmax=100.0)
    assert out_in_range.reason == "currency_mismatch"
