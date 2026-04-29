"""Synchronous sqlite3 helpers. WAL journal, foreign keys ON.

All functions take an explicit Connection — no module-level singleton (per
architect cross-cutting rule "no global singletons").
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from ..normalize import NormalizedListing
from ..parser import ParsedQuery
from ..validate import ValidationFailure
from .schema import DDL_STATEMENTS, SCHEMA_VERSION


class SchemaMismatch(RuntimeError):
    """Raised when the on-disk DB schema_version != current SCHEMA_VERSION
    and FB_MARKETPLACE_DROP_ON_MIGRATE is not set.
    """


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def open_db(db_path: Path) -> sqlite3.Connection:
    """Open (or create) the DB. Caller is responsible for `init_db` after
    a fresh open if they need schema guarantees.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist; verify schema_version."""
    existing = _read_schema_version(conn)
    if existing is None:
        # Fresh DB.
        for stmt in DDL_STATEMENTS:
            conn.execute(stmt)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,)
        )
        conn.commit()
        return

    if existing != SCHEMA_VERSION:
        if os.environ.get("FB_MARKETPLACE_DROP_ON_MIGRATE") == "1":
            _drop_all(conn)
            for stmt in DDL_STATEMENTS:
                conn.execute(stmt)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version(version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
            conn.commit()
            return
        raise SchemaMismatch(
            f"on-disk schema_version={existing}, code expects {SCHEMA_VERSION}. "
            "Rerun with FB_MARKETPLACE_DROP_ON_MIGRATE=1 to recreate (this deletes your cache)."
        )

    # Schema is current. Still run CREATE IF NOT EXISTS to repair missing
    # indexes (cheap, idempotent).
    for stmt in DDL_STATEMENTS:
        conn.execute(stmt)
    conn.commit()


def _read_schema_version(conn: sqlite3.Connection) -> Optional[int]:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    )
    if cur.fetchone() is None:
        return None
    cur = conn.execute("SELECT version FROM schema_version LIMIT 1")
    row = cur.fetchone()
    return int(row[0]) if row else None


def _drop_all(conn: sqlite3.Connection) -> None:
    for tbl in ("search_results", "searches", "listings", "schema_version"):
        conn.execute(f"DROP TABLE IF EXISTS {tbl}")
    conn.commit()


def upsert_listing(conn: sqlite3.Connection, listing: NormalizedListing) -> None:
    """Insert or update by marketplace_id. `first_seen_at` set on insert,
    `last_seen_at` advanced on every call. All other fields refreshed.
    """
    now = _now_iso()
    listed_at_iso = listing.listed_at.isoformat(timespec="seconds") if listing.listed_at else None
    conn.execute(
        """
        INSERT INTO listings (
            marketplace_id, url, title, description, price, currency, location,
            distance_km, listed_at, condition, seller_id, image_url, raw_blob,
            first_seen_at, last_seen_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(marketplace_id) DO UPDATE SET
            url=excluded.url,
            title=excluded.title,
            description=COALESCE(excluded.description, listings.description),
            price=excluded.price,
            currency=excluded.currency,
            location=excluded.location,
            distance_km=excluded.distance_km,
            listed_at=COALESCE(excluded.listed_at, listings.listed_at),
            condition=COALESCE(excluded.condition, listings.condition),
            seller_id=COALESCE(excluded.seller_id, listings.seller_id),
            image_url=COALESCE(excluded.image_url, listings.image_url),
            raw_blob=excluded.raw_blob,
            last_seen_at=excluded.last_seen_at
        """,
        (
            listing.marketplace_id,
            listing.url,
            listing.title,
            listing.description,
            listing.price,
            listing.currency,
            listing.location,
            listing.distance_km,
            listed_at_iso,
            listing.condition,
            listing.seller_id,
            listing.image_url,
            listing.raw_blob,
            now,
            now,
        ),
    )


def canonical_filters_json(query: ParsedQuery) -> str:
    """Stable JSON of the filter portion of a ParsedQuery (NOT keywords).

    Diff joins on this exact string, so it must be deterministic across runs.
    Sorted keys; `None` fields included so explicit absence stays explicit.
    """
    payload = {
        "size": query.size,
        "price_min": query.price_min,
        "price_max": query.price_max,
        "distance_km": query.distance_km,
        "recency_days": query.recency_days,
        "condition": query.condition,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def filters_hash(filters_json: str) -> str:
    return hashlib.sha256(filters_json.encode("utf-8")).hexdigest()


def record_search(
    conn: sqlite3.Connection,
    *,
    query_text: str,
    parsed_filters_json: str,
    pages_fetched: int,
    total_returned: int,
    total_passed: int,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO searches (
            query_text, parsed_filters_json, parsed_filters_hash, run_at,
            pages_fetched, total_returned, total_passed
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            query_text,
            parsed_filters_json,
            filters_hash(parsed_filters_json),
            _now_iso(),
            pages_fetched,
            total_returned,
            total_passed,
        ),
    )
    return int(cur.lastrowid)


def record_search_results(
    conn: sqlite3.Connection,
    *,
    search_id: int,
    rows: Iterable[tuple[str, int, bool, list[ValidationFailure], Optional[float], Optional[str]]],
) -> int:
    """rows: iterable of (listing_id, position, validated_pass, failures_list,
    price_at_search, currency_at_search).

    Returns the count of rows dropped as within-run duplicates. Per
    architecture §7.6: ON CONFLICT IGNORE retains the earliest-seen position.

    `price_at_search`/`currency_at_search` snapshot the listing's price at
    the moment this search ran. listings.price gets overwritten on every
    UPSERT, so without these per-search columns the diff loses the price
    history needed for the PRICE_CHANGED bucket (bug #6 / AT-5.2).
    """
    payload = []
    for listing_id, position, passed, failures, price_at, currency_at in rows:
        failures_json = (
            json.dumps([f.as_dict() for f in failures], separators=(",", ":"))
            if failures
            else None
        )
        payload.append(
            (
                search_id,
                listing_id,
                position,
                1 if passed else 0,
                failures_json,
                price_at,
                currency_at,
            )
        )
    if not payload:
        return 0
    before = conn.execute(
        "SELECT COUNT(*) FROM search_results WHERE search_id = ?", (search_id,)
    ).fetchone()[0]
    conn.executemany(
        """
        INSERT OR IGNORE INTO search_results (
            search_id, listing_id, position, validated_pass, validation_failures_json,
            price_at_search, currency_at_search
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        payload,
    )
    after = conn.execute(
        "SELECT COUNT(*) FROM search_results WHERE search_id = ?", (search_id,)
    ).fetchone()[0]
    inserted = after - before
    return len(payload) - inserted


def most_recent_search_with_filters_hash(
    conn: sqlite3.Connection, *, filters_hash_value: str, before_search_id: Optional[int] = None
) -> Optional[sqlite3.Row]:
    """Return the most recent prior `searches` row with the given filters_hash.

    `before_search_id` excludes the current run's own row.
    """
    if before_search_id is not None:
        cur = conn.execute(
            """
            SELECT * FROM searches
            WHERE parsed_filters_hash = ? AND id < ?
            ORDER BY run_at DESC
            LIMIT 1
            """,
            (filters_hash_value, before_search_id),
        )
    else:
        cur = conn.execute(
            """
            SELECT * FROM searches
            WHERE parsed_filters_hash = ?
            ORDER BY run_at DESC
            LIMIT 1
            """,
            (filters_hash_value,),
        )
    return cur.fetchone()


def listings_for_search(
    conn: sqlite3.Connection, *, search_id: int, only_passed: bool = True
) -> list[sqlite3.Row]:
    """Join search_results to listings, optionally filtered to validated_pass=1."""
    if only_passed:
        cur = conn.execute(
            """
            SELECT sr.position, sr.validated_pass, sr.validation_failures_json,
                   l.*
              FROM search_results sr
              JOIN listings l ON l.marketplace_id = sr.listing_id
             WHERE sr.search_id = ? AND sr.validated_pass = 1
             ORDER BY sr.position
            """,
            (search_id,),
        )
    else:
        cur = conn.execute(
            """
            SELECT sr.position, sr.validated_pass, sr.validation_failures_json,
                   l.*
              FROM search_results sr
              JOIN listings l ON l.marketplace_id = sr.listing_id
             WHERE sr.search_id = ?
             ORDER BY sr.position
            """,
            (search_id,),
        )
    return cur.fetchall()
