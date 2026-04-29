# facebook_marketplace_search — v1 Architecture

Status: Draft v1
Owner: architect
Audience: developer (#4), qa-tester (#3), product-manager
Companion doc: [specs/v1.md](../specs/v1.md)

---

## 1. Stack choice

**Chosen stack: Python 3.12, managed with `uv`, browser automation via Camoufox (Playwright-compatible anti-detection Firefox), persistence via `sqlite3` stdlib (synchronous), CLI via `argparse` or `click`.**

Justification (one paragraph): the wedge of v1 is a single-shot, single-user CLI that has to coexist with Marketplace's aggressive bot fingerprinting and login wall. We have two sibling projects to learn from: `appointmaker/` (vanilla Playwright + persistent storage state, simple synchronous flow, good enough for a private-but-non-hostile site like Costco) and `jobhuntingagent/` (Camoufox `BrowserPool` + async SQLAlchemy + EventBus, hardened for hostile job-board scraping). Marketplace is much closer to the second class of target than the first — same parent company that runs the site also runs the detection — so we adopt Camoufox as the proven anti-bot driver. We deliberately *do not* adopt jobhuntingagent's full async/dashboard/EventBus stack: v1 is one shot, no daemon, no UI, no LLM, so async I/O and SQLAlchemy are pure overhead. The result is "jobhuntingagent's browser layer + appointmaker's CLI shape" — Camoufox where the hostility lives, simple synchronous Python everywhere else. Node + Puppeteer-stealth was rejected: no existing patterns in this repo, and we'd be re-deriving anti-bot tuning from scratch for no upside.

A note on future stack drift: if v1.x ever needs concurrent multi-query runs, swap `sqlite3` for the async pattern from jobhuntingagent. Until then, synchronous is right.

## 2. Module breakdown

All modules live under `src/fb_marketplace_search/`. One Python package, no plugin system, no abstract registries (we have exactly one search target).

```
src/fb_marketplace_search/
  __init__.py
  cli.py                 # entrypoint: argparse, wires everything, prints output
  config.py              # paths, defaults, env loading; no business logic
  parser/
    __init__.py
    query_parser.py      # free-form query string -> ParsedQuery (filters + keywords)
    tokens.py            # regex catalog: size, price, distance, recency, condition
  driver/
    __init__.py
    browser.py           # Camoufox launcher, storage_state load/save, headful/headless toggle
    login.py             # one-time interactive login, persists state to ~/.fb_marketplace_search/state.json
    search_runner.py     # navigate to /marketplace, set Marketplace-side filters, paginate, harvest
    selectors.py         # all CSS/XPath selectors in one file; the canary that breaks first
  normalize/
    __init__.py
    listing.py           # raw HTML/JSON snippet -> NormalizedListing dataclass (typed fields)
  validate/
    __init__.py
    validators.py        # one function per filter; each returns Pass | Fail(reason)
    pipeline.py          # runs all active validators against a listing, AND-combined
  storage/
    __init__.py
    schema.py            # CREATE TABLE DDL, schema_version constant
    db.py                # connection helper, init_db, upsert_listing, record_search, diff_query
  diff/
    __init__.py
    differ.py            # compute NEW / STILL_THERE / GONE / PRICE_CHANGED across two searches
  output/
    __init__.py
    formatter.py         # console rendering of accepted listings, --show-rejects, --only new
tests/
  unit/                  # parser, validators, normalizer — no browser
  fixtures/              # captured HTML samples of Marketplace listing cards
  smoke/                 # opt-in real-Marketplace test, marker excluded by default (mirrors appointmaker)
scripts/
  setup.py               # interactive: launch headful Camoufox, user logs in, save storage_state
pyproject.toml           # uv-managed; deps: camoufox, playwright, click (or argparse), python-dateutil
```

Module responsibilities, in dependency order:

1. **`config`** — resolves paths (`~/.fb_marketplace_search/` by default, override via `FB_MARKETPLACE_HOME`), loads sentinel constants (default `--pages`, default min-rerun interval, user-agent locale). No I/O on import.
2. **`parser`** — pure functions, no I/O. `parse(query: str) -> ParsedQuery`. The token regex catalog is the single source of truth for what v1 understands as a filter. Tested entirely with unit tests; no browser needed.
3. **`driver.browser`** — wraps Camoufox launch, loads `state.json` if present (else raises a clear "run setup.py first" error), exposes a context-manager `open_page()` that yields a Playwright `Page`. Headless by default, headful when `debug=True`.
4. **`driver.login`** — one-time flow: launch headful, navigate to facebook.com/login, wait until the user manually logs in and the post-login DOM appears, save `storage_state` to disk. Mirrors `appointmaker/scripts/setup.py`.
5. **`driver.search_runner`** — given a `ParsedQuery`, drives the page: builds the search URL (Marketplace supports a lot of filters as URL query params — prefer URL over click-driven filtering for determinism), scrolls/paginates, harvests result cards into raw dicts. **Does not normalize.**
6. **`driver.selectors`** — every CSS/XPath selector and every URL-param key lives here. When Marketplace breaks us, this is the file we edit.
7. **`normalize`** — raw harvest dict → `NormalizedListing` (strict types, parsed numbers, ISO dates). Defensive about missing fields — partial listings are returned with `None`s rather than raising; the validator handles missing data per spec §3.
8. **`validate`** — one validator per filter (`validate_size`, `validate_price`, `validate_distance`, `validate_recency`, `validate_condition`). Each returns `ValidationOutcome(passed: bool, reason: str | None)`. `pipeline.validate_all()` runs the active set, AND-combines, returns `(passed, [failure_reasons])`. **This module is the wedge — must be 100% unit-tested with adversarial fixtures from spec §3.**
9. **`storage`** — synchronous `sqlite3` with WAL mode and `PRAGMA foreign_keys=ON`. `init_db()` checks `schema_version` table; if mismatch and `FB_MARKETPLACE_DROP_ON_MIGRATE=1` (or it's a fresh DB), runs full DDL. See §4.
10. **`diff`** — joins the current `search_results` against the most recent prior `searches` row with the same `parsed_filters_hash` and produces buckets per spec Story 5. Buckets `NEW`/`STILL_THERE`/`GONE`/`PRICE_CHANGED` are computed only over `validated_pass=true` rows on both sides.
11. **`output.formatter`** — pure rendering of accepted/rejected listings. No business logic.
12. **`cli`** — argparse + dispatch. Commands: `search "query…"` (default), `setup` (one-time login), `init-db` (idempotent), `show <listing-id>` (debug; print raw_blob).

Two cross-cutting design rules:
- **No global singletons.** Pass `Settings`, `Connection`, and `Page` explicitly. Keeps unit tests trivial. Diverges from jobhuntingagent's `get_settings()` pattern — appropriate because we have no long-lived process.
- **`raw_blob` is sacred.** Every harvested card is stored byte-for-byte (gzipped JSON of the network response or HTML fragment). When Marketplace changes its DOM and our normalizer breaks, we backfill from `raw_blob`. This is the audit trail referenced by spec §4 acceptance criteria.

## 3. Data flow

```
                              ┌─────────────────────┐
   user CLI invocation        │  cli.py (argparse)  │
   "gants hockey 11", new,…  ─►  dispatch: search   │
                              └──────────┬──────────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │ parser.query_parser │   pure function
                              │   tokens.py regex   │   (no I/O)
                              └──────────┬──────────┘
                                         │ ParsedQuery
                                         │   { keywords: "gants hockey 11"",
                                         │     filters: { size:'11', price:(50,100),
                                         │                distance_km:10, days:7,
                                         │                condition:'new' } }
                                         ▼
                              ┌─────────────────────┐
                              │ driver.browser      │ load storage_state
                              │  + search_runner    │ build URL with FB filter params
                              └──────────┬──────────┘ scroll / paginate
                                         │ raw cards (list[dict])
                                         ▼
                              ┌─────────────────────┐
                              │ normalize.listing   │ raw -> NormalizedListing
                              └──────────┬──────────┘ (typed; missing→None)
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │ storage.upsert      │ idempotent on marketplace_id
                              │   listings table    │ updates last_seen_at, price
                              └──────────┬──────────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │ validate.pipeline   │ AND-combine validators
                              │   per spec §3        │ per-listing pass/fail+reasons
                              └──────────┬──────────┘
                                         │
                                         ▼  (lazy 2nd pass: re-fetch description
                                         │   only for listings whose title alone
                                         │   can't conclusively pass/fail size;
                                         │   re-validate just those)
                                         ▼
                              ┌─────────────────────┐
                              │ storage.record      │ writes search row +
                              │   search_results    │ search_results rows
                              └──────────┬──────────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │ diff.differ         │ vs. prior search w/ same
                              │                     │ parsed_filters_hash
                              └──────────┬──────────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │ output.formatter    │ stdout (accepted by default)
                              │                     │ --show-rejects / --only new
                              └─────────────────────┘
```

## 4. SQLite schema

Synchronous `sqlite3` from stdlib, WAL journal mode, `PRAGMA foreign_keys=ON`. Schema is intentionally narrow; spec Story 3 sketch is the floor, this is the actual DDL.

```sql
-- schema_version sentinel; bumped on any DDL change. v1 policy = blow away on mismatch.
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
INSERT OR IGNORE INTO schema_version(version) VALUES (1);

CREATE TABLE IF NOT EXISTS listings (
    marketplace_id     TEXT PRIMARY KEY,           -- FB's listing id; canonical key
    url                TEXT NOT NULL,
    title              TEXT,
    description        TEXT,                       -- nullable: lazy 2nd-pass fetch
    price              REAL,
    currency           TEXT,                       -- 'CAD' / 'USD' / null
    location           TEXT,
    distance_km        REAL,
    listed_at          TEXT,                       -- ISO 8601 UTC; null if FB didn't return it
    condition          TEXT,                       -- 'new'|'used-like-new'|... |null
    seller_id          TEXT,
    image_url          TEXT,
    raw_blob           BLOB NOT NULL,              -- gzipped JSON of source-of-truth payload
    first_seen_at      TEXT NOT NULL,              -- ISO 8601 UTC, never updated
    last_seen_at       TEXT NOT NULL               -- ISO 8601 UTC, updated every re-sight
);

CREATE INDEX IF NOT EXISTS idx_listings_last_seen
    ON listings(last_seen_at);                     -- for "what did we see recently"
CREATE INDEX IF NOT EXISTS idx_listings_price
    ON listings(price) WHERE price IS NOT NULL;    -- partial: skips listings w/o price
CREATE INDEX IF NOT EXISTS idx_listings_seller
    ON listings(seller_id) WHERE seller_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS searches (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    query_text            TEXT NOT NULL,           -- raw user input
    parsed_filters_json   TEXT NOT NULL,           -- canonical JSON (sorted keys)
    parsed_filters_hash   TEXT NOT NULL,           -- sha256(parsed_filters_json) for diff key
    run_at                TEXT NOT NULL,           -- ISO 8601 UTC
    pages_fetched         INTEGER NOT NULL,
    total_returned        INTEGER NOT NULL,        -- before validation
    total_passed          INTEGER NOT NULL         -- after validation
);

CREATE INDEX IF NOT EXISTS idx_searches_filters_hash_run
    ON searches(parsed_filters_hash, run_at DESC); -- diff lookup: "most recent prior with same filters"

CREATE TABLE IF NOT EXISTS search_results (
    search_id                 INTEGER NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
    listing_id                TEXT NOT NULL REFERENCES listings(marketplace_id) ON DELETE CASCADE,
    position                  INTEGER NOT NULL,    -- order Marketplace returned it
    validated_pass            INTEGER NOT NULL,    -- 0/1
    validation_failures_json  TEXT,                -- '[{"filter":"size","reason":"..."}]' if failed; null if passed
    PRIMARY KEY (search_id, listing_id)
);

CREATE INDEX IF NOT EXISTS idx_results_listing
    ON search_results(listing_id);                 -- "every search that returned this listing" (diff side)
CREATE INDEX IF NOT EXISTS idx_results_search_passed
    ON search_results(search_id, validated_pass);  -- "passing rows in this search" (default output)
```

Index rationale (briefly, since it's the part that ages worst):
- `idx_listings_last_seen` — supports a future "what's stale, prune it" job; cheap.
- `idx_listings_price` is **partial** (`WHERE price IS NOT NULL`) — most diff/aggregation queries that touch price will naturally exclude nulls, partial index keeps it small.
- `idx_searches_filters_hash_run DESC` is the **diff hot path**: finding the most recent prior search with identical filters is one O(log n) lookup, not a scan.
- `idx_results_search_passed` accelerates the default "show only passing rows of this run" CLI render — covering enough that SQLite can use index-only scans for the count badges.

Schema migration policy: per product preference and spec §6.6 — **blow-away on schema mismatch.** v1 reads `schema_version` on `init_db()`; if absent or != current, prints "schema changed; rerun with FB_MARKETPLACE_DROP_ON_MIGRATE=1 to recreate (this deletes your cache)". No Alembic, no in-place ALTERs. Document this clearly in the user-facing README so that no one cries when their cache vanishes.

## 5. Anti-bot strategy

**Layer 1 — driver.** Camoufox (the same library jobhuntingagent uses) for all Marketplace traffic. Camoufox is a hardened Firefox build that ships with a randomized fingerprint stack (canvas, fonts, webgl, navigator) that vanilla Playwright Chromium cannot match. We piggyback on jobhuntingagent's vetted version pin — copy whatever it has in its `pyproject.toml` rather than deriving fresh.

**Layer 2 — session reuse.** One-time interactive login via `scripts/setup.py` (mirrors `appointmaker/scripts/setup.py`). Headful Camoufox, user logs in by hand, we save Playwright's `storage_state` to `~/.fb_marketplace_search/state.json`. Every subsequent `search` invocation loads that state, so the bot never sees a fresh-cookie session — it sees a continuing one. This is product preference §6.1(b) and is correct.

**Layer 3 — headful/headless policy.** Per product §6.3:
- `setup` (login flow) → always headful. Required so the user can log in; also coincidentally less detectable.
- `search` default → headless.
- `search --debug` → headful (also enables a longer timeout and dumps `raw_blob` to disk for offline inspection).

**Layer 4 — pacing.** Inside one search run, we use Camoufox-style human-ish delays between scrolls (jitter on top of jobhuntingagent's defaults — don't re-derive). Across runs of the **same query**, enforce a minimum interval (default 5 minutes; configurable via `--min-interval`). Per product §6.7: this is polite, and more importantly it kills any user temptation to put `while true; do search …; done` in a loop. Implementation: check `searches.run_at` for most-recent row with same `parsed_filters_hash`; if delta < min interval, refuse with a clear error rather than running.

**Layer 5 — failure modes.**
- HTTP 429 / "Too many requests" interstitial → exponential backoff: 30s, 90s, 300s, then bail. Log `rate_limited` and exit non-zero. Do **not** retry indefinitely — partial data is worse than no data.
- "Please log in again" wall (storage_state went stale) → exit non-zero with a clear "run `setup` again" message. Do not attempt to drive the login form headlessly.
- DOM selector miss (zero result cards parsed where we expected ≥1) → write the page HTML to `~/.fb_marketplace_search/last_failure.html`, exit with `selector_drift` error. This is an early-warning canary for §6 risk #1.

**Layer 6 — pagination.** Marketplace uses **infinite scroll**, not numbered pages. `--pages N` is a soft target: scroll N viewport-heights worth, then stop. Each scroll waits for either new card nodes to mount or a 5s idle timeout, whichever comes first. We do not try to deep-link to "page 3" — there is no such URL.

**Layer 7 — description harvest (§6.5).** Lazy second pass, per product preference. After the first-pass title-only validation, build a list of `needs_description` listings (size validator returned `inconclusive` because the title contained no parseable size token). Re-open each in the same browser context, harvest the description, re-run the size validator. Cap the second pass at 25 listings per search (configurable) — past that we'd be making the run twice as slow for diminishing returns.

## 6. Risk register

Top three fragile assumptions, ordered by P(breaks within 6 months) × blast radius.

1. **Marketplace selector drift.** Every CSS/XPath we depend on (search box, filter dropdowns, listing card grid, listing detail description) is a string Meta can change. *Likelihood:* near-certain to break at least one. *Impact:* total — search returns zero cards. *Mitigation:* (a) all selectors centralized in `driver/selectors.py` (one file to edit); (b) the `selector_drift` canary in Layer 5 surfaces it on the first failed run rather than silently returning empty; (c) `raw_blob` lets us recover historical data after we patch; (d) capture HTML fixtures in `tests/fixtures/` from real runs and write a parser unit test against each — fixture-based tests catch drift in CI before users hit it.

2. **Login storage_state expires faster than we expect.** Meta is known to invalidate sessions aggressively for accounts that show automation-y patterns, even if Camoufox masks the fingerprint. *Likelihood:* moderate (weeks to months per session). *Impact:* user has to re-run `setup`. *Mitigation:* (a) clear "run setup again" message on the auth-wall failure mode, no silent retries; (b) document expected re-login cadence in the user README; (c) per spec §1, this is single-user single-machine so we never grow a pool of sessions to refresh — keeping it deliberately small reduces the "looks like a bot farm" signal.

3. **Size-validator false negatives on free-form titles.** The wedge depends on the size validator hitting 100% precision (per spec §5). The risk is at the *recall* end: a listing genuinely IS size 11 but the title encodes it as `taille 11`, `sz11`, `eleven`, `XI`, etc., and the description is gated behind a click. *Likelihood:* moderate — bilingual Quebec listings are normal, and our spec only enumerates `11`, `11"`, `11 inch`. *Impact:* user sees an emptier list than reality, secondary metric (false-negative rate) goes up but **primary metric stays at 100%** because we never *show* a wrong listing. *Mitigation:* (a) the lazy-description-pass (§5 Layer 7) catches most cases since descriptions are wordier than titles; (b) ship `--show-rejects` from day one so the user can spot-check rejects and feed examples back as test fixtures; (c) accept this is a recall tradeoff explicitly — spec §5 tolerates it (false-negative rate is logged, not gated).

(Notable runner-up not in the top 3: clock skew on `listed_at` parsing for "X days ago" strings around midnight UTC. Spec §5 already gives recency a 95% target — we're covered. Worth a single timezone unit-test fixture, nothing more.)

## 7. Open questions / spec ambiguities flagged back to product

These are minor — the spec is solid. Filing them rather than blocking on them; defaults below are what the developer should ship unless product responds otherwise before #4 starts.

1. **Re-validation on every re-run, or trust prior validation?** When `STILL_THERE` listings come back unchanged, do we re-run validators against them or trust the prior `validated_pass`? Default decision: **re-validate every run.** Validators are pure and cheap; trusting cached results means a validator bug fix doesn't take effect for cached listings. Spec didn't say either way.
2. **Distance unit on display.** Spec §3 specifies km in the filter; spec doesn't say what the CLI prints. Default decision: **always display km** (project is Montreal/QC-region, consistent with the filter input).
3. **Currency.** Spec §3 says CAD. Default decision: **assume CAD; if FB returns a non-CAD currency on a listing, that listing fails the price filter with reason `currency_mismatch`.** Cheaper than an FX layer.
4. **What constitutes "ambiguous parse" in Story 1?** The spec asks for a y/N confirmation when parsing is ambiguous, but doesn't define the trigger. Default decision: ambiguous = (a) two filters of the same type detected (e.g., two distance tokens), or (b) a token matched a filter regex but also looks like it could be a keyword (e.g., the word `new` in `new york yankees`). When in doubt, prompt.
5. **`--only new` semantics on first-ever run for a given parsed filter set.** Diff has no prior run to compare to. Default decision: print everything and a one-line note "first run for these filters; nothing to diff against yet."
6. **Within-run duplicate listings (raised by QA test DIFF-7).** Marketplace can return the same `marketplace_id` on two different pages of a single harvest. Decision: **`search_results` has `PRIMARY KEY (search_id, listing_id)`, so within-run dups collapse to one row at the schema level — no application logic required.** The retained row keeps the *first* `position` we encountered (use `INSERT OR IGNORE` on duplicates, not `OR REPLACE`); rationale is that a listing's "rank" is its earliest appearance, and Marketplace re-showing it later is just recency-weighted UI noise. The de-dup is logged once per run as `dedup: dropped N within-run duplicate listings` so it's visible to anyone debugging an unexpected count.
7. **Rate-limit on re-run of the same query (spec §6 Q7, raised by QA test RATE-1).** Decision: **default 5-minute minimum interval between runs of the same `parsed_filters_hash`; configurable via `--min-interval` (seconds), bypass with `--force`.** Implementation: before issuing the search, query `MAX(run_at) WHERE parsed_filters_hash = ?`; if `now - max_run_at < min_interval`, exit with non-zero and a clear "Last run was N seconds ago; minimum interval is M. Use --force to override." This is also restated in §5 Layer 4 (where it lives operationally) — repeating it here so QA has one place to point RATE-1 at.
8. **Currency mismatch (raised by QA test PRICE-10).** Decision: already in §7.3 — listing price in a non-CAD currency fails the price filter with `validation_failures_json` reason `currency_mismatch`. Restating here so QA can map PRICE-10 directly to this ruling.

If product disagrees with any of these defaults, ping back **before** developer starts #4 — none of them are deep enough to need a re-spec.

---

## Appendix: deviations from sibling projects, called out

For developer reviewing #4: where this design intentionally diverges from the sibling we're closest to (`jobhuntingagent/`), and why:

- **No async, no SQLAlchemy, no ChromaDB.** v1 is one shot. Async I/O and an ORM buy nothing here.
- **No EventBus, no FastAPI dashboard.** CLI only per spec §2.
- **No `get_settings()` / `get_browser_pool()` singletons.** Pass dependencies explicitly. Easier to test. Re-introduce singletons if v1.x grows a daemon.
- **Synchronous `sqlite3` from stdlib**, not async SQLAlchemy. Keep imports tiny.
- **One scraper target, not an adapter pattern.** Marketplace is the only target. Resist the temptation to write `BoardAdapter` ABC for one implementation.

What we DO take wholesale from jobhuntingagent: the Camoufox version pin, the human-delay pacing primitives, the WAL-mode SQLite setup. Lift, don't rewrite.

What we take wholesale from appointmaker: the `scripts/setup.py` interactive-login pattern and the `pytest -m smoke` real-site test marker (excluded from default `pytest`).
