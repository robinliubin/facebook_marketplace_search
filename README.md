# facebook_marketplace_search

Validating CLI search over Facebook Marketplace. Runs your search through Marketplace's own filters, then **re-validates every returned listing against your filters** so that a `size 11` query never shows you sizes 7 / 14 / 15.

## Why

Marketplace's native search treats numeric size tokens as loose keywords, so it returns size 7 and 14 listings for a size-11 query. Distance and "listed within" are advisory, condition is often mistagged, and price filters miss listings whose price is in the description. This tool is **post-search filter validation**: it drops every listing whose actual attributes violate the user's stated filters before showing results.

## What it does

1. Parses one free-form query line (`gants hockey 11", new, 10km, $50-100, listed in 1 week`) into structured filters.
2. Runs the real Marketplace search via Camoufox (anti-bot Firefox).
3. Persists every seen listing in local SQLite for diff-on-rerun.
4. Re-validates each listing against the parsed filters; drops violators with a recorded reason.
5. Default output shows only listings that genuinely match. `--show-rejects` shows the dropped listings and why.

## Install

Requires Python 3.12+ and [`uv`](https://docs.astral.sh/uv/).

```bash
cd facebook_marketplace_search
uv venv --python 3.12
uv pip install -e ".[dev]"
.venv/bin/python -m playwright install firefox    # Camoufox runs on top of Playwright Firefox
```

## One-time login

Marketplace shows partial results to logged-out browsers. Run the interactive setup once — a Firefox window will open, you log in by hand, and the tool persists session state to `~/.fb_marketplace_search/state.json`.

```bash
.venv/bin/fbms setup
```

You'll be prompted to re-run this if Meta invalidates your session (typically every few weeks).

## Run a search

```bash
.venv/bin/fbms search 'gants hockey 11", new, 10km, $50-100, listed in 1 week'
```

Useful flags:

| Flag | Purpose |
|---|---|
| `--pages N` | scroll N viewport-heights of infinite scroll (default 3) |
| `--show-rejects` | print listings dropped by validation, with the failure reason |
| `--only-new` | print only listings not seen in any prior run with the same parsed filters |
| `--debug` | run headful + dump raw response when something goes wrong |
| `--db PATH` | override the SQLite path (default `~/.fb_marketplace_search/db.sqlite`) |
| `--stdin` | read the query from stdin instead of an argument |
| `--assume-yes` | skip the confirmation prompt on ambiguous queries |

The tool refuses to re-run the **same query** within 5 minutes (configurable in `config.py`). This is polite to Marketplace and discourages tight loops.

## Query syntax

Filters are recognized in any order, separated by commas or spaces:

| Filter | Forms |
|---|---|
| size | `11`, `11"`, `11 inch`, `XS`, `S`, `M`, `L`, `XL`, `XXL` |
| price | `$50-100`, `50-100$`, `between 50 and 100`, `under 100`, `over 50` (CAD) |
| distance | `10km`, `10 km`, `within 10 km` |
| recency | `today`, `past 24h`, `last 7 days`, `listed in 1 week` |
| condition | `new`, `like new`, `used`, `good`, `fair` |

Whatever the parser does **not** recognize as a filter becomes the keyword string. A bare digit (e.g. `11`) is parsed as a size but flagged as ambiguous — the CLI prompts before running so you don't lose a literal-`11` keyword by accident.

## Storage and diff

Every listing the tool has ever seen is upserted into `~/.fb_marketplace_search/db.sqlite`. The schema (verbatim from `docs/architecture.md` §4):

- `listings` — primary key `marketplace_id`, includes `first_seen_at` and `last_seen_at`. Every harvest stores the gzipped raw payload as `raw_blob` so we can backfill if the parser changes.
- `searches` — one row per CLI invocation, with `parsed_filters_json` and a SHA-256 hash for diff lookup.
- `search_results` — many-to-many between searches and listings, with `validated_pass` and `validation_failures_json` for audit.

Re-running an identical query (same parsed filters JSON) computes a diff vs. the most recent prior run with that filter set, bucketing results into `NEW` / `STILL_THERE` / `GONE` / `PRICE_CHANGED`.

### Schema migrations

v1 policy is **blow-away on schema mismatch**. The DB is a cache, not a system of record. If a future version bumps `SCHEMA_VERSION`, you'll see:

```
schema changed; rerun with FB_MARKETPLACE_DROP_ON_MIGRATE=1 to recreate (this deletes your cache).
```

## Run the tests

```bash
.venv/bin/pytest                           # unit + integration; smoke excluded by default
.venv/bin/pytest -m smoke tests/smoke -s   # opt-in smoke against real Marketplace
```

The headline ship gate is `WEDGE-E2E-1` in `tests/integration/test_wedge_e2e.py`: 20 listings (5 truly size 11, 15 leakage cases), and only the 5 must `validated_pass=true`.

Test fixtures live in `tests/fixtures/`. They are HTML snapshots scrubbed of PII; capture new ones from real runs and scrub before committing per `docs/test-plan.md` §6.

## Project layout

```
src/fb_marketplace_search/
  cli.py                 entrypoint (argparse)
  config.py              paths, defaults, env loading
  parser/                free-form query -> ParsedQuery
  driver/                Camoufox launcher, login, search runner, selectors
  normalize/             raw harvest dict -> NormalizedListing
  validate/              one validator per filter; AND-combined pipeline
  storage/               sync sqlite3, schema verbatim from architecture §4
  diff/                  NEW / STILL_THERE / GONE / PRICE_CHANGED
  output/                console rendering
tests/
  unit/                  parser, validators, normalizer, storage, diff
  integration/           harvest + persist + render against canned HTML
  fixtures/              PII-scrubbed Marketplace snapshots (commit these)
  smoke/                 opt-in real-Marketplace
scripts/                 (reserved; setup/ helpers grow here)
```

When Marketplace changes its DOM and the harvester breaks, edit `src/fb_marketplace_search/driver/selectors.py` first. Every CSS/XPath/URL-param key lives there.

## See also

- `docs/architecture.md` — system architecture
- `docs/test-plan.md` — acceptance matrix and the WEDGE tests
- `specs/v1.md` — feature spec
