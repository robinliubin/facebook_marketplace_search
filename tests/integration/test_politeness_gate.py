"""RATE-1a/c/d — deterministic politeness gate (architecture §7.7).

Smoke is too expensive for "did the message string match exactly" — this
hits the gate logic directly against a tmp DB with backdated `run_at` rows.
RATE-1b (the bypass-and-actually-run path) still belongs in smoke since
it requires the harvest path.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from fb_marketplace_search.cli import check_politeness_gate
from fb_marketplace_search.parser import ParsedQuery
from fb_marketplace_search.storage import (
    canonical_filters_json,
    filters_hash,
    init_db,
    open_db,
    record_search,
)


NOW = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)


def _seed_search(
    conn, *, query_text: str, filters_json: str, run_at: datetime
) -> None:
    """Insert a `searches` row with an arbitrary `run_at`, bypassing the
    `record_search` helper so we can backdate the timestamp.
    """
    conn.execute(
        """
        INSERT INTO searches (
            query_text, parsed_filters_json, parsed_filters_hash, run_at,
            pages_fetched, total_returned, total_passed
        ) VALUES (?, ?, ?, ?, 1, 0, 0)
        """,
        (
            query_text,
            filters_json,
            filters_hash(filters_json),
            run_at.isoformat(timespec="seconds"),
        ),
    )
    conn.commit()


def test_rate_1a_block_path_exact_message(tmp_path: Path):
    """RATE-1a: prior run 30s ago, default 300s interval, no --force. Gate
    must return the exact spec §7.7 wording.
    """
    conn = open_db(tmp_path / "t.sqlite")
    init_db(conn)
    fjson = canonical_filters_json(ParsedQuery(keywords="x", size="11"))
    _seed_search(
        conn,
        query_text="x size 11",
        filters_json=fjson,
        run_at=NOW - timedelta(seconds=30),
    )
    msg = check_politeness_gate(
        conn,
        filters_hash_value=filters_hash(fjson),
        min_interval=300,
        force=False,
        now=NOW,
    )
    assert msg == "Last run was 30 seconds ago; minimum interval is 300. Use --force to override."


def test_rate_1c_interval_expired_proceeds(tmp_path: Path):
    """RATE-1c: prior run 5s ago but --min-interval 2 makes the run
    legal again (5 > 2). Gate returns None.
    """
    conn = open_db(tmp_path / "t.sqlite")
    init_db(conn)
    fjson = canonical_filters_json(ParsedQuery(keywords="x", size="11"))
    _seed_search(
        conn,
        query_text="x size 11",
        filters_json=fjson,
        run_at=NOW - timedelta(seconds=5),
    )
    msg = check_politeness_gate(
        conn,
        filters_hash_value=filters_hash(fjson),
        min_interval=2,
        force=False,
        now=NOW,
    )
    assert msg is None


def test_rate_1d_different_query_proceeds(tmp_path: Path):
    """RATE-1d: prior run 10s ago for query A; current run is query B
    with a different parsed_filters_hash. Gate returns None — rate limit
    is per-hash, not global.
    """
    conn = open_db(tmp_path / "t.sqlite")
    init_db(conn)
    fjson_a = canonical_filters_json(ParsedQuery(keywords="x", size="11"))
    fjson_b = canonical_filters_json(ParsedQuery(keywords="y", size="14"))
    _seed_search(
        conn,
        query_text="x size 11",
        filters_json=fjson_a,
        run_at=NOW - timedelta(seconds=10),
    )
    msg = check_politeness_gate(
        conn,
        filters_hash_value=filters_hash(fjson_b),
        min_interval=300,
        force=False,
        now=NOW,
    )
    assert msg is None


def test_force_bypasses_gate_even_within_interval(tmp_path: Path):
    """RATE-1b's gate side: --force makes the gate return None even when
    the prior run is well within the interval. The actual harvest path is
    smoke-only since it needs a real browser.
    """
    conn = open_db(tmp_path / "t.sqlite")
    init_db(conn)
    fjson = canonical_filters_json(ParsedQuery(keywords="x", size="11"))
    _seed_search(
        conn,
        query_text="x size 11",
        filters_json=fjson,
        run_at=NOW - timedelta(seconds=10),
    )
    msg = check_politeness_gate(
        conn,
        filters_hash_value=filters_hash(fjson),
        min_interval=300,
        force=True,
        now=NOW,
    )
    assert msg is None


def test_no_prior_search_proceeds(tmp_path: Path):
    """First-ever run for a given filter set: nothing to compare against,
    gate must allow it.
    """
    conn = open_db(tmp_path / "t.sqlite")
    init_db(conn)
    fjson = canonical_filters_json(ParsedQuery(keywords="x", size="11"))
    msg = check_politeness_gate(
        conn,
        filters_hash_value=filters_hash(fjson),
        min_interval=300,
        force=False,
        now=NOW,
    )
    assert msg is None
