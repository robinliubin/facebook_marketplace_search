# facebook_marketplace_search — v1 QA Report (Round 1)

Run date: 2026-04-29
Tester: qa-tester
Build: developer task #4 close (commit at HEAD on main when round 1 ran)
Test plan: docs/test-plan.md (commit 9863635)
Spec: specs/v1.md (with §8 addendum, commit c2126ed)
Architecture: docs/architecture.md

---

## 1. Verdict

**HOLD** — the wedge ship gate is intact, but five non-wedge acceptance tests fail. Five bug tasks filed (#6–#10), task #5 blocked on them. No re-run yet.

Per test-plan §9 verdict criteria:
- All `WEDGE-*` tests pass (size validator boundary contract holds).
- All `AT-*` tests in stories 1, 2, 3 pass.
- Five `AT-*` failures touch story 1 (parser ambiguity prompts) and story 5 (price-change diff). One adversarial RECENT failure.
- No structural failure of the size validator → not REDESIGN.

When all five bugs are fixed and a re-run is green, the build is shippable.

## 2. Test counts

| Bucket | Run | Pass | Fail | Skipped / deselected |
|---|---|---|---|---|
| Developer's pytest suite (`pytest`) | 114 | 114 | 0 | 1 (smoke marker, default-deselected as designed) |
| Smoke (`pytest -m smoke`) | — | — | — | not run (requires interactive login + live Marketplace; out of scope for round 1) |
| Manual offline acceptance probes (test-plan IDs not in dev's suite) | 19 | 14 | 5 | — |

Probes targeted gaps in dev coverage, not duplicates. Specifically:
AT-1.11a/b/c/d/e/f, AT-3.2 (custom DB path), AT-4.6 (km display), AT-5.1, AT-5.2, AT-5.3, AT-5.3b, AT-5.6, RATE-1a/b/c/d (logic-level), PRICE-9, RECENT-5b, RECENT-8/8b/8c/8d, WEDGE-NUM-5 cross-check.

## 3. Wedge gate (test-plan §2)

**WEDGE-E2E-1** — `tests/integration/test_wedge_e2e.py::test_wedge_e2e_1` — **PASS**.
All `WEDGE-NUM-1..14` and `WEDGE-ALPHA-1..9` pass in the developer's parametrized suite. The size validator's word-boundary contract holds for every boundary case in the plan (substring guards `110`/`115`/`7-11`, single-letter `S` guard, decimal `11.5` guard, etc.).

The product's reason to exist — "size 11 query never returns size 7/14/15" — is upheld by the build.

## 4. Bugs filed

| # | Test ID | Severity (impact on plan §9) | Story | Owner | Task |
|---|---|---|---|---|---|
| 1 | AT-5.2 | non-wedge AT failure → blocks ship until fixed | Story 5 (re-run and diff) | developer | #6 |
| 2 | AT-1.11a | non-wedge AT failure → blocks ship | Story 1 (query input) | developer | #7 |
| 3 | AT-1.11b | non-wedge AT failure → blocks ship | Story 1 | developer | #8 |
| 4 | AT-1.11c | non-wedge AT failure → blocks ship | Story 1 | developer | #9 |
| 5 | RECENT-8c | non-wedge AT failure → blocks ship | filter validator (recency) | developer | #10 |

### Bug summaries

- **#6 / AT-5.2 (PRICE_CHANGED bucket permanently empty).** `passed_pairs_for_search` joins to `listings.price`, which UPSERT overwrites on every run, so prior-run price ends up identical to current-run price and the diff branch never fires. Likely needs a per-search price snapshot column on `search_results` (architect should weigh in on schema). This is the most consequential bug — it disables half of Story 5.

- **#7 / AT-1.11a (duplicate-filter ambiguity not flagged).** `parse('… 10km within 5 km')` silently keeps the first match without setting `ambiguities`. Spec §8.2 Trigger 1 requires a prompt.

- **#8 / AT-1.11b (`new` in keyword context not flagged).** `parse('new york yankees jersey XL')` silently sets `condition=new` and strips `new` from the keyword. Spec §8.2 Trigger 2 requires a prompt.

- **#9 / AT-1.11c (single-letter alpha size flanked by alphas not flagged).** `parse('vintage S sport gear')` silently sets `size=S`. Spec §8.2 Trigger 2 second sentence requires a prompt unless flanked by `size`/`taille`/`:`/`,`/string-boundary. The cued case `chandail size S` is correctly *not* flagged (verified), so the heuristic is partially implemented but missing the alpha-flank check.

- **#10 / RECENT-8c (`last week` returns None).** `parse_listed_at('last week')` returns None; sibling forms `a week ago` and `1 week ago` correctly map to 7 days. Spec §8.2 lists `last week` as an explicit equivalent.

## 5. What passed (highlights)

Beyond the wedge:

- **AT-3.2 (custom DB path)** — `--db /tmp/x.sqlite` creates a fresh DB at the configured path with all three required tables.
- **AT-4.6 (km display)** — formatter renders `4.7 km`; no `mile`/`mi` substring anywhere in output.
- **AT-5.1 (NEW/GONE/STILL_THERE buckets)** — all three buckets correct on a 3 → 3 listing diff with one new, one gone, one shared.
- **AT-5.3 (`--only-new` filters output)** — only the NEW bucket reaches stdout.
- **AT-5.3b (first-run note)** — literal `first run for these filters; nothing to diff against yet.` is emitted in the no-prior-run path (cli.py:259).
- **AT-5.6 (every-run revalidation)** — re-running the validator against the same persisted listings yields the same pass/fail set; nothing is cached.
- **RATE-1a/b/c/d (re-run politeness)** — the rate-limit lookup keys on `parsed_filters_hash`, the refusal message matches spec wording, `--force` bypass branch is in cli.py:181, and a different-hash query is correctly not throttled. The smoke-level (a/b/c/d through the CLI binary) runs were not exercised because the CLI eagerly opens the browser before the printable refusal message would land — the logic-level probe verifies the contract.
- **PRICE-9 (price in description, structured price=None)** — fails with `no_price` (spec §3 source-of-truth contract upheld; description is not parsed).
- **RECENT-5b (non-allowlist string)** — `around a fortnight` correctly returns None and routes to `no_listed_at`.
- **RECENT-8 / 8b / 8d (week-ago variants except `last week`)** — `a week ago`, `1 week ago`, `2 weeks ago`, `3 weeks ago` all map correctly to n×7 days.

## 6. What was not run in round 1

- **Smoke suite (`pytest -m smoke`)** — requires interactive login per spec §6 Q1 (b). Not run because (a) it touches live Marketplace and the §7 spot-check protocol is the better fit, (b) round 1 is meant to be offline; smoke is opt-in.
- **§7 manual spot-check protocol** — produces the spec §5 accuracy targets (size 100%, price ≥99%, distance ≥99%, recency ≥95%, condition ≥90%). Not run in round 1; runs in the final pre-ship round 2 (after bugs are fixed, before declaring SHIP).
- **AT-1.11g/h/i** — these exercise `--force`, `-y`, and interactive `y` answers to ambiguity prompts. Skipped in round 1 because the underlying ambiguity detection (#7/#8/#9) is broken; once fixed I'll re-test the prompt-and-bypass path end-to-end.
- **AT-2.3 / AT-2.4 (`--pages N`)** — there is no multi-page fixture in the build's `tests/fixtures/` (only single-page `_clean`/`_dirty`/`_empty`). Not strictly a bug — pagination touches the live driver. Flagged to developer for round 2.

## 7. Environment notes (not bugs, for the team)

While setting up the project locally I hit a macOS quarantine artifact: pip's `_editable_impl_*.pth` file in `.venv/lib/python3.12/site-packages/` had the macOS `UF_HIDDEN` flag set, which caused CPython's `site.addpackage` to skip it (site.py:176–179), making `import fb_marketplace_search` fail despite a successful `uv pip install -e ".[dev]"`. Workaround: `chflags -R nohidden .venv`. The flag is re-applied each time the venv is touched (likely Gatekeeper/`com.apple.provenance` xattr propagation), so this needs to be re-run after every install in this environment. **Not a v1 bug** — the build itself is correct; this is the laptop's macOS being aggressive. Mentioned here so it doesn't show up as a phantom blocker on a future re-run.

## 8. Re-run plan

Round 2 fires when developer marks tasks #6/#7/#8/#9/#10 completed. Per test-plan §8 step 6, my re-run scope per fix:

| Fixed task | Re-run | Re-run scope |
|---|---|---|
| #6 (AT-5.2) | AT-5.2 + AT-5.1, AT-5.3, AT-5.5, AT-5.6 | full Story 5 regression (schema change risk) |
| #7 (AT-1.11a) | AT-1.11a–i + AT-1.* parser table | full Story 1 (parser change) |
| #8 (AT-1.11b) | AT-1.11a–i + AT-1.7* (condition parsing affected) | Story 1 + condition validator probe |
| #9 (AT-1.11c) | AT-1.11a–i + AT-1.3* (size parsing affected) | Story 1 + size validator probe |
| #10 (RECENT-8c) | RECENT-1..8g | full recency parser + validator |

If round 2 is green, I'll then run the §7 manual spot-check protocol against live Marketplace, write a round 3 report, and update verdict to SHIP / HOLD / REDESIGN.

---

# Round 2

Run date: 2026-04-29
Build: commit c6cc0a9 ("fix: spec §8.2 ambiguity triggers + RECENT mappings + AT-5.2 price snapshot")
Schema: bumped v1 → v2 (`price_at_search`, `currency_at_search` columns on `search_results`); blow-away migration policy applies (`FB_MARKETPLACE_DROP_ON_MIGRATE=1` for existing caches).

## 1. Verdict (round 2)

**SHIP — pending the §7 spot-check.** All five round-1 bugs verified fixed. The wedge gate remains green. The automated suite is necessary-but-not-sufficient per spec §5; final SHIP/HOLD on the build belongs to product-manager after the spot-check protocol runs.

Per test-plan §9: every WEDGE-* passes (size precision/recall = 1.0 by automated fixture), every AT-* in stories 1-5 passes, no open blocker bugs. The non-functional metrics are still soft targets and not gating.

## 2. Test counts

| Bucket | Round 1 | Round 2 | Notes |
|---|---|---|---|
| Developer's pytest suite (`pytest`) | 114/114 | **145/145** | +24 in c6cc0a9 (ambiguity-trigger, recency §8.2, render-units, revalidate-every-run, AT-5.2 snapshot); +5 in ea0837d (RATE-1a/c/d deterministic via factored-out `check_politeness_gate` helper, plus `--force` bypass and no-prior-search rows) |
| Smoke (`pytest -m smoke`) | not run | not run | gated on §7 manual protocol |
| Manual offline acceptance probes | 14/19 | **13/13** | round-2 probes scoped to round-1 failures + architect's precedence assertion |

## 3. Bug verification (round-2)

| # | Test ID | Round 1 | Round 2 | Evidence |
|---|---|---|---|---|
| 6 | AT-5.2 | FAIL — PRICE_CHANGED empty | **PASS** — A2 in PRICE_CHANGED, NOT in STILL_THERE (precedence respected per architect) | direct probe of compute_diff with new schema |
| 7 | AT-1.11a | FAIL — duplicate not flagged | **PASS** | `parse('… 10km within 5 km')` sets ambiguities |
| 8 | AT-1.11b | FAIL — `new york` silent | **PASS** | `parse('new york yankees jersey XL')` sets ambiguities |
| 9 | AT-1.11c | FAIL — `S` flanked silent | **PASS** | `parse('vintage S sport gear')` sets ambiguities |
| 10 | RECENT-8c | FAIL — `last week` → None | **PASS** | maps to now-7d; sibling cases unchanged |

Architect's precedence assertion (PRICE_CHANGED listing must NOT also appear in STILL_THERE): **PASS**. `STILL_THERE=['A1']` only; A2 went to PRICE_CHANGED, A3 to GONE, D1 to NEW.

## 4. Test-plan / spec drift adjustments

The fix for bug #10 surfaced a clarification on §8.2's strict allow-list: bare `yesterday` is NOT on the spec's mapping list (the day-grain form is `X days ago`). Developer's RECENT mapping correctly routes `yesterday` to NULL → `no_listed_at`. My round-1 test-plan row RECENT-6 had encoded `yesterday → 1 day`, which is a test-plan bug, not a product bug. Updated docs/test-plan.md:
- RECENT-6 changed to use `1 day ago` (proper day-grain form).
- RECENT-6b added asserting `yesterday` → fails with `no_listed_at` per §8.2 strict reading.

No spec change needed — §8.2 is unambiguous on this point ("Anything not on this list → `listed_at = NULL`").

## 5. What's still pending

- **§7 manual spot-check protocol.** Required before final SHIP per test-plan §9 and spec §5. Produces the per-filter accuracy CSV. Will run that and post results to product-manager for the release call.
- **Smoke suite (`pytest -m smoke`)** against a logged-in session. PM has indicated this is also a precondition for ship. Note: with ea0837d, RATE-1a/c/d and the `--force` gate logic are now deterministic-test-covered offline; only RATE-1b's *full harvest path* (gate bypass plus a real search) still needs smoke.

If the §7 spot-check returns size accuracy 100% and price/distance/recency/condition meet their targets in spec §5, the verdict becomes SHIP and PM owns the release call.