"""AT-4.6 — distance always renders in km, never miles."""

from __future__ import annotations

from fb_marketplace_search.output import render_run


def test_at_4_6_distance_in_km():
    rows = [
        {
            "position": 0,
            "validated_pass": 1,
            "validation_failures_json": None,
            "marketplace_id": "L1",
            "title": "test",
            "url": "https://x/L1",
            "price": 80.0,
            "currency": "CAD",
            "distance_km": 4.7,
            "location": "Mtl",
        }
    ]
    out = render_run(rows)
    assert "4.7" in out
    assert "km" in out
    assert "mile" not in out.lower()
    assert "mi " not in out
