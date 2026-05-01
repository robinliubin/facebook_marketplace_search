"""AT-2.* — harvest from canned HTML, no browser."""

from __future__ import annotations

from pathlib import Path

import pytest

from fb_marketplace_search.driver.search_runner import harvest_from_html


FIX = Path(__file__).resolve().parent.parent / "fixtures"


def test_at_2_2_extracts_required_fields_from_clean_fixture():
    html = (FIX / "results_page_size11_clean.html").read_text()
    cards = harvest_from_html(html)
    assert len(cards) == 5
    c = cards[0]
    for k in (
        "marketplace_id",
        "url",
        "title",
        "description",
        "price",
        "currency",
        "location",
        "distance_km",
        "listed_at",
        "condition",
        "seller_id",
        "image_url",
    ):
        assert k in c
    assert c["marketplace_id"] == "1001"
    assert c["url"].endswith("/marketplace/item/1001/abc")
    assert c["title"].startswith("Bauer Pro")
    assert c["price"] == 80.0
    assert c["currency"] == "CAD"
    assert c["distance_km"] == 3.0


def test_at_2_5_empty_fixture_returns_empty_list():
    html = (FIX / "results_page_empty.html").read_text()
    assert harvest_from_html(html) == []


def test_dirty_fixture_yields_20_cards():
    html = (FIX / "results_page_size11_dirty.html").read_text()
    cards = harvest_from_html(html)
    assert len(cards) == 20


def test_at_2_6_missing_description_does_not_crash():
    html = (FIX / "results_page_size11_dirty.html").read_text()
    cards = harvest_from_html(html)
    no_desc = [c for c in cards if c["marketplace_id"] == "2020"]
    assert len(no_desc) == 1
    # data-description="" -> empty string -> normalized to None downstream;
    # at the harvest level, an empty data-description is preserved as ''.
    assert no_desc[0]["description"] in ("", None)


def test_at_2_7_missing_price_does_not_crash():
    html = (FIX / "results_page_size11_dirty.html").read_text()
    cards = harvest_from_html(html)
    no_price = [c for c in cards if c["marketplace_id"] == "2021"]
    assert len(no_price) == 1
    assert no_price[0]["price"] is None
