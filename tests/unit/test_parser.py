"""AT-1.* — parser unit tests. Test plan §1 Story 1."""

from __future__ import annotations

import pytest

from fb_marketplace_search.parser import parse


# ---- Size --------------------------------------------------------------

def test_at_1_3a_numeric_inch_double_quote():
    p = parse('gants hockey 11"')
    assert p.size == "11"
    assert p.keywords == "gants hockey"


def test_at_1_3b_numeric_inch_word():
    p = parse('gants hockey 11 inch')
    assert p.size == "11"
    assert p.keywords == "gants hockey"


def test_at_1_3c_alpha_xl():
    p = parse("chandail XL")
    assert p.size == "XL"
    assert p.keywords == "chandail"


@pytest.mark.parametrize("alpha", ["XS", "S", "M", "L", "XL", "XXL"])
def test_at_1_3d_alpha_sizes(alpha):
    p = parse(f"chandail {alpha}")
    assert p.size == alpha
    assert p.keywords == "chandail"


# ---- Price -------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,lo,hi",
    [
        ("$50-100", 50.0, 100.0),
        ("50-100$", 50.0, 100.0),
        ("between 50 and 100", 50.0, 100.0),
    ],
)
def test_at_1_4_price_range(raw, lo, hi):
    p = parse(f"chandail {raw}")
    assert p.price_min == lo
    assert p.price_max == hi


def test_at_1_4d_price_under():
    p = parse("chandail under 100")
    assert p.price_min == 0.0
    assert p.price_max == 100.0


def test_at_1_4e_price_over():
    p = parse("chandail over 50")
    assert p.price_min == 50.0
    assert p.price_max is None


# ---- Distance ----------------------------------------------------------


@pytest.mark.parametrize("raw", ["10km", "10 km", "within 10 km"])
def test_at_1_5_distance(raw):
    p = parse(f"chandail {raw}")
    assert p.distance_km == 10.0


# ---- Recency -----------------------------------------------------------


def test_at_1_6a_listed_in_1_week():
    p = parse("chandail listed in 1 week")
    assert p.recency_days == 7


def test_at_1_6b_last_7_days():
    p = parse("chandail last 7 days")
    assert p.recency_days == 7


def test_at_1_6c_past_24h():
    p = parse("chandail past 24h")
    assert p.recency_days == 1


def test_at_1_6d_today():
    p = parse("chandail today")
    assert p.recency_days == 0


# ---- Condition ---------------------------------------------------------


def test_at_1_7a_new():
    p = parse("chandail new")
    assert p.condition == "new"


def test_at_1_7b_like_new():
    p = parse("chandail like new")
    assert p.condition == "used-like-new"


@pytest.mark.parametrize("raw,cond", [("used", "used-good"), ("good", "used-good"), ("fair", "used-fair")])
def test_at_1_7c_used_variants(raw, cond):
    p = parse(f"chandail {raw}")
    assert p.condition == cond


# ---- Composite ---------------------------------------------------------


def test_at_1_8_full_query():
    p = parse('gants hockey 11", new, 10km, $50-100, listed in 1 week')
    assert p.size == "11"
    assert p.condition == "new"
    assert p.distance_km == 10.0
    assert p.price_min == 50.0
    assert p.price_max == 100.0
    assert p.recency_days == 7
    assert p.keywords == "gants hockey"


def test_at_1_9_comma_less():
    p = parse('gants hockey 11" new 10km $50-100 listed in 1 week')
    assert p.size == "11"
    assert p.condition == "new"
    assert p.distance_km == 10.0
    assert p.price_min == 50.0
    assert p.price_max == 100.0
    assert p.recency_days == 7
    assert p.keywords == "gants hockey"


# ---- Adversarial -------------------------------------------------------


def test_at_1_10_filter_shaped_but_no_match():
    """`7-11 set` — bare digit token, no `size`/`taille`/`sz` cue, no inch
    suffix. Per spec §8.2 trigger 3, this is ambiguous: the parser
    consumes the digit as a size (first match) but flags it.
    """
    p = parse("7-11 set")
    assert p.size in ("7", "11")
    assert any("bare integer" in a for a in p.ambiguities)


def test_at_1_11d_bare_integer_no_cue_flagged():
    """AT-1.11d: `iphone 11 mint condition` — bare 11, no cue, ambiguous."""
    p = parse("iphone 11 mint condition")
    assert p.size == "11"
    assert any("bare integer" in a for a in p.ambiguities)


def test_lone_bare_digit_flagged():
    p = parse("11")
    assert p.size == "11"
    assert any("bare integer" in a for a in p.ambiguities)


def test_keywords_only_no_filters():
    p = parse("gants hockey")
    assert not p.has_any_filter()
    assert p.keywords == "gants hockey"
