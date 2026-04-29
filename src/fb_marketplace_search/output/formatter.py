"""Console rendering. Pure: takes data, returns strings.

Default output: only validated_pass=True listings, in position order.
`--show-rejects`: also dumps rejects with reason annotations.
`--only new`: applies after diff, returns only NEW.
"""

from __future__ import annotations

import json
from typing import Iterable, Optional

from ..diff import Bucket, DiffResult


def _fmt_price(p: Optional[float], currency: Optional[str]) -> str:
    if p is None:
        return "(no price)"
    cur = currency or "CAD"
    return f"{cur} {p:g}"


def _fmt_distance(km: Optional[float]) -> str:
    return f"{km:g} km" if km is not None else "(no distance)"


def render_run(
    rows: list[dict],
    *,
    show_rejects: bool = False,
) -> str:
    """`rows`: list of dicts with keys position, validated_pass (0/1),
    validation_failures_json, marketplace_id, title, url, price, currency,
    distance_km, location.
    """
    if not rows:
        return "(no results)"

    accepted = [r for r in rows if r.get("validated_pass")]
    rejected = [r for r in rows if not r.get("validated_pass")]

    lines: list[str] = []
    if not accepted:
        lines.append("No listings passed validation.")
    else:
        lines.append(f"=== {len(accepted)} listing(s) passed validation ===")
        for r in accepted:
            lines.append(_fmt_row(r))

    if show_rejects and rejected:
        lines.append("")
        lines.append(f"=== {len(rejected)} listing(s) rejected ===")
        for r in rejected:
            failures = r.get("validation_failures_json")
            reasons = ""
            if failures:
                try:
                    parsed = json.loads(failures)
                    reasons = ", ".join(f"{f['filter']}:{f['reason']}" for f in parsed)
                except (ValueError, KeyError):
                    reasons = failures
            lines.append(_fmt_row(r) + f"   [REJECT: {reasons}]")

    return "\n".join(lines)


def _fmt_row(r: dict) -> str:
    pos = r.get("position", "?")
    title = (r.get("title") or "").strip() or "(no title)"
    return (
        f"  [{pos:>3}] {title[:70]:<70}  "
        f"{_fmt_price(r.get('price'), r.get('currency')):>14}  "
        f"{_fmt_distance(r.get('distance_km')):>10}  "
        f"{r.get('url', '')}"
    )


def render_diff(diff: DiffResult, *, only_new: bool = False) -> str:
    if only_new:
        if not diff.new:
            return "(no NEW listings since last run)"
        return "\n".join(["=== NEW ==="] + [f"  {lid}" for lid in diff.new])
    parts = []
    if diff.new:
        parts.append("=== NEW ===\n" + "\n".join(f"  {lid}" for lid in diff.new))
    if diff.price_changed:
        parts.append(
            "=== PRICE_CHANGED ===\n"
            + "\n".join(
                f"  {p.listing_id}  {p.old_price} -> {p.new_price}"
                for p in diff.price_changed
            )
        )
    if diff.still_there:
        parts.append("=== STILL_THERE ===\n" + "\n".join(f"  {lid}" for lid in diff.still_there))
    if diff.gone:
        parts.append("=== GONE ===\n" + "\n".join(f"  {lid}" for lid in diff.gone))
    return "\n\n".join(parts) if parts else "(no diff)"
