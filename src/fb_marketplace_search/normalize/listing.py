"""Raw harvest dict -> NormalizedListing.

Defensive about missing fields per architecture §2 module 7: partial listings
are returned with None rather than raising. Validators decide what to do
with missing data per spec §3.

Listed-at parsing handles Marketplace's coarse strings: "just listed",
"X minutes/hours/days/weeks/months ago" — all relative to a reference time
(passed in for testability; defaults to UTC now).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


@dataclass(frozen=True)
class NormalizedListing:
    marketplace_id: str
    url: str
    title: Optional[str]
    description: Optional[str]
    price: Optional[float]
    currency: Optional[str]
    location: Optional[str]
    distance_km: Optional[float]
    listed_at: Optional[datetime]
    condition: Optional[str]
    seller_id: Optional[str]
    image_url: Optional[str]
    raw_blob: bytes
    position: int

    @property
    def text_for_size_match(self) -> str:
        """Concatenated title + description, used by the size validator.
        Empty pieces are skipped so trailing newlines don't matter.
        """
        parts = [p for p in (self.title, self.description) if p]
        return "\n".join(parts)


# Spec §8.2 mapping. Anything NOT matched by these patterns -> None
# (validator then fails with `no_listed_at` per spec §3).
_REL_RE = re.compile(
    r'(?P<n>\d+)\s+(?P<unit>minute|minutes|hour|hours|day|days|week|weeks)\s+ago',
    re.IGNORECASE,
)
_JUST_LISTED = re.compile(r'\b(?:just\s+listed|moments?\s+ago|today)\b', re.IGNORECASE)
# "a week ago" and "last week" both map to 7d. "1 week ago" is handled by _REL_RE.
_ONE_WEEK_LITERAL = re.compile(r'\b(?:a\s+week\s+ago|last\s+week)\b', re.IGNORECASE)


def parse_listed_at(raw: Optional[str], now: Optional[datetime] = None) -> Optional[datetime]:
    """Convert a Marketplace 'X ago' string to an absolute UTC timestamp.

    Mapping per spec §8.2 (resolves QA RECENT-8):
      - just listed / moments ago / today           -> now (0 days)
      - X minutes ago / X hours ago                 -> sub-day timestamp
      - X days ago                                  -> now - X days (literal)
      - a week ago / 1 week ago / last week         -> now - 7 days (lenient)
      - n weeks ago                                 -> now - n*7 days
      - anything else                               -> None (validator fails `no_listed_at`)

    Month-grain strings, ISO 8601, and bare `yesterday` are intentionally NOT
    on the allow-list per spec §8.2.
    """
    if not raw:
        return None
    s = raw.strip().lower()
    ref = now or datetime.now(timezone.utc)
    if _JUST_LISTED.search(s):
        return ref
    if _ONE_WEEK_LITERAL.search(s):
        return ref - timedelta(days=7)
    m = _REL_RE.search(s)
    if m:
        n = int(m.group("n"))
        unit = m.group("unit").lower()
        if unit.startswith("minute"):
            return ref - timedelta(minutes=n)
        if unit.startswith("hour"):
            return ref - timedelta(hours=n)
        if unit.startswith("day"):
            return ref - timedelta(days=n)
        if unit.startswith("week"):
            return ref - timedelta(weeks=n)
    return None


def _to_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def normalize(
    raw: dict,
    *,
    raw_blob: bytes,
    position: int,
    now: Optional[datetime] = None,
) -> NormalizedListing:
    """Project a harvested dict to a typed NormalizedListing.

    `raw` must contain at minimum `marketplace_id` and `url`; everything else
    is optional and degrades to None if absent or unparseable.
    """
    mid = raw.get("marketplace_id")
    url = raw.get("url")
    if not mid or not url:
        raise ValueError(
            f"normalize: marketplace_id and url are required (got mid={mid!r}, url={url!r})"
        )
    return NormalizedListing(
        marketplace_id=str(mid),
        url=str(url),
        title=raw.get("title") or None,
        description=raw.get("description") or None,
        price=_to_float(raw.get("price")),
        currency=raw.get("currency") or None,
        location=raw.get("location") or None,
        distance_km=_to_float(raw.get("distance_km")),
        listed_at=parse_listed_at(raw.get("listed_at"), now=now),
        condition=raw.get("condition") or None,
        seller_id=raw.get("seller_id") or None,
        image_url=raw.get("image_url") or None,
        raw_blob=raw_blob,
        position=position,
    )
