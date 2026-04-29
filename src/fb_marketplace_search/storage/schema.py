"""SQLite DDL — copied verbatim from architecture §4.

Schema migration policy: blow-away on mismatch (architect §4 / spec §6.6).
Bump SCHEMA_VERSION on any DDL change. The runtime checks the
`schema_version` table; on mismatch, prints a clear message and refuses
to run unless `FB_MARKETPLACE_DROP_ON_MIGRATE=1` is set.
"""

SCHEMA_VERSION = 1


DDL_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS listings (
        marketplace_id     TEXT PRIMARY KEY,
        url                TEXT NOT NULL,
        title              TEXT,
        description        TEXT,
        price              REAL,
        currency           TEXT,
        location           TEXT,
        distance_km        REAL,
        listed_at          TEXT,
        condition          TEXT,
        seller_id          TEXT,
        image_url          TEXT,
        raw_blob           BLOB NOT NULL,
        first_seen_at      TEXT NOT NULL,
        last_seen_at       TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_listings_last_seen
        ON listings(last_seen_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_listings_price
        ON listings(price) WHERE price IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_listings_seller
        ON listings(seller_id) WHERE seller_id IS NOT NULL
    """,
    """
    CREATE TABLE IF NOT EXISTS searches (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        query_text            TEXT NOT NULL,
        parsed_filters_json   TEXT NOT NULL,
        parsed_filters_hash   TEXT NOT NULL,
        run_at                TEXT NOT NULL,
        pages_fetched         INTEGER NOT NULL,
        total_returned        INTEGER NOT NULL,
        total_passed          INTEGER NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_searches_filters_hash_run
        ON searches(parsed_filters_hash, run_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS search_results (
        search_id                 INTEGER NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
        listing_id                TEXT NOT NULL REFERENCES listings(marketplace_id) ON DELETE CASCADE,
        position                  INTEGER NOT NULL,
        validated_pass            INTEGER NOT NULL,
        validation_failures_json  TEXT,
        PRIMARY KEY (search_id, listing_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_results_listing
        ON search_results(listing_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_results_search_passed
        ON search_results(search_id, validated_pass)
    """,
)
