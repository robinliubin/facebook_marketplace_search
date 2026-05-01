"""Query parser: free-form string -> ParsedQuery.

Pure function, no I/O. Tested entirely with unit tests.

Strategy: walk the input through each filter pattern in priority order,
consuming the matched span (replacing with whitespace so positions of
later-tried patterns are preserved). What remains, with whitespace
collapsed, becomes the keyword string.

Ambiguity per spec §8.2 — three concrete triggers:

  1. Duplicate filter type: two or more tokens parsed into the same filter
     type (e.g. `10km within 5 km`, two prices). Pick the first-by-position
     match for the parsed-filter set; flag ambiguity.
  2. Token-class collision: a token matched a filter regex but its
     surrounding context is also plausibly keyword. Heuristic: a single-
     letter alpha-size token (S, M, L) flanked on both sides by
     alphabetical tokens — and not preceded by `size` / `taille` / `:` /
     `,` / string boundary — is ambiguous. The `new` condition token is
     ambiguous when both flanks are alphabetical (e.g. `new york yankees`).
  3. Bare-integer collision: a bare integer (no inch mark, no
     `size`/`taille`/`sz` cue) consumed as a numeric size. Concretely:
     ambiguous unless preceded by `size`/`taille`/`sz`/`sz.` OR followed
     by `"`/`inch`/`in.`.

The CLI prints the parsed filter set + `(y/N)` prompt when any ambiguity
fires; `--assume-yes` / `-y` skips the prompt with the first-match
interpretation echoed for audit.
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
    original: str
    out: dict
    ambiguities: list[str]

    def consume(self, span: tuple[int, int]) -> None:
        a, b = span
        self.text = self.text[:a] + (" " * (b - a)) + self.text[b:]


class ParseAmbiguity(Exception):
    """Raised by callers that want to treat ambiguity as fatal."""

    def __init__(self, ambiguities: list[str]):
        super().__init__("; ".join(ambiguities))
        self.ambiguities = ambiguities


def parse(query: str) -> ParsedQuery:
    """Parse the free-form query. Returns a ParsedQuery even if ambiguous;
    `parsed.ambiguities` will be non-empty in that case.
    """
    if query is None:
        raise ValueError("query must not be None")

    acc = _Acc(text=query, original=query, out={}, ambiguities=[])

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


# ---------------------------------------------------------------------------
# Price
# ---------------------------------------------------------------------------


def _extract_price(acc: _Acc) -> None:
    matches: list[tuple[int, dict]] = []
    for pat, kind in (
        (tokens.PRICE_DOLLAR_RANGE, "range"),
        (tokens.PRICE_RANGE_DOLLAR_SUFFIX, "range"),
        (tokens.PRICE_BETWEEN, "range"),
        (tokens.PRICE_UNDER, "under"),
        (tokens.PRICE_OVER, "over"),
    ):
        for m in pat.finditer(acc.text):
            matches.append((m.start(), {"pat": pat, "match": m, "kind": kind}))
    if not matches:
        return
    matches.sort(key=lambda x: x[0])
    first = matches[0][1]
    m = first["match"]
    if first["kind"] == "range":
        acc.out["price_min"] = float(m.group("lo"))
        acc.out["price_max"] = float(m.group("hi"))
    elif first["kind"] == "under":
        acc.out["price_min"] = 0.0
        acc.out["price_max"] = float(m.group("hi"))
    elif first["kind"] == "over":
        acc.out["price_min"] = float(m.group("lo"))
    acc.consume(m.span())
    if len(matches) > 1:
        acc.ambiguities.append(
            "multiple price tokens detected; using first-by-position"
        )
        # Consume the rest so they don't leak into keywords.
        for _, extra in matches[1:]:
            acc.consume(extra["match"].span())


# ---------------------------------------------------------------------------
# Distance
# ---------------------------------------------------------------------------


def _extract_distance(acc: _Acc) -> None:
    matches: list[tuple[int, "re.Match"]] = []
    for pat in (tokens.DISTANCE_WITHIN, tokens.DISTANCE_PLAIN):
        for m in pat.finditer(acc.text):
            matches.append((m.start(), m))
    if not matches:
        return
    matches.sort(key=lambda x: x[0])
    first = matches[0][1]
    acc.out["distance_km"] = float(first.group("km"))
    acc.consume(first.span())
    if len(matches) > 1:
        acc.ambiguities.append(
            "multiple distance tokens detected; using first-by-position"
        )
        for _, m in matches[1:]:
            acc.consume(m.span())


# ---------------------------------------------------------------------------
# Recency
# ---------------------------------------------------------------------------


def _extract_recency(acc: _Acc) -> None:
    """Recency precedence per spec §3:
       past Nh > today > listed-in/last-N (windowed)
    Duplicate windowed tokens flag ambiguity but use first-by-position.
    """
    m = tokens.RECENCY_PAST_HOURS.search(acc.text)
    if m:
        h = int(m.group("h"))
        acc.out["recency_days"] = 1 if h <= 24 else (h + 23) // 24
        acc.consume(m.span())
        return
    m = tokens.RECENCY_TODAY.search(acc.text)
    if m:
        acc.out["recency_days"] = 0
        acc.consume(m.span())
        return
    matches: list[tuple[int, "re.Match"]] = []
    for pat in (tokens.RECENCY_LISTED_IN, tokens.RECENCY_LAST_N):
        for m in pat.finditer(acc.text):
            matches.append((m.start(), m))
    if not matches:
        return
    matches.sort(key=lambda x: x[0])
    first = matches[0][1]
    n = int(first.group("n"))
    unit = first.group("unit")
    acc.out["recency_days"] = tokens.days_from_unit(n, unit)
    acc.consume(first.span())
    if len(matches) > 1:
        acc.ambiguities.append(
            "multiple recency tokens detected; using first-by-position"
        )
        for _, m in matches[1:]:
            acc.consume(m.span())


# ---------------------------------------------------------------------------
# Condition
# ---------------------------------------------------------------------------

_CONDITION_CUE_RE = re.compile(
    r'\b(?:condition|état|etat)\s*[:=-]?\s*$', re.IGNORECASE
)


def _extract_condition(acc: _Acc) -> None:
    """Look for `like new` first (longest), then `new` / `used` / `good` / `fair`.

    Token-class collision (spec §8.2 trigger 2): the bare token `new`
    flanked on both sides by alphabetical words (e.g. `new york yankees`)
    is flagged ambiguous unless preceded by a condition cue
    (`condition:`, `état`, etc.) or by `like` (handled separately).
    """
    m = tokens.CONDITION_LIKE_NEW.search(acc.text)
    if m:
        acc.out["condition"] = "used-like-new"
        acc.consume(m.span())
        return

    # Try each remaining condition pattern in priority order.
    for pat, value, name in (
        (tokens.CONDITION_NEW, "new", "new"),
        (tokens.CONDITION_USED_GOOD, "used-good", "good"),
        (tokens.CONDITION_USED_FAIR, "used-fair", "fair"),
        (tokens.CONDITION_USED, "used-good", "used"),
    ):
        m = pat.search(acc.text)
        if not m:
            continue
        if name == "new" and _is_keyword_adjacent(
            acc.text, m.span(), cue_word="condition"
        ):
            acc.ambiguities.append(
                f"token 'new' is adjacent to alphabetical context; "
                f"could be a keyword (e.g. 'new york'). Parsed as condition."
            )
        acc.out["condition"] = value
        acc.consume(m.span())
        return


# ---------------------------------------------------------------------------
# Size
# ---------------------------------------------------------------------------

# Cues immediately before a bare digit make it unambiguous as a size.
_BARE_DIGIT_CUE_BEFORE = re.compile(r'(?:\bsize|\btaille|\bsz\.?)\s*[:=]?\s*$', re.IGNORECASE)
# Cues immediately after a bare digit (before-strip) — handled separately
# via the SIZE_NUMERIC_INCH pattern, which already consumes `"`/`inch`/`in.`.

# Cues that disambiguate a bare alpha size.
_ALPHA_CUE_BEFORE = re.compile(
    r'(?:\bsize|\btaille|\bsz\.?)\s*[:=]?\s*$', re.IGNORECASE
)
_ALPHA_LEFT_PUNCT = re.compile(r'[:,]\s*$')
_ALPHA_RIGHT_PUNCT = re.compile(r'^\s*[:,/]')


def _extract_size(acc: _Acc) -> None:
    """Three-tier size extraction.

    1. Numeric+inch (`11"`, `11 inch`) — never ambiguous; the inch suffix is
       the disambiguator.
    2. Alpha (XS/S/M/L/XL/XXL) — ambiguous if the alpha is a single letter
       (S/M/L) flanked on both sides by alphabetical words AND not preceded
       by a size cue.
    3. Bare numeric — ambiguous unless preceded by `size`/`taille`/`sz`.
    """
    # Tier 1
    m = tokens.SIZE_NUMERIC_INCH.search(acc.text)
    if m:
        acc.out["size"] = m.group("size")
        acc.consume(m.span())
        m2 = tokens.SIZE_NUMERIC_INCH.search(acc.text) or tokens.SIZE_NUMERIC_BARE.search(acc.text)
        if m2:
            acc.ambiguities.append(
                f"multiple numeric size tokens ({acc.out['size']!r} and {m2.group('size')!r})"
            )
            acc.consume(m2.span())
        return

    # Tier 2
    m = tokens.SIZE_ALPHA.search(acc.text)
    if m:
        size = m.group("size").upper()
        if len(size) == 1 and _is_alpha_flanked(acc.text, m.span(), allow_cues=("size", "taille", "sz")):
            acc.ambiguities.append(
                f"single-letter size {size!r} flanked by alphabetical context; "
                f"could be a keyword (e.g. an initial). Parsed as size."
            )
        acc.out["size"] = size
        acc.consume(m.span())
        return

    # Tier 3
    m = tokens.SIZE_NUMERIC_BARE.search(acc.text)
    if m:
        size = m.group("size")
        # Cue check: text immediately before the match.
        prefix = acc.text[: m.start()]
        if not _BARE_DIGIT_CUE_BEFORE.search(prefix):
            acc.ambiguities.append(
                f"bare integer {size!r} parsed as size; could be a quantity, "
                f"year, or model number (no 'size'/'taille'/'sz' cue, no '\"' suffix)"
            )
        acc.out["size"] = size
        acc.consume(m.span())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_alpha_flanked(text: str, span: tuple[int, int], *, allow_cues: tuple[str, ...]) -> bool:
    """True iff the token at `span` is bounded on BOTH sides by an
    alphabetical word AND not preceded by any of the allow-listed cues
    (`size`, `taille`, `sz`, etc.). String boundaries and common
    punctuation (`:`/`,`/`/`) count as non-alpha. Used for size tokens
    where standalone-at-edge usage is normal.
    """
    a, b = span
    left = text[:a]
    right = text[b:]

    cue_re = re.compile(
        r'\b(?:' + r'|'.join(re.escape(c) for c in allow_cues) + r')\.?\s*[:=]?\s*$',
        re.IGNORECASE,
    )
    if cue_re.search(left):
        return False

    left_alpha = bool(re.search(r'[A-Za-z]\s*$', left))
    right_alpha = bool(re.search(r'^\s*[A-Za-z]', right))
    return left_alpha and right_alpha


def _is_keyword_adjacent(text: str, span: tuple[int, int], *, cue_word: str) -> bool:
    """True iff the token at `span` has an alphabetical word on EITHER side
    AND is not preceded by `cue_word`. Used for the `new` condition where
    `new york yankees` (alpha-right at start of string) is the canonical
    ambiguity.
    """
    a, b = span
    left = text[:a]
    right = text[b:]

    cue_re = re.compile(
        r'\b' + re.escape(cue_word) + r'\.?\s*[:=]?\s*$', re.IGNORECASE
    )
    if cue_re.search(left):
        return False

    left_alpha = bool(re.search(r'[A-Za-z]\s*$', left))
    right_alpha = bool(re.search(r'^\s*[A-Za-z]', right))
    return left_alpha or right_alpha


_SEP_RE = re.compile(r'[,;]+')


def _strip_separators(s: str) -> str:
    return _SEP_RE.sub(" ", s)


_WS_RE = re.compile(r'\s+')


def _collapse_ws(s: str) -> str:
    return _WS_RE.sub(" ", s).strip()
