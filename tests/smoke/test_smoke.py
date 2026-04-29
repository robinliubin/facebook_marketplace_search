"""Real-Marketplace smoke. Default-excluded via pyproject's `addopts = -m "not smoke"`.

Opt-in: `pytest -m smoke tests/smoke/test_smoke.py -s`. Requires a previously
captured logged-in session (run `fbms setup` first).
"""

from __future__ import annotations

import pytest

from fb_marketplace_search.config import make_settings
from fb_marketplace_search.parser import parse


@pytest.mark.smoke
def test_smoke_search_returns_at_least_one_card():
    """End-to-end ping. Asserts only that the runner returns >=1 card without
    crashing — not strict on counts (Marketplace inventory is volatile).
    """
    from fb_marketplace_search.driver import open_page, run_search

    settings = make_settings()
    if not settings.state_path.exists():
        pytest.skip(f"no captured session at {settings.state_path}; run `fbms setup` first")

    query = parse('hockey gloves 11" $50-100 10km')
    with open_page(settings) as page:
        cards, _pages = run_search(page, query, pages=1, settings=settings)

    assert len(cards) >= 1, "expected at least one card from a real Marketplace search"
