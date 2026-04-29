"""AT-1.11a-i — three ambiguity triggers per spec §8.2.

A query is ambiguous (CLI must prompt) when ANY of:
  1. Duplicate filter type (e.g. two distance tokens).
  2. Token-class collision: a single-letter alpha-size flanked by alpha
     tokens not preceded by `size`/`taille`/`:`/`,`; OR `new` flanked by
     alpha words.
  3. Bare-integer collision: bare integer not preceded by
     `size`/`taille`/`sz`/`sz.` AND not followed by `"`/`inch`/`in.`.

The parser returns `parsed.ambiguities`; the CLI decides whether to prompt.
"""

from __future__ import annotations

import pytest

from fb_marketplace_search.parser import parse


# ---------------------------------------------------------------------------
# Trigger 1 — duplicate filter type
# ---------------------------------------------------------------------------


def test_at_1_11a_two_distance_tokens_first_wins_and_ambiguous():
    p = parse('gants hockey 11" 10km within 5 km')
    assert p.distance_km == 10.0  # first-by-position
    assert any("distance" in a for a in p.ambiguities)


def test_two_price_tokens_ambiguous():
    p = parse('chandail $50-100 between 20 and 30')
    # First-by-position wins.
    assert p.price_min == 50.0 and p.price_max == 100.0
    assert any("price" in a for a in p.ambiguities)


# ---------------------------------------------------------------------------
# Trigger 2 — token-class collision
# ---------------------------------------------------------------------------


def test_at_1_11b_new_in_alpha_context_flagged():
    """`new york yankees jersey XL` — `new` is consumed as condition but
    flagged ambiguous since both flanks are alphabetical.
    """
    p = parse("new york yankees jersey XL")
    assert p.condition == "new"
    assert p.size == "XL"
    assert any("'new'" in a for a in p.ambiguities)


def test_at_1_11c_single_alpha_flanked_by_alpha():
    """`vintage S sport gear` — `S` is between alpha tokens with no cue."""
    p = parse("vintage S sport gear")
    assert p.size == "S"
    assert any("size 'S'" in a for a in p.ambiguities)


def test_at_1_11f_alpha_with_cue_unambiguous():
    """`chandail size S` — `size` cue precedes; not ambiguous."""
    p = parse("chandail size S")
    assert p.size == "S"
    assert p.ambiguities == ()


def test_alpha_xl_flanked_by_punct_unambiguous():
    """XL after a comma: not alpha-flanked."""
    p = parse("vintage jersey, XL, mint")
    assert p.size == "XL"
    assert p.ambiguities == ()


# ---------------------------------------------------------------------------
# Trigger 3 — bare-integer collision
# ---------------------------------------------------------------------------


def test_at_1_11e_full_canonical_query_unambiguous():
    """The canonical example MUST parse cleanly with no ambiguities.

    Inch suffix on `11"`, explicit price/distance/recency tokens — none of
    the three triggers fires.
    """
    p = parse('gants hockey size 11" new 10km $50-100 listed in 1 week')
    assert p.size == "11"
    assert p.condition == "new"
    assert p.distance_km == 10.0
    assert p.price_min == 50.0 and p.price_max == 100.0
    assert p.recency_days == 7
    assert p.ambiguities == ()


def test_bare_integer_with_size_cue_unambiguous():
    p = parse("chandail size 11")
    assert p.size == "11"
    assert p.ambiguities == ()


def test_bare_integer_with_inch_suffix_unambiguous():
    p = parse('chandail 11"')
    assert p.size == "11"
    assert p.ambiguities == ()
