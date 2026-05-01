"""DIFF-* — diff/dedup logic. Test plan §4."""

from __future__ import annotations

from fb_marketplace_search.diff import compute_diff


def test_diff_1_all_still_there():
    """DIFF-1."""
    prior = [("a", 80.0), ("b", 90.0)]
    current = [("a", 80.0), ("b", 90.0)]
    d = compute_diff(prior, current)
    assert d.still_there == ["a", "b"]
    assert d.new == []
    assert d.gone == []
    assert d.price_changed == []


def test_diff_2_new_gone_still():
    """DIFF-2."""
    prior = [("1", 10.0), ("2", 20.0)]
    current = [("2", 20.0), ("3", 30.0)]
    d = compute_diff(prior, current)
    assert d.new == ["3"]
    assert d.gone == ["1"]
    assert d.still_there == ["2"]


def test_diff_3_price_changed():
    """DIFF-3."""
    d = compute_diff([("1", 80.0)], [("1", 70.0)])
    assert d.price_changed and d.price_changed[0].listing_id == "1"
    assert d.price_changed[0].old_price == 80.0
    assert d.price_changed[0].new_price == 70.0
    assert "1" not in d.still_there


def test_diff_4_unchanged_price_is_still_there_not_price_changed():
    """DIFF-4."""
    d = compute_diff([("1", 80.0)], [("1", 80.0)])
    assert d.still_there == ["1"]
    assert d.price_changed == []
