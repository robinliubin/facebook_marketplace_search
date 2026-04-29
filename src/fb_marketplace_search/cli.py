"""argparse entrypoint. Wires the modules into commands.

Commands:
  fbms search "<query>"            run a search
  fbms search --stdin               read query from stdin
  fbms setup                        one-time interactive login
  fbms init-db                      idempotent: ensure DB + schema
  fbms show <listing-id>            print stored listing detail (debug)
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import Settings, ensure_home, make_settings
from .diff import compute_diff
from .diff.differ import passed_pairs_for_search
from .normalize import normalize
from .output import render_diff, render_run
from .parser import parse
from .storage import (
    SchemaMismatch,
    canonical_filters_json,
    filters_hash,
    init_db,
    listings_for_search,
    most_recent_search_with_filters_hash,
    open_db,
    record_search,
    record_search_results,
    upsert_listing,
)
from .validate import validate_all


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fbms",
        description="Validating CLI search over Facebook Marketplace.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    search_p = sub.add_parser("search", help="run a Marketplace search with validation")
    search_p.add_argument("query", nargs="?", help="free-form query string")
    search_p.add_argument("--stdin", action="store_true", help="read query from stdin")
    search_p.add_argument("--pages", type=int, default=3)
    search_p.add_argument("--db", type=Path, default=None, help="override DB path")
    search_p.add_argument("--show-rejects", action="store_true")
    search_p.add_argument("--only-new", action="store_true")
    search_p.add_argument("--debug", action="store_true", help="headful + dump raw")
    search_p.add_argument("--assume-yes", "-y", action="store_true",
                          help="don't prompt on ambiguous parse; echo the chosen interpretation to stdout for audit")
    search_p.add_argument("--min-interval", type=int, default=None,
                          help="override re-run minimum interval in seconds (default 300)")
    search_p.add_argument("--force", action="store_true",
                          help="bypass the re-run minimum interval check")

    sub.add_parser("setup", help="one-time interactive login (headful)")
    sub.add_parser("init-db", help="ensure DB + schema (idempotent)")

    show_p = sub.add_parser("show", help="print stored listing detail")
    show_p.add_argument("listing_id")
    show_p.add_argument("--db", type=Path, default=None)

    args = parser.parse_args(argv)

    if args.cmd == "search":
        return cmd_search(args)
    if args.cmd == "setup":
        return cmd_setup()
    if args.cmd == "init-db":
        return cmd_init_db()
    if args.cmd == "show":
        return cmd_show(args)
    return 2


def check_politeness_gate(
    conn,
    *,
    filters_hash_value: str,
    min_interval: int,
    force: bool,
    now=None,
) -> Optional[str]:
    """Architecture §7.7 RATE-1 gate. Returns the user-facing error message
    string when the gate blocks the run, or None when the run may proceed.

    `now` is injectable for deterministic testing.
    """
    if force:
        return None
    prior = most_recent_search_with_filters_hash(conn, filters_hash_value=filters_hash_value)
    if prior is None:
        return None
    prior_run_at = datetime.fromisoformat(prior["run_at"])
    ref = now or datetime.now(timezone.utc)
    delta = int((ref - prior_run_at).total_seconds())
    if delta < min_interval:
        return (
            f"Last run was {delta} seconds ago; minimum interval is "
            f"{min_interval}. Use --force to override."
        )
    return None


def cmd_init_db() -> int:
    settings = make_settings()
    ensure_home(settings)
    conn = open_db(settings.db_path)
    try:
        init_db(conn)
    except SchemaMismatch as exc:
        print(str(exc), file=sys.stderr)
        return 3
    finally:
        conn.close()
    print(f"DB ready at {settings.db_path}")
    return 0


def cmd_setup() -> int:
    from .driver.login import run_login_flow

    settings = make_settings(headful=True)
    ensure_home(settings)
    state_path = run_login_flow(settings)
    print(f"setup complete; state at {state_path}")
    return 0


def cmd_show(args) -> int:
    settings = make_settings(db_path=args.db)
    conn = open_db(settings.db_path)
    try:
        cur = conn.execute(
            "SELECT * FROM listings WHERE marketplace_id = ?", (args.listing_id,)
        )
        row = cur.fetchone()
        if row is None:
            print(f"no listing with id {args.listing_id}", file=sys.stderr)
            return 4
        d = dict(row)
        # raw_blob is gzipped JSON; decode for the human.
        try:
            d["raw_blob"] = json.loads(gzip.decompress(d["raw_blob"]).decode("utf-8"))
        except Exception:
            d["raw_blob"] = "<unreadable>"
        print(json.dumps(d, indent=2, default=str))
        return 0
    finally:
        conn.close()


def cmd_search(args) -> int:
    # 1. Resolve query text.
    if args.stdin:
        query_text = sys.stdin.read().strip()
    else:
        query_text = (args.query or "").strip()
    if not query_text:
        print("error: empty query (pass a string or use --stdin)", file=sys.stderr)
        return 2

    # 2. Parse.
    parsed = parse(query_text)
    if parsed.ambiguities:
        if args.assume_yes:
            # Audit-echo the chosen interpretation to stdout per spec §8.2
            # escape hatch — the user passed -y, so we proceed silently
            # but leave a record.
            print("ambiguous parse; --assume-yes accepted first-match interpretation:")
            print(_dump_parsed(parsed))
        else:
            print("Parsed filter set (with ambiguities):", file=sys.stderr)
            print(_dump_parsed(parsed), file=sys.stderr)
            if sys.stdin.isatty():
                ans = input("Proceed? (y/N): ").strip().lower()
                if ans != "y":
                    print("aborted by user", file=sys.stderr)
                    return 5
            else:
                print(
                    "non-tty + ambiguous parse; refusing without --assume-yes",
                    file=sys.stderr,
                )
                return 5

    # 3. Storage.
    settings = make_settings(
        db_path=args.db, pages=args.pages, debug=args.debug, headful=args.debug
    )
    ensure_home(settings)
    conn = open_db(settings.db_path)
    try:
        try:
            init_db(conn)
        except SchemaMismatch as exc:
            print(str(exc), file=sys.stderr)
            return 3

        # 4. Re-run politeness check (architecture §7.7 / Layer 4 / RATE-1).
        filters_json = canonical_filters_json(parsed)
        fhash = filters_hash(filters_json)
        min_interval = (
            args.min_interval
            if args.min_interval is not None
            else settings.min_interval_seconds
        )
        gate = check_politeness_gate(
            conn, filters_hash_value=fhash, min_interval=min_interval, force=args.force
        )
        if gate is not None:
            print(gate, file=sys.stderr)
            return 6

        # 5. Drive the browser.
        from .driver import open_page, run_search

        with open_page(settings) as page:
            raw_cards, pages_fetched = run_search(
                page, parsed, pages=settings.pages, settings=settings
            )

        if not raw_cards:
            print("no results", file=sys.stderr)
            # Per AT-2.5: clean exit, no DB write.
            return 0

        # 6. Normalize + persist + validate.
        listings = []
        for i, raw in enumerate(raw_cards):
            blob = gzip.compress(json.dumps(raw, default=str).encode("utf-8"))
            try:
                listings.append(normalize(raw, raw_blob=blob, position=i))
            except ValueError:
                continue

        passed_count = 0
        result_rows = []
        for listing in listings:
            upsert_listing(conn, listing)
            ok, failures = validate_all(listing, parsed)
            if ok:
                passed_count += 1
            result_rows.append(
                (
                    listing.marketplace_id,
                    listing.position,
                    ok,
                    failures,
                    listing.price,
                    listing.currency,
                )
            )

        search_id = record_search(
            conn,
            query_text=query_text,
            parsed_filters_json=filters_json,
            pages_fetched=pages_fetched,
            total_returned=len(listings),
            total_passed=passed_count,
        )
        dropped = record_search_results(conn, search_id=search_id, rows=result_rows)
        if dropped:
            print(
                f"dedup: dropped {dropped} within-run duplicate listing(s)",
                file=sys.stderr,
            )
        conn.commit()

        # 7. Output.
        rows = [dict(r) for r in listings_for_search(conn, search_id=search_id, only_passed=False)]

        # Diff if there's a prior run.
        prior_id = prior["id"] if prior else None
        if prior_id is not None:
            current_pairs = passed_pairs_for_search(conn, search_id=search_id)
            prior_pairs = passed_pairs_for_search(conn, search_id=prior_id)
            diff = compute_diff(prior_pairs, current_pairs)
            if args.only_new:
                print(render_diff(diff, only_new=True))
                return 0
            print(render_run(rows, show_rejects=args.show_rejects))
            print()
            print(render_diff(diff))
        else:
            if args.only_new:
                print("first run for these filters; nothing to diff against yet.")
            print(render_run(rows, show_rejects=args.show_rejects))
        return 0
    finally:
        conn.close()


def _dump_parsed(parsed) -> str:
    payload = {
        "keywords": parsed.keywords,
        "size": parsed.size,
        "price_min": parsed.price_min,
        "price_max": parsed.price_max,
        "distance_km": parsed.distance_km,
        "recency_days": parsed.recency_days,
        "condition": parsed.condition,
        "ambiguities": list(parsed.ambiguities),
    }
    return json.dumps(payload, indent=2)


if __name__ == "__main__":
    sys.exit(main())
