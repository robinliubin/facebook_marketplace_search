"""Query parser: free-form string -> ParsedQuery.

Pure function, no I/O. Tested entirely with unit tests.

Strategy: walk the input through each filter pattern in priority order,
consuming the matched span (replacing with whitespace so positions of
later-tried patterns are preserved). What remains, with whitespace
collapsed, becomes the keyword string.

Ambiguity (per architect §7.4): two filters of the same type, OR a
size/condition token that *could* also be a keyword. The default ruling
in §7.4 is: when in doubt, prompt — so we surface ambiguity rather than
silently picking. This module returns ambiguity flags; the CLI decides
whether to prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from . import tokens


@dataclass(frozen=True)
class ParsedQuery:
    keywords: str
    size: Optional[str] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    distance_km: Optional[float] = None
    recency_days: Optional[int] = None
    condition: Optional[str] = None
    ambiguities: tuple[str, ...] = field(default_factory=tuple)

    def has_any_filter(self) -> bool:
        return any(
            v is not None
            for v in (
                self.size,
                self.price_min,
                self.price_max,
                self.distance_km,
                self.recency_days,
                self.condition,
            )
        )


@dataclass
class _Acc:
    text: str
    out: dict
    ambiguities: list[str]

    def consume(self, span: tuple[int, int]) -> None:
        a, b = span
        self.text = self.text[:a] + (" " * (b - a)) + self.text[b:]


class ParseAmbiguity(Exception):
    """Raised by `parse_strict` when the input has unresolved ambiguity."""

    def __init__(self, ambiguities: list[str]):
        super().__init__("; ".join(ambiguities))
        self.ambiguities = ambiguities


def parse(query: str) -> ParsedQuery:
    """Parse the free-form query. Returns a `ParsedQuery` even if ambiguous;
    `parsed.ambiguities` will be non-empty in that case.
    """
    if query is None:
        raise ValueError("query must not be None")

    acc = _Acc(text=query, out={}, ambiguities=[])

    _extract_price(acc)
    _extract_distance(acc)
    _extract_recency(acc)
    _extract_condition(acc)
    _extract_size(acc)

    keywords = _collapse_ws(_strip_separators(acc.text))

    return ParsedQuery(
        keywords=keywords,
        size=acc.out.get("size"),
        price_min=acc.out.get("price_min"),
        price_max=acc.out.get("price_max"),
        distance_km=acc.out.get("distance_km"),
        recency_days=acc.out.get("recency_days"),
        condition=acc.out.get("condition"),
        ambiguities=tuple(acc.ambiguities),
    )


def _set_once(acc: _Acc, key: str, value, where: str) -> None:
    if key in acc.out and acc.out[key] != value:
        acc.ambiguities.append(
            f"multiple {key} values detected ({acc.out[key]!r} and {value!r}) at {where}"
        )
        return
    acc.out[key] = value


def _extract_price(acc: _Acc) -> None:
    for pat, lo_key, hi_key in (
        (tokens.PRICE_DOLLAR_RANGE, "lo", "hi"),
        (tokens.PRICE_RANGE_DOLLAR_SUFFIX, "lo", "hi"),
        (tokens.PRICE_BETWEEN, "lo", "hi"),
    ):
        m = pat.search(acc.text)
        if m:
            _set_once(acc, "price_min", float(m.group(lo_key)), "price-range")
            _set_once(acc, "price_max", float(m.group(hi_key)), "price-range")
            acc.consume(m.span())
            return
    m = tokens.PRICE_UNDER.search(acc.text)
    if m:
        _set_once(acc, "price_min", 0.0, "price-under")
        _set_once(acc, "price_max", float(m.group("hi")), "price-under")
        acc.consume(m.span())
        return
    m = tokens.PRICE_OVER.search(acc.text)
    if m:
        _set_once(acc, "price_min", float(m.group("lo")), "price-over")
        acc.consume(m.span())
        return


def _extract_distance(acc: _Acc) -> None:
    for pat in (tokens.DISTANCE_WITHIN, tokens.DISTANCE_PLAIN):
        m = pat.search(acc.text)
        if m:
            _set_once(acc, "distance_km", float(m.group("km")), "distance")
            acc.consume(m.span())
            # Loop again in case there's a second occurrence — same value is fine,
            # different value flags ambiguity (`_set_once` records that).
            second = pat.search(acc.text)
            if second:
                _set_once(acc, "distance_km", float(second.group("km")), "distance-2")
                acc.consume(second.span())
            return


def _extract_recency(acc: _Acc) -> None:
    m = tokens.RECENCY_PAST_HOURS.search(acc.text)
    if m:
        h = int(m.group("h"))
        _set_once(acc, "recency_days", 1 if h <= 24 else (h + 23) // 24, "recency-hours")
        acc.consume(m.span())
        return
    m = tokens.RECENCY_TODAY.search(acc.text)
    if m:
        _set_once(acc, "recency_days", 0, "recency-today")
        acc.consume(m.span())
        return
    for pat in (tokens.RECENCY_LISTED_IN, tokens.RECENCY_LAST_N):
        m = pat.search(acc.text)
        if m:
            n = int(m.group("n"))
            unit = m.group("unit")
            _set_once(acc, "recency_days", tokens.days_from_unit(n, unit), "recency-window")
            acc.consume(m.span())
            return


def _extract_condition(acc: _Acc) -> None:
    # `like new` first.
    m = tokens.CONDITION_LIKE_NEW.search(acc.text)
    if m:
        _set_once(acc, "condition", "used-like-new", "condition-like-new")
        acc.consume(m.span())
        return
    for pat, value in (
        (tokens.CONDITION_NEW, "new"),
        (tokens.CONDITION_USED_GOOD, "used-good"),
        (tokens.CONDITION_USED_FAIR, "used-fair"),
        (tokens.CONDITION_USED, "used-good"),
    ):
        m = pat.search(acc.text)
        if m:
            _set_once(acc, "condition", value, f"condition-{value}")
            acc.consume(m.span())
            return


def _extract_size(acc: _Acc) -> None:
    # 1. Numeric+inch first (consumes the `"` / `inch` along with the digits).
    m = tokens.SIZE_NUMERIC_INCH.search(acc.text)
    if m:
        _set_once(acc, "size", m.group("size"), "size-numeric-inch")
        acc.consume(m.span())
        # Don't return — also consume any second numeric size-shaped token as
        # ambiguity, since user typed two sizes.
        m2 = tokens.SIZE_NUMERIC_INCH.search(acc.text) or tokens.SIZE_NUMERIC_BARE.search(acc.text)
        if m2:
            acc.ambiguities.append(
                f"multiple numeric size tokens ({acc.out['size']!r} and {m2.group('size')!r})"
            )
            acc.consume(m2.span())
        # Alpha shouldn't also be set when a numeric size already won.
        return

    # 2. Alpha BEFORE bare numeric: prevents stealing a `size 11" set` keyword digit
    #    when the user really meant the alpha. (§7.4 ambiguity: bare digits trigger
    #    a prompt, alpha sizes are unambiguous when they appear standalone.)
    m = tokens.SIZE_ALPHA.search(acc.text)
    if m:
        _set_once(acc, "size", m.group("size").upper(), "size-alpha")
        acc.consume(m.span())
        return

    # 3. Bare numeric. This is the ambiguous case: the digit could be a keyword.
    #    Per §7.4, we DO consume it (so the search behaves as the user almost
    #    always intends), but flag ambiguity so the CLI can prompt.
    m = tokens.SIZE_NUMERIC_BARE.search(acc.text)
    if m:
        size = m.group("size")
        _set_once(acc, "size", size, "size-numeric-bare")
        acc.consume(m.span())
        acc.ambiguities.append(
            f"bare digit {size!r} parsed as size — could also be a keyword"
        )


_SEP_RE = re.compile(r'[,;]+')


def _strip_separators(s: str) -> str:
    return _SEP_RE.sub(" ", s)


_WS_RE = re.compile(r'\s+')


def _collapse_ws(s: str) -> str:
    return _WS_RE.sub(" ", s).strip()
