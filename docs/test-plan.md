# facebook_marketplace_search — v1 Test Plan

Status: Draft v1
Owner: qa-tester
Audience: developer (#4), architect (#2), product-manager (#1)
Spec under test: `specs/v1.md`

---

## 0. Scope and philosophy

This plan covers v1 only. Anything in spec §2 "Non-goals" is explicitly **not** tested:
no auto-messaging, no multi-account, no daemon/cron, no notifications, no GUI, no
sponsored / Catalog API, no cross-category browsing.

The wedge — and therefore the headline test — is spec §4 Story 4 + §3's size
validator: **a query that asks for size N must yield 100% of shown listings whose
listing text contains size==N as a token, never a substring.** Everything else
in this plan is structural support around proving that.

### Test layering

We mirror `appointmaker/`'s pytest layout:

- **Unit tests** (default `pytest`): run offline, no network, deterministic, `< 5s`
  total. Cover the parser, every validator, the diff/dedup logic, and the SQLite
  schema/idempotency. Should be the bulk of the suite.
- **Integration tests** (default `pytest`): exercise the harvest → store →
  validate → render pipeline against **canned HTML/JSON fixtures** stored in
  `tests/fixtures/`. No network. Used to lock down the wedge end-to-end.
- **Smoke tests** against real Marketplace, marked `@pytest.mark.smoke` and
  **excluded by default** via `addopts = -m "not smoke"` in `pyproject.toml`.
  Run explicitly with `pytest -m smoke tests/test_smoke.py -s`. These are
  manually-triggered and gated on an interactively-captured logged-in session
  state (per spec open question #1, preferred answer (b)).

A test is unit unless it (a) reads from disk, (b) opens a browser, or (c) hits
a network. (a) and (b) are integration; (c) is smoke.

### Success metric measurement

Spec §5 sets per-filter accuracy targets that **cannot be measured purely by
automated tests** — they require a human to look at 20 real listings per filter
and judge correctness. §7 of this document defines the spot-check protocol that
produces those numbers; the automated suite alone is necessary but not sufficient
to declare v1 ships.

---

## 1. Acceptance test matrix (one row per acceptance criterion)

Each row maps to a checkbox in spec §4. Test IDs are `AT-<story>.<criterion>`.

### Story 1 — Query input (spec §4.1)

| ID | Precondition | Steps | Expected | Evidence |
|---|---|---|---|---|
| AT-1.1 | tool installed | `fbms search 'gants hockey 11"'` (single quoted arg) | parser emits structured filters; exit 0 | stdout dump of parsed filters |
| AT-1.2 | tool installed | `echo 'gants hockey 11"' \| fbms search --stdin` | same parsed filters as AT-1.1 | stdout dump |
| AT-1.3a | — | parse `gants hockey 11"` | `size=11`, keyword=`gants hockey` | unit test on parser |
| AT-1.3b | — | parse `gants hockey 11 inch` | `size=11`, keyword=`gants hockey` | unit test |
| AT-1.3c | — | parse `chandail XL` | `size=XL`, keyword=`chandail` | unit test |
| AT-1.3d | — | parse all alpha sizes `XS / S / M / L / XL / XXL` (separately) | each recognized as size, not keyword | parametrized unit test |
| AT-1.4a | — | parse `$50-100` | price min=50, max=100 CAD | unit test |
| AT-1.4b | — | parse `50-100$` | same as AT-1.4a | unit test |
| AT-1.4c | — | parse `between 50 and 100` | same | unit test |
| AT-1.4d | — | parse `under 100` | min=0, max=100 | unit test |
| AT-1.4e | — | parse `over 50` | min=50, max=∞ (None) | unit test |
| AT-1.5a | — | parse `10km` / `10 km` / `within 10 km` | distance_km=10 | parametrized unit test |
| AT-1.6a | — | parse `listed in 1 week` | recency_days=7 | unit test |
| AT-1.6b | — | parse `last 7 days` | recency_days=7 | unit test |
| AT-1.6c | — | parse `past 24h` | recency_days=1 | unit test |
| AT-1.6d | — | parse `today` | recency_days=0 | unit test |
| AT-1.7a | — | parse `new` | condition=`new` | unit test |
| AT-1.7b | — | parse `like new` | condition=`used-like-new` | unit test |
| AT-1.7c | — | parse `used`/`good`/`fair` | condition mapped per spec §3 | parametrized unit test |
| AT-1.8 | — | parse `gants hockey 11", new, 10km, $50-100, listed in 1 week` | all 5 filters set; keyword=`gants hockey` (size+condition+price+distance+recency tokens stripped) | unit test |
| AT-1.9 | — | parse comma-less variant `gants hockey 11" new 10km $50-100 listed in 1 week` | same parse as AT-1.8 (filters separable by spaces or commas, per §4.1) | unit test |
| AT-1.10 | — | parse query containing tokens that look filter-shaped but don't fit any pattern (e.g. `7-11 set`) | tokens left in keyword string, NOT consumed as filters | unit test (adversarial) |
| AT-1.11a | tty | run query with two distance tokens: `gants hockey 11" 10km within 5 km` (Trigger 1: duplicate filter type, per spec §8.2) | tool prints parsed filter set with the **first** match (10km), `(y/N)` prompt, waits on stdin | integration test using pexpect |
| AT-1.11b | tty | run query with token-class collision: `new york yankees jersey XL` (Trigger 2: `new` matched condition but flanked by alpha keywords) | tool prompts; `new` flagged in echo as ambiguous | integration test |
| AT-1.11c | tty | run query with single-letter alpha-size flanked by alpha tokens: `vintage S sport gear` (Trigger 2: `S` between alpha tokens, no `size`/`taille`/`:`/`,` cue) | tool prompts | integration test |
| AT-1.11d | tty | run query with bare-integer collision: `iphone 11 mint condition` (Trigger 3: bare `11`, no `size`/`taille`/`sz`/inch cue) | tool prompts | integration test |
| AT-1.11e | tty | run UNAMBIGUOUS query: `gants hockey size 11" new 10km $50-100 listed in 1 week` (no triggers fire — bare digit is preceded by `size` AND followed by `"`) | tool runs without prompting | integration test |
| AT-1.11f | tty | run UNAMBIGUOUS query with single-letter alpha bounded by `size` cue: `chandail size S` (S is preceded by `size` cue, Trigger 2 does not fire) | tool runs without prompting | integration test |
| AT-1.11g | tty | answer `n` to any AT-1.11a–d prompt | tool exits without searching, exit code != 0 | integration test |
| AT-1.11h | piped stdin OR `-y` flag | run AT-1.11a query with `--assume-yes` | tool skips prompt and runs with first-match interpretation; the chosen interpretation is echoed to stdout (auditable, per spec §8.2 escape hatch) | integration test |
| AT-1.11i | tty, ambiguous query, user answers `y` | run AT-1.11a query, type `y\n` | tool proceeds with first-match parse (echo matches what was confirmed) | integration test |

### Story 2 — Run the search (spec §4.2)

| ID | Precondition | Steps | Expected | Evidence |
|---|---|---|---|---|
| AT-2.1 | logged-in storage state present | run query with all 5 filters | tool sets price, distance, condition, recency Marketplace controls before issuing search; keyword (with size token retained) goes into search box | smoke test asserting the URL or POST payload contains the four mapped filter params |
| AT-2.2 | canned fixture | harvest fixture page | extracts marketplace_id, URL, title, description, price, currency, location, distance_km, listed_at, condition, seller_id, image_url, raw_blob for every result tile | integration test |
| AT-2.3 | `--pages 3` (default) | run against canned multi-page fixture | exactly 3 pages worth of listings harvested | integration test |
| AT-2.4 | `--pages 1` | as above | exactly 1 page harvested | integration test |
| AT-2.5 | canned fixture with zero result tiles | run | exits 0 with `no results` message; no rows inserted into `listings` or `searches` | integration test |
| AT-2.6 | canned fixture | harvest a tile missing description | row stored with description=NULL, no crash | integration test (adversarial) |
| AT-2.7 | canned fixture | harvest a tile missing price | row stored with price=NULL (will be dropped at validation if price filter active) | integration test (adversarial) |

### Story 3 — Local SQLite persistence (spec §4.3)

| ID | Precondition | Steps | Expected | Evidence |
|---|---|---|---|---|
| AT-3.1 | fresh `$HOME` | first run | `~/.fb_marketplace_search/db.sqlite` created with `searches`, `listings`, `search_results` tables matching schema in §4.3 | integration test using tmp_path |
| AT-3.2 | `--db /tmp/x.sqlite` | first run | DB created at the configured path, default not touched | integration test |
| AT-3.3 | DB seeded with listing X | re-harvest a fixture containing X with same fields | UPSERT: same `marketplace_id` row updated, `last_seen_at` advanced, `first_seen_at` unchanged | unit test on the persistence layer |
| AT-3.4 | DB seeded with listing X at price 80 | re-harvest with X at price 70 | row updated to price=70, `last_seen_at` advanced; old price recoverable via raw_blob | unit test |
| AT-3.5 | validation drops a listing for size mismatch | persist | row in `listings` AND row in `search_results` with `validated_pass=0` and `validation_failures_json` containing `[{filter:"size", reason:"..."}]` | integration test |
| AT-3.6 | re-run identical search | check searches table | new `searches` row inserted with same `parsed_filters_json` (idempotency is at the listings level, not search level) | integration test |

### Story 4 — Post-search validation (spec §4.4) **— THE WEDGE**

See §2 of this plan for the dedicated wedge tests. The acceptance rows here
just lock down the surrounding contract.

| ID | Precondition | Steps | Expected | Evidence |
|---|---|---|---|---|
| AT-4.1 | fixture of 10 listings, 5 fail size, 3 fail price, 2 pass everything | run validation | exactly 2 listings have `validated_pass=true`; 8 have `validated_pass=false` with the correct `validation_failures_json` | integration test |
| AT-4.2 | listing fails size AND price | validate | both reasons appear in `validation_failures_json` (failures recorded for *every* failing filter, not just the first) | integration test (asserts AND-combined record) |
| AT-4.3 | as AT-4.1 | default CLI output | only the 2 passing listings printed, in `position` order | integration test capturing stdout |
| AT-4.4 | as AT-4.1 | run with `--show-rejects` | all 10 listings printed; rejects annotated with their failure reasons | integration test |
| AT-4.5 | see §2 of this plan | size substring boundary cases | dedicated wedge tests |
| AT-4.6 | listing.distance_km=4.7 | render to CLI | distance shown in km (e.g. `4.7 km` or `4.7km`); no miles, no mixed-unit (per spec §8.1 ruling 2) | integration test capturing stdout |

### Story 5 — Re-run and diff (spec §4.5)

| ID | Precondition | Steps | Expected | Evidence |
|---|---|---|---|---|
| AT-5.1 | run query Q yielding listings {A,B,C}; later run Q yielding {A,B,D} | diff | A,B → STILL_THERE; C → GONE; D → NEW | integration test |
| AT-5.2 | A had price 80, now 70 | diff | A → PRICE_CHANGED with old=80, new=70 | integration test |
| AT-5.3 | as AT-5.1 with `--only new` | run | only D printed | integration test |
| AT-5.3b | first-ever run for this `parsed_filters_hash`, with `--only new` (per spec §8.1 ruling 5) | run | every passing listing printed AND a one-line note `first run for these filters; nothing to diff against yet.` is emitted; tool does NOT bucket all results as `NEW`; tool does NOT error | integration test |
| AT-5.4 | C failed validation in run 1, would still appear from Marketplace in run 2 but again fails | diff | C is **not** in any bucket — diff only considers `validated_pass=true` listings (per spec §4.5 last bullet) | integration test (regression guard against accidental "GONE" on filter-rejected items) |
| AT-5.5 | run query Q' (different parsed filters from Q) | diff | diff falls back to "no prior run" — does NOT diff Q' against Q | integration test (regression: filter-key changes must not be cross-matched) |
| AT-5.6 | run query Q at time T1 (validator A is buggy and passes a size-110 listing); developer fixes validator; re-run Q at T2 (per spec §8.1 ruling 1: every run revalidates from scratch, never trusts prior `validated_pass`) | second run | the size-110 listing now has `validated_pass=false` in the run-T2 `search_results` row, even though the same `marketplace_id` had `validated_pass=true` at T1; the diff bucketing for this listing follows AT-5.4 (excluded) | integration test |

---

## 2. The wedge — size validator boundary cases (spec §3 + §4.4)

These are the most important tests in the suite. The product exists to fix
size leakage; if any of these regress, ship is blocked.

All are unit tests against `validators.size.validate(listing_text, target_size)`
returning `(passed: bool, reason: str)`.

| ID | target | listing text | expected pass? | rationale |
|---|---|---|---|---|
| WEDGE-NUM-1 | `11` | `Bauer hockey gloves size 11 like new` | **pass** | exact token, word boundary |
| WEDGE-NUM-2 | `11` | `CCM size 110 youth` | **fail** | `110` is NOT `11`; substring must not match |
| WEDGE-NUM-3 | `11` | `Vintage gloves 115` | **fail** | substring guard |
| WEDGE-NUM-4 | `11` | `Hockey set 7-11 various sizes` | **fail** | range bounded by digits, not a clean `11` |
| WEDGE-NUM-5 | `11` | `Sizes available: s/m/l/xl/11` | **pass** | `11` is bounded by `/` and string end — both non-digits |
| WEDGE-NUM-6 | `11` | `Gloves size: 11"` | **pass** | inch mark is a non-digit boundary |
| WEDGE-NUM-7 | `11` | `Gloves 11.5 size` | **fail** | decimal point is non-digit but `11.5` is a different size — boundary is non-digit-AND-non-`.` |
| WEDGE-NUM-8 | `11` | `Got 211 of these in stock` | **fail** | leading-digit boundary |
| WEDGE-NUM-9 | `11` | `Item #1101 hockey` | **fail** | embedded; trailing-digit boundary |
| WEDGE-NUM-10 | `11` | `` (empty string) | **fail** | empty has no token |
| WEDGE-NUM-11 | `11` | `gants hockey` (description harvest failed → empty) | **fail** | per spec §3, missing source-of-truth → drop. If description was the only source and it's NULL, validator must treat as fail and log `no_size_field` |
| WEDGE-NUM-12 | `11` | `bauer\nhockey\n11` (newline-separated) | **pass** | newlines are non-digit boundaries |
| WEDGE-NUM-13 | `11` | `Hockey gloves 7, 14, 15 in stock — message for 11` | **pass** | `11` appears as a clean token; spec rule is satisfied even if other sizes also appear |
| WEDGE-NUM-14 | `11` (case test) | `BAUER 11 GLOVES` | **pass** | numeric is case-irrelevant |
| WEDGE-ALPHA-1 | `XL` | `BAUER XL hockey jersey` | **pass** | case-insensitive whole-token |
| WEDGE-ALPHA-2 | `XL` | `Size: xl` | **pass** | case-insensitive |
| WEDGE-ALPHA-3 | `XL` | `XLR8 brand jersey` | **fail** | substring must not match |
| WEDGE-ALPHA-4 | `M` | `Size: medium` | **fail** | spec §3 says alpha sizes are whole-token match; `medium` ≠ `M`. (Confirms spec — does NOT do fuzzy expansion.) |
| WEDGE-ALPHA-5 | `M` | `Size M jersey` | **pass** | exact token |
| WEDGE-ALPHA-6 | `M` | `MMA gloves` | **fail** | substring guard on alpha |
| WEDGE-ALPHA-7 | `S` | `Size S` | **pass** | single-letter token |
| WEDGE-ALPHA-8 | `S` | `Sport gear` | **fail** | single-letter substring guard (this is the riskiest one — implementation must use word boundaries, not `in`) |
| WEDGE-ALPHA-9 | `XL` | `XL/L/M available` | **pass** | `/` is a non-letter boundary |

**Wedge end-to-end test** (integration, deterministic):

| ID | Precondition | Steps | Expected | Evidence |
|---|---|---|---|---|
| WEDGE-E2E-1 | canned fixture: 20 listings — 5 actually size 11, 15 are sizes 7/14/15/110/115/`7-11`/empty/etc. | run pipeline with `size=11` | exactly the 5 true-11 listings have `validated_pass=true`; precision = recall = 1.0 | integration test asserting the exact set of `marketplace_id`s |

WEDGE-E2E-1 is the **headline test for ship/no-ship.** If it fails, v1 does not ship.

---

## 3. Filter validation — non-size filters (spec §3 + §5)

One test row per filter, plus adversarial cases. All unit tests unless noted.

### 3.1 Price range

| ID | Precondition | Steps | Expected | Notes |
|---|---|---|---|---|
| PRICE-1 | filter min=50 max=100 | listing price=75 | pass | inside range |
| PRICE-2 | as above | price=50 | pass | inclusive lower |
| PRICE-3 | as above | price=100 | pass | inclusive upper |
| PRICE-4 | as above | price=49.99 | fail | just below |
| PRICE-5 | as above | price=100.01 | fail | just above |
| PRICE-6 | as above | price=NULL (Marketplace returned no price) | **fail with reason `no_price`** | spec §3 explicit |
| PRICE-7 | filter `under 100` (min=0,max=100) | price=0 (free) | pass | zero is valid |
| PRICE-8 | filter `over 50` (min=50, max=None) | price=10000 | pass | open upper bound |
| PRICE-9 | adversarial: price in description, not structured field | structured price=NULL, description="$80 firm" | **fail with `no_price`** | spec §3: structured price is source of truth; v1 does NOT parse description for price |
| PRICE-10 | currency mismatch (listing in USD) | price=80 USD, filter is CAD 50-100 | fail with `validation_failures_json` entry `[{"filter":"price","reason":"currency_mismatch"}]`; v1 does NOT do FX conversion | architect ruling, architecture.md §7.6 |

### 3.2 Distance

| ID | Precondition | Steps | Expected | Notes |
|---|---|---|---|---|
| DIST-1 | filter 10km | listing distance_km=5 | pass | |
| DIST-2 | as above | distance_km=10 | pass | inclusive |
| DIST-3 | as above | distance_km=10.01 | fail | |
| DIST-4 | as above | distance_km=NULL | **fail with `no_distance`** | spec §3 explicit |
| DIST-5 | adversarial: Marketplace pre-filtered to 10km but returned a tile reporting distance_km=15 (Marketplace's own filter is leaky) | filter 10km | fail with `distance_exceeded` | this is the literal "Marketplace lied" case; the validator earns its keep here |

### 3.3 Listed-within-N-days

| ID | Precondition | Steps | Expected | Notes |
|---|---|---|---|---|
| RECENT-1 | filter recency_days=7, frozen now=2026-04-29 | listing listed_at=2026-04-22 | pass | inclusive |
| RECENT-2 | as above | listed_at=2026-04-21 | fail | 8 days |
| RECENT-3 | as above | listed_at="just listed" | pass | maps to 0 days per spec §8.2 |
| RECENT-4 | as above | listed_at="3 hours ago" | pass | sub-day → 0 (spec §8.2) |
| RECENT-4b | as above | listed_at="X minutes ago" | pass | sub-day → 0 (spec §8.2) |
| RECENT-5 | as above | listed_at=NULL | **fail with `no_listed_at`** | spec §3 explicit |
| RECENT-5b | as above | listed_at="around a fortnight" (a string not on §8.2's allow-list) | **fail with `no_listed_at`** | spec §8.2: anything not on the mapping list → NULL → fails |
| RECENT-6 | filter recency_days=0 (`today`) | listed_at="yesterday" | fail | strict; "yesterday" is day-grain, literal 1 day |
| RECENT-7 | filter recency_days=1 (`past 24h`) | listed_at="23 hours ago" | pass | sub-day boundary |
| RECENT-8 | filter recency_days=7 | listing listed_at="a week ago" | **pass** | spec §8.2 RULING: `a week ago` → 7 days exactly (lenient). Resolved (no longer OPEN). |
| RECENT-8b | as above | listed_at="1 week ago" | pass | spec §8.2: same mapping as `a week ago` |
| RECENT-8c | as above | listed_at="last week" | pass | spec §8.2: same mapping as `a week ago` |
| RECENT-8d | filter recency_days=14 | listed_at="2 weeks ago" | pass | spec §8.2: plural weeks round to n×7 days = 14 |
| RECENT-8e | filter recency_days=13 | listed_at="2 weeks ago" | fail | n×7 = 14 > 13 |
| RECENT-8f | filter recency_days=7 | listed_at="3 days ago" | pass | day-grain literal (spec §8.2) |
| RECENT-8g | filter recency_days=7 | listed_at="8 days ago" | fail | day-grain literal exceeds filter |

### 3.4 Condition

| ID | Precondition | Steps | Expected | Notes |
|---|---|---|---|---|
| COND-1 | filter `new` | listing.condition=`new` | pass | structured field |
| COND-2 | filter `new` | listing.condition=`used-like-new` | fail | exact match only |
| COND-3 | filter `used-like-new` | listing.condition=`used-like-new` | pass | |
| COND-4 | filter `new` | listing.condition=NULL | **fail with `no_condition`** | spec §3: only when user specified |
| COND-5 | filter NOT set (user didn't ask) | listing.condition=NULL | **pass** (not evaluated) | per spec §3: missing condition only matters if user specified |
| COND-6 | adversarial: title says "BRAND NEW IN BOX" but structured condition=`used-good` | filter `new` | **fail** | spec §3 explicit: v1 trusts structured field, does NOT infer from text |

### 3.5 Cross-filter combination

| ID | Precondition | Steps | Expected |
|---|---|---|---|
| COMBO-1 | all 5 filters set; listing passes 4, fails 1 | validate | `validated_pass=false`, single failure recorded |
| COMBO-2 | all 5 filters set; listing fails 3 | validate | `validated_pass=false`, all 3 failures recorded (AND-combined; per AT-4.2) |
| COMBO-3 | all 5 filters set; listing passes all | validate | `validated_pass=true`, empty failures array |

---

## 4. Regression: diff and dedup (spec §4.5)

| ID | Precondition | Steps | Expected |
|---|---|---|---|
| DIFF-1 | runs A then B with same query, B harvested same listings | diff B vs A | all STILL_THERE, no NEW, no GONE |
| DIFF-2 | A: {1,2}, B: {2,3} | diff B vs A | NEW=[3], GONE=[1], STILL_THERE=[2] |
| DIFF-3 | A: listing 1 @ $80, B: listing 1 @ $70 | diff B vs A | PRICE_CHANGED for listing 1, old=80 new=70 |
| DIFF-4 | A: listing 1 @ $80, B: listing 1 @ $80 | diff B vs A | STILL_THERE, NOT PRICE_CHANGED |
| DIFF-5 | listing 1 in A passed validation; in B same listing returned by Marketplace but now fails (e.g. user added stricter filter) | diff B vs A | listing 1 NOT in any bucket (per AT-5.4) |
| DIFF-6 | run with no prior runs of this exact parsed filter | diff | tool prints "no prior run to diff against" and outputs validated results unfiltered (not all-NEW or all-GONE) |
| DIFF-7 | DEDUP within a single run: Marketplace returned the same `marketplace_id` twice on different pages (positions 3 and 27, say) | harvest+persist | `listings` = 1 row; `search_results` = 1 row keyed at the **earlier** position (3, not 27) — `INSERT OR IGNORE` semantics on `PRIMARY KEY (search_id, listing_id)`, NOT `OR REPLACE`; stderr/log line `dedup: dropped N within-run duplicate listings` reports the drop count | architect ruling, architecture.md §7.7 |

---

## 5. Non-functional

These are **not gates** but tracked metrics; failures here open bugs for triage,
not auto-block ship.

| ID | What | How measured | Target |
|---|---|---|---|
| PERF-1 | Time-to-results | smoke test: time from CLI invocation to printed list, default `--pages 3` | median < 60s (spec §5 secondary metric) |
| PERF-2 | Validator latency | unit benchmark: validate 1000 listings | < 1s on dev laptop (size validator is regex-only; should be trivial) |
| PERF-3 | DB write latency | integration test: insert 1000 listings | < 5s |
| RATE-1a | Re-run politeness — block path | smoke: run query, immediately re-run within 30s without `--force` | tool exits non-zero with message `Last run was N seconds ago; minimum interval is M. Use --force to override.`; no new search executed | architect ruling, architecture.md §5 Layer 4 + §7.7 / §7.8 |
| RATE-1b | Re-run politeness — bypass path | as above, then re-run with `--force` | tool proceeds, search executes, new `searches` row written | same |
| RATE-1c | Re-run politeness — interval expired | sleep past `--min-interval` (use a low override e.g. `--min-interval 2` and wait 3s), re-run same query | tool proceeds without `--force` | same |
| RATE-1d | Re-run politeness — different query | run query A, immediately run query B (different `parsed_filters_hash`) | tool proceeds; rate limit is per-hash, not global | same |
| AUTH-1 | Login session expiry | smoke: invalidate stored session, run | tool exits with a clear "please re-login" message and a re-login command, NOT a stack trace | spec §6 open Q1 (b) implication |

---

## 6. Test fixtures plan

All fixtures live in `tests/fixtures/`. Follow the appointmaker layout where the
`fixtures/` directory holds canned HTML and JSON snapshots that the unit and
integration tests load directly — no network.

Required fixtures (developer is expected to capture these once during build, with
a real Marketplace browser session, scrubbing PII):

- `fixtures/results_page_size11_clean.html` — single result page, 5 tiles all
  genuinely size 11. Used for happy-path harvest tests and the wedge end-to-end.
- `fixtures/results_page_size11_dirty.html` — single result page, 20 tiles: 5
  truly size 11 + 15 leakage cases (sizes 7, 14, 15, 110, 115, "7-11 set",
  "size: small/medium/11", missing-description tile, missing-price tile,
  out-of-range distance, etc.). This is the primary wedge fixture.
- `fixtures/results_page_empty.html` — Marketplace's "no results" state. AT-2.5.
- `fixtures/results_pages_multi_p1.html`, `_p2.html`, `_p3.html` — three pages
  for `--pages` testing. AT-2.3 / AT-2.4.
- `fixtures/listing_detail_size11.html` — single listing detail page (the lazy
  description-fetch pass per spec §6 Q5). At least one fixture per condition
  value (`new`, `used-like-new`, `used-good`, `used-fair`).
- `fixtures/listing_detail_no_price.html` — adversarial: structured price absent.
- `fixtures/listing_detail_no_distance.html` — adversarial.
- `fixtures/listing_detail_no_listed_at.html` — adversarial.
- `fixtures/listing_detail_no_condition.html` — adversarial.
- `fixtures/listing_detail_currency_usd.html` — adversarial for PRICE-10:
  structured price field present but currency is `USD`, not `CAD` (or any
  non-CAD code). Used to verify the `currency_mismatch` reason path.
- `fixtures/parsed_filters/*.json` — golden parser outputs for AT-1.* table-driven
  tests.

PII scrub rules for fixtures: replace seller usernames, profile-image URLs,
phone numbers, addresses with placeholders. Listing IDs may stay real (they are
Marketplace's). Do not commit fixtures containing the developer's logged-in
session cookies or storage state.

---

## 7. Manual spot-check protocol (for spec §5 success metrics)

Spec §5 sets per-filter accuracy targets that automated tests cannot prove,
because they require judging "did Marketplace lie?" against a real listing.
This protocol produces those numbers and is run **before declaring v1 done**.

For each of the five filter types, qa-tester:

1. Constructs a query that exercises that filter (e.g. for size: a category
   known to have many size-11 leakage cases like hockey gloves; for distance:
   a city with sellers at the radius edge; etc.).
2. Runs `fbms search '<query>' --pages 3 --show-rejects > run.txt`.
3. Pulls the first 20 listings that have `validated_pass=true` (from the DB or
   stdout). If fewer than 20, expand `--pages` until N≥20.
4. For each of the 20, opens the listing on Marketplace in a browser and
   manually judges: does it actually match the filter?
5. Records yes/no in a CSV `qa-spotcheck-<filter>-<date>.csv` with columns:
   `marketplace_id, url, judgment (pass|fail), notes`.
6. Computes accuracy = passes / 20.
7. Compares against §5 targets:
   - size **must be 100%** — any failure blocks ship.
   - price ≥ 99%, distance ≥ 99%, recency ≥ 95%, condition ≥ 90% — failures
     below threshold open a bug, but ship decision is product-manager's call.

Each spot-check round is also an opportunity to record **false negatives**:
sample 5 listings from `--show-rejects` and judge whether the validator
*should* have passed them. Log to the same CSV with `judgment=false_negative`.

---

## 8. Bug reporting protocol

When a test fails, qa-tester does **not** patch the code. Instead:

1. Capture: test ID, command run, full stdout/stderr, fixture or query used,
   environment (OS, Python version, browser version if smoke), DB state if
   relevant (sqlite snapshot path).
2. Re-run once to confirm the failure is reproducible (rules out flake).
3. `TaskCreate` a new task:
   - Subject: `Bug: <test ID> — <one-line symptom>`
   - Owner: `developer`
   - Description, formatted exactly:

     ```
     Test: <test ID>
     Spec ref: <e.g. spec §4.4 AC bullet 6>

     Steps to reproduce:
     1. ...
     2. ...

     Expected:
     <copy of expected from this plan>

     Actual:
     <observed behavior, with logs / stdout snippet>

     Environment:
     - OS:
     - Python:
     - Branch / commit:
     - Fixture: tests/fixtures/<file>

     Evidence:
     <paths to captured logs, sqlite snapshot, screenshot>
     ```
4. If the bug blocks further testing (e.g. the parser crashes so no validator
   tests can run), `TaskUpdate addBlockedBy=[<bug-id>]` on task #5.
5. Notify developer via `SendMessage`.
6. When developer messages back that the fix is in: pull, re-run **the failing
   test plus all tests downstream of the changed module** (e.g. a parser fix
   re-runs all AT-1.*; a size validator fix re-runs all WEDGE-*), update the
   bug task to completed if green, otherwise re-open with new evidence.

---

## 9. Ship / hold / redesign verdict criteria

The QA report (`docs/qa-report-v1.md`) ends with a one-line verdict:

- **SHIP** — every WEDGE-* test passes (size accuracy = 100% by automated
  fixture AND by §7 spot-check), all AT-* in stories 1–5 pass, no open
  blocker bugs. Non-functional metrics may be off-target (logged, not gating).
- **HOLD** — the wedge passes but ≥1 non-wedge AT fails. Bugs filed,
  developer is unblocked to fix.
- **REDESIGN** — any WEDGE-* fails AND the failure is structural (e.g. the
  size validator uses substring matching baked into the architecture). Goes
  back to architect / product-manager — this is the case where v1 is broken
  in the same way Marketplace is broken, which is the entire reason for
  the project not to exist that way.

---

## 10. Open questions raised by this plan — all resolved

All five questions raised in this plan are resolved by the spec §8 addendum
(commit c2126ed) and architecture.md §7. Summary for traceability:

1. **PRICE-10 currency mismatch.** Resolved — spec §8.1 ruling 3/8 +
   architecture.md §7.6. Non-CAD listing fails price filter with reason
   `currency_mismatch`; no FX conversion. Test row updated.
2. **DIFF-7 within-run duplicates.** Resolved — spec §8.1 ruling 6 +
   architecture.md §7.7. `INSERT OR IGNORE` on the `(search_id, listing_id)`
   PK; first-seen position retained; per-run log line
   `dedup: dropped N within-run duplicate listings`.
3. **RATE-1 re-run politeness.** Resolved — spec §8.1 ruling 7 +
   architecture.md §5 Layer 4 / §7.7 / §7.8. 5-min default per
   `parsed_filters_hash`; `--min-interval`, `--force`. Expanded to four rows
   (a/b/c/d).
4. **RECENT-8 "a week ago" rounding.** Resolved — spec §8.2. `a week ago` /
   `1 week ago` / `last week` → 7 days exactly (PASS for `recency_days=7`).
   Plural weeks → n×7. Day-grain literal. Sub-day → 0. Anything else → NULL →
   `no_listed_at`. RECENT-8 expanded into RECENT-8a–g.
5. **AT-1.11 ambiguity prompt.** Resolved — spec §8.2. Three concrete
   triggers: (1) duplicate filter type, (2) token-class collision (e.g. `new`
   in `new york`, single-letter alpha-size flanked by alpha tokens with no
   `size`/`taille`/`:`/`,` cue), (3) bare-integer collision (bare integer
   without leading `size`/`taille`/`sz` cue or trailing `"`/`inch`/`in.`).
   Escape hatch: `--assume-yes` / `-y`. Expanded to AT-1.11a–i.

Two side-effect rulings from architect (spec §8.1) added to the plan as
new test rows:

- **§8.1 ruling 1 (every-run revalidation).** New row AT-5.6 confirms a
  validator bugfix takes effect on next run, even for listings whose
  `validated_pass` was previously `true`.
- **§8.1 ruling 2 (km display unit).** New row AT-4.6 asserts CLI distance
  rendering is always km, no miles, no mixed-unit.
- **§8.1 ruling 5 (`--only new` first run).** New row AT-5.3b asserts
  first-ever run prints all passing results plus the
  `first run for these filters...` note, does NOT bucket as NEW, does NOT
  error.
