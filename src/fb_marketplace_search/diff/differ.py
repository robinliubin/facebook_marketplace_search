"""Compute NEW / STILL_THERE / GONE / PRICE_CHANGED across two searches.

Per spec §4.5 last bullet + AT-5.4: diff is computed only across listings
that pass validation in BOTH runs.

The differ is pure — it takes two lists of `(listing_id, price)` tuples (the
'passed' set of each run) and returns bucket assignments. The DB layer
extracts those tuples upstream.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Bucket(str, Enum):
    NEW = "NEW"
    STILL_THERE = "STILL_THERE"
    GONE = "GONE"
    PRICE_CHANGED = "PRICE_CHANGED"


@dataclass(frozen=True)
class PriceChange:
    listing_id: str
    old_price: Optional[float]
    new_price: Optional[float]


@dataclass(frozen=True)
class DiffResult:
    new: list[str] = field(default_factory=list)
    still_there: list[str] = field(default_factory=list)
    gone: list[str] = field(default_factory=list)
    price_changed: list[PriceChange] = field(default_factory=list)

    def bucket_of(self, listing_id: str) -> Optional[Bucket]:
        if listing_id in self.new:
            return Bucket.NEW
        if any(p.listing_id == listing_id for p in self.price_changed):
            return Bucket.PRICE_CHANGED
        if listing_id in self.still_there:
            return Bucket.STILL_THERE
        if listing_id in self.gone:
            return Bucket.GONE
        return None


def compute_diff(
    prior: list[tuple[str, Optional[float]]],
    current: list[tuple[str, Optional[float]]],
) -> DiffResult:
    """Both args are (listing_id, price). PRICE_CHANGED takes precedence over
    STILL_THERE when prices differ.
    """
    prior_map = dict(prior)
    current_map = dict(current)
    prior_ids = set(prior_map)
    current_ids = set(current_map)

    new_ids = sorted(current_ids - prior_ids)
    gone_ids = sorted(prior_ids - current_ids)
    overlap = current_ids & prior_ids

    still_there = []
    price_changes = []
    for lid in sorted(overlap):
        old = prior_map[lid]
        new = current_map[lid]
        if old != new:
            price_changes.append(PriceChange(listing_id=lid, old_price=old, new_price=new))
        else:
            still_there.append(lid)

    return DiffResult(
        new=new_ids,
        still_there=still_there,
        gone=gone_ids,
        price_changed=price_changes,
    )


def passed_pairs_for_search(
    conn: sqlite3.Connection, *, search_id: int
) -> list[tuple[str, Optional[float]]]:
    """(listing_id, price) for every validated_pass=1 row in a search."""
    cur = conn.execute(
        """
        SELECT sr.listing_id, l.price
          FROM search_results sr
          JOIN listings l ON l.marketplace_id = sr.listing_id
         WHERE sr.search_id = ? AND sr.validated_pass = 1
         ORDER BY sr.listing_id
        """,
        (search_id,),
    )
    return [(row["listing_id"], row["price"]) for row in cur.fetchall()]
