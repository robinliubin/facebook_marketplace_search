"""WEDGE-E2E-1 — the headline ship gate.

Per test plan §2: 20 listings, 5 truly size 11. After running the pipeline
with size=11, exactly those 5 must `validated_pass=true`. Precision = recall = 1.0.
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
from fb_marketplace_search.validate import validate_all


FIX = Path(__file__).resolve().parent.parent / "fixtures"
NOW = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)


def test_wedge_e2e_1():
    html = (FIX / "results_page_size11_dirty.html").read_text()
    raw_cards = harvest_from_html(html)
    assert len(raw_cards) == 20

    query = ParsedQuery(keywords="hockey gloves", size="11")

    passed_ids: list[str] = []
    failed_ids: list[str] = []
    for i, raw in enumerate(raw_cards):
        blob = gzip.compress(json.dumps(raw, default=str).encode("utf-8"))
        listing = normalize(raw, raw_blob=blob, position=i, now=NOW)
        ok, _failures = validate_all(listing, query, now=NOW)
        (passed_ids if ok else failed_ids).append(listing.marketplace_id)

    assert set(passed_ids) == {"2001", "2002", "2003", "2004", "2005"}, (
        f"expected exactly the 5 true-size-11 ids; got passed={sorted(passed_ids)}"
    )
    assert len(failed_ids) == 15
