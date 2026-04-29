"""Pipeline: AND-combine all active validators against a NormalizedListing.

Returns `(validated_pass, list_of_failures)`. Failures are recorded for
EVERY failing filter, not just the first — per AT-4.2.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional

from ..normalize import NormalizedListing
from ..parser import ParsedQuery
from . import validators


@dataclass(frozen=True)
class ValidationFailure:
    filter: str
    reason: str

    def as_dict(self) -> dict:
        return asdict(self)


def validate_all(
    listing: NormalizedListing,
    query: ParsedQuery,
    *,
    now: Optional[datetime] = None,
) -> tuple[bool, list[ValidationFailure]]:
    failures: list[ValidationFailure] = []

    if query.size is not None:
        # Size is matched against title+description. Description may be None
        # at first pass; the runner handles a lazy second-pass refetch.
        outcome = validators.validate_size(listing.text_for_size_match, query.size)
        if not outcome.passed:
            failures.append(ValidationFailure(filter="size", reason=outcome.reason or ""))

    if query.price_min is not None or query.price_max is not None:
        outcome = validators.validate_price(
            listing.price,
            listing.currency,
            pmin=query.price_min,
            pmax=query.price_max,
        )
        if not outcome.passed:
            failures.append(ValidationFailure(filter="price", reason=outcome.reason or ""))

    if query.distance_km is not None:
        outcome = validators.validate_distance(listing.distance_km, max_km=query.distance_km)
        if not outcome.passed:
            failures.append(
                ValidationFailure(filter="distance", reason=outcome.reason or "")
            )

    if query.recency_days is not None:
        outcome = validators.validate_recency(
            listing.listed_at, max_days=query.recency_days, now=now
        )
        if not outcome.passed:
            failures.append(
                ValidationFailure(filter="recency", reason=outcome.reason or "")
            )

    if query.condition is not None:
        outcome = validators.validate_condition(listing.condition, target=query.condition)
        if not outcome.passed:
            failures.append(
                ValidationFailure(filter="condition", reason=outcome.reason or "")
            )

    return (len(failures) == 0, failures)
