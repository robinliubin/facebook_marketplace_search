# facebook_marketplace_search — Operations Runbook

Scenario-driven recovery guide. Reference, not exhaustive — for install / happy-path use, see [`README.md`](../README.md).

## If X is broken, jump to:

| Symptom | Section |
|---|---|
| Marketplace shows logged-out / partial results, or "log in" wall mid-search | [§1 Session expired](#1-session-expired) |
| Zero result cards parsed, or `last_failure.html` written | [§2 Selectors broke after FB redesign](#2-selectors-broke-after-fb-redesign) |
| `schema changed; rerun with FB_MARKETPLACE_DROP_ON_MIGRATE=1` error | [§3 Cache corruption / schema mismatch](#3-cache-corruption--schema-mismatch) |
| Spec §5 accuracy targets need verification before ship | [§4 Live spot-check](#4-live-spot-check-procedure) |

---

## §1. Session expired

**Symptom.**
- `fbms search '…'` returns far fewer cards than expected, or every card is missing distance/condition fields.
- A previously working search now exits with a `SelectorDrift` error containing the word "log in" — Marketplace served a login wall instead of the search-results DOM.
- Architect §6 risk #2 baseline: Meta invalidates sessions every few weeks regardless of usage.

**Recovery.**
```bash
.venv/bin/fbms setup     # opens a Camoufox window; log in by hand
```
The interactive setup script (`scripts/setup.py`, wraps `fbms setup`) navigates to facebook.com/login, polls for the post-login DOM, then writes the new Playwright `storage_state` to `~/.fb_marketplace_search/state.json` (overwriting the stale one). Closing the window before the script signals "saved" leaves you with no usable state — re-run.

**Confirm it worked.**
```bash
.venv/bin/fbms search 'gants hockey 11"' --pages 1
```
Should return ≥1 listing with non-null `distance_km` and `condition`. If still degraded, the state file is fine but Marketplace fingerprinted the browser — wait an hour and retry, or skip ahead to [§2](#2-selectors-broke-after-fb-redesign) if the *shape* of results is wrong (not just the count).

**Files involved.**
- `scripts/setup.py` — entrypoint
- `src/fb_marketplace_search/driver/login.py` — the polling loop (`POST_LOGIN_SIGNAL`, `LOGIN_TIMEOUT_SECONDS=600`)
- `~/.fb_marketplace_search/state.json` — the persisted Playwright storage_state (gitignored, never commit)

---

## §2. Selectors broke after FB redesign

**Symptom.**
- `fbms search` exits non-zero with `SelectorDrift: Zero cards parsed from non-empty results page; HTML dumped to ~/.fb_marketplace_search/last_failure.html`.
- Or: result count is reasonable but harvested fields are wrong-shape (price coming through as title, distance always null, etc.).
- Architect §6 risk #1: this is the most likely failure mode. Every CSS/XPath/URL-param key lives in **one file** so the patch is small.

**Recovery.**

1. Inspect the captured DOM:
   ```bash
   open ~/.fb_marketplace_search/last_failure.html   # or any browser
   ```
   Find the actual selector for the listing-card anchor (it's some `a[href*="/marketplace/item/"]` shape) and the structured price/distance/title spans inside it.

2. Edit the central selector catalog — every selector lives here:
   ```
   src/fb_marketplace_search/driver/selectors.py
   ```
   Update only the constants that drift (`RESULT_CARD`, `RESULT_CARD_PRICE`, `LISTING_ID_URL_REGEX`, etc.). Do not move logic into this file — it is intentionally declarative.

3. Capture a new fixture from the broken DOM (PII-scrub per [`docs/test-plan.md`](test-plan.md) §6):
   ```bash
   # Save the scrubbed HTML to:
   tests/fixtures/results_page_<scenario>.html
   # Replace seller usernames, profile-image URLs, phone numbers, addresses
   # with placeholders. Listing IDs may stay real (they're Marketplace's).
   # Never commit raw captures containing your storage_state.
   ```

4. Pin a regression test against the new fixture:
   ```python
   # tests/integration/test_harvest_<scenario>.py
   from pathlib import Path
   from fb_marketplace_search.driver.search_runner import harvest_from_html

   FIX = Path(__file__).resolve().parent.parent / "fixtures"

   def test_harvest_post_redesign():
       html = (FIX / "results_page_<scenario>.html").read_text()
       cards = harvest_from_html(html)
       assert len(cards) >= 1
       # ... assert on the specific shape you just fixed
   ```

5. Run `.venv/bin/pytest -q` (must include the new fixture path), commit selector + fixture + test together. **No schema bump** — selector drift is purely a code+fixture change.

**Why one big edit beats many small ones.** Per architect §2 cross-cutting rule, the catalog is the canary. Centralizing keeps "where do I look first" trivial and makes the recovery flow above three lines, not three days.

---

## §3. Cache corruption / schema mismatch

**Symptom.**
```
on-disk schema_version=N, code expects M. Schema bumped to add per-search
price snapshot columns (price_at_search, currency_at_search) so the
PRICE_CHANGED diff bucket reflects the prior run's price instead of the
current post-UPSERT one. Rerun with FB_MARKETPLACE_DROP_ON_MIGRATE=1 to
recreate (this deletes your cache; per the v1 blow-away policy).
```

This is the only schema-migration policy v1 supports. The DB is a cache, not a system of record (architect §4 / spec §6.6). DB corruption (rare) presents as opaque sqlite errors and uses the same recovery.

**Recovery.**
```bash
FB_MARKETPLACE_DROP_ON_MIGRATE=1 .venv/bin/fbms init-db
```
Then rerun your normal `fbms search`.

**What gets lost.**
- Every `listings` row (incl. `raw_blob` audit payloads).
- Every `searches` row (history of past invocations).
- Every `search_results` row (per-search price snapshots, validation outcomes).

**What survives.**
- `~/.fb_marketplace_search/state.json` — the login session is untouched. **No need to re-run `fbms setup`.**
- Anything you copied out of `raw_blob` by hand. The blob is `gzip(json(harvested_dict))`; if you've been archiving these for forensics, your archive survives outside the DB.

**Avoid the surprise.** Set the env var preemptively in your shell rc only if you genuinely want every schema bump to nuke your cache silently. Default is to require the explicit opt-in so you know what you're losing — keep it that way.

**Related.** README's `## Storage and diff` and `### Schema migrations` sections cover the DDL details. This section is the recovery playbook; that one is the reference.

---

## §4. Live spot-check procedure

The smoke / live-spot-check layer is the gate between WEDGE-green and SHIP. Automated unit and integration tests prove the validator's *boundary discipline* (size 11 never matches 110/115/`7-11`/etc.); they cannot prove that the structured fields Marketplace actually returns *match reality*. That's a human judgment call, run per filter type with N=20 listings.

**Authoritative protocol.** [`docs/test-plan.md`](test-plan.md) §7 (manual spot-check protocol) is the canonical version. The runbook only restates the operational specifics:

**Run the smoke marker (driver+session sanity).**
```bash
.venv/bin/pytest -m smoke tests/smoke -s
```
Pre-conditions:
- `~/.fb_marketplace_search/state.json` must exist (run `fbms setup` first per §1 if not).
- Internet reachable to facebook.com.
- The smoke test skips automatically if the storage_state is missing.

**Per-filter spot-check.** For each of size, price, distance, recency, condition:
```bash
.venv/bin/fbms search '<filter-exercising query>' --pages 3 --show-rejects > run.txt
```
Pull the first 20 `validated_pass=true` listings from the DB or stdout (expand `--pages` until N≥20). For each, open the listing in a browser and judge whether the actual listing matches the filter. Record into a CSV per test-plan §7:
- Filename: `qa-spotcheck-<filter>-<YYYY-MM-DD>.csv`
- Columns: `marketplace_id, url, judgment, notes`
- `judgment` ∈ `pass` | `fail` | `false_negative`
- File is QA-local; not committed (no project-relative path is mandated by the spec).

> **TBD pending qa-tester confirmation:** exact CSV directory location and any extra `pytest` flags the QA workflow uses (e.g. for capturing rejects to a fixed file). Patch this paragraph once their reply lands; commit as a follow-up.

**Threshold mapping (per spec §5 + qa-report-v1 §8).**

| Filter | Target | Failure |
|---|---|---|
| size | **100%** | Blocks ship. Verdict: REDESIGN if structural; HOLD if isolated bug. |
| price | ≥99% | HOLD; PM call on ship. |
| distance | ≥99% | HOLD; PM call on ship. |
| recency | ≥95% | HOLD; PM call on ship (Marketplace's "X days ago" rounding is coarse). |
| condition | ≥90% | HOLD; PM call on ship (sellers mistag). |

A WEDGE-* automated regression failure is REDESIGN territory regardless of spot-check numbers. A spot-check below threshold opens a bug task per test-plan §8 (subject `Bug: <test ID> — <one-line symptom>`, owner `developer`).

**Politeness during spot-check.** Default 5-minute interval keyed on `parsed_filters_hash`. Two options for back-to-back probes:
- Wait the 5 minutes between identical queries.
- Vary the filter set so the hash changes (e.g. flip `--pages`, change the price band slightly). The gate is per-hash, not global — RATE-1d.
- `--force` is a last resort; document the reason in the spot-check CSV `notes` column when used. Every `--force` invocation is one Marketplace fingerprinting flag closer to a §1 session expiry, so don't make it a habit.

---

## §5. (See pointer table at top.)

(The pointer table at the top of this document is §5's content — kept there because that's where a stressed user looks first. This section is intentionally empty; the table is the navigation.)

---

## See also

- [`README.md`](../README.md) — install, run, query syntax, schema reference
- [`docs/architecture.md`](architecture.md) — module layout, schema, anti-bot strategy, risk register
- [`docs/test-plan.md`](test-plan.md) — acceptance matrix, WEDGE tests, fixture inventory, spot-check protocol (§7), bug-reporting protocol (§8)
- [`docs/qa-report-v1.md`](qa-report-v1.md) — round-1/2 verdicts, ship/hold/redesign criteria
- `src/fb_marketplace_search/driver/selectors.py` — the canary for §2
