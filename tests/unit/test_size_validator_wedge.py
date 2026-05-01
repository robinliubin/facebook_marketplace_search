"""WEDGE — size validator boundary cases. Test plan §2.

Headline ship gate. If any of these regress, v1 does not ship.
"""

from __future__ import annotations

import pytest

from fb_marketplace_search.validate.validators import validate_size


# WEDGE-NUM-* (numeric size 11)
@pytest.mark.parametrize(
    "case_id,text,expected",
    [
        ("WEDGE-NUM-1", "Bauer hockey gloves size 11 like new", True),
        ("WEDGE-NUM-2", "CCM size 110 youth", False),
        ("WEDGE-NUM-3", "Vintage gloves 115", False),
        ("WEDGE-NUM-4", "Hockey set 7-11 various sizes", False),
        ("WEDGE-NUM-5", "Sizes available: s/m/l/xl/11", True),
        ("WEDGE-NUM-6", 'Gloves size: 11"', True),
        ("WEDGE-NUM-7", "Gloves 11.5 size", False),
        ("WEDGE-NUM-8", "Got 211 of these in stock", False),
        ("WEDGE-NUM-9", "Item #1101 hockey", False),
        ("WEDGE-NUM-12", "bauer\nhockey\n11", True),
        ("WEDGE-NUM-13", "Hockey gloves 7, 14, 15 in stock — message for 11", True),
        ("WEDGE-NUM-14", "BAUER 11 GLOVES", True),
    ],
)
def test_wedge_num(case_id, text, expected):
    outcome = validate_size(text, "11")
    assert outcome.passed is expected, (
        f"{case_id}: text={text!r} target='11' "
        f"expected pass={expected}, got pass={outcome.passed} (reason={outcome.reason!r})"
    )


def test_wedge_num_10_empty_text():
    """WEDGE-NUM-10: empty text fails with no_size_field."""
    outcome = validate_size("", "11")
    assert outcome.passed is False
    assert outcome.reason == "no_size_field"


def test_wedge_num_11_none_text_is_no_size_field():
    """WEDGE-NUM-11: missing source-of-truth (None) must fail with no_size_field.

    Models the case where description was the only source available and it is
    NULL after harvest.
    """
    outcome = validate_size(None, "11")
    assert outcome.passed is False
    assert outcome.reason == "no_size_field"


# WEDGE-ALPHA-*
@pytest.mark.parametrize(
    "case_id,text,target,expected",
    [
        ("WEDGE-ALPHA-1", "BAUER XL hockey jersey", "XL", True),
        ("WEDGE-ALPHA-2", "Size: xl", "XL", True),
        ("WEDGE-ALPHA-3", "XLR8 brand jersey", "XL", False),
        ("WEDGE-ALPHA-4", "Size: medium", "M", False),
        ("WEDGE-ALPHA-5", "Size M jersey", "M", True),
        ("WEDGE-ALPHA-6", "MMA gloves", "M", False),
        ("WEDGE-ALPHA-7", "Size S", "S", True),
        ("WEDGE-ALPHA-8", "Sport gear", "S", False),
        ("WEDGE-ALPHA-9", "XL/L/M available", "XL", True),
    ],
)
def test_wedge_alpha(case_id, text, target, expected):
    outcome = validate_size(text, target)
    assert outcome.passed is expected, (
        f"{case_id}: text={text!r} target={target!r} "
        f"expected pass={expected}, got pass={outcome.passed} (reason={outcome.reason!r})"
    )
