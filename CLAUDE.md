# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

`small_nice` is a **container directory of independent side projects**, not a single application. Each immediate subdirectory is its own self-contained project with its own `.git`, its own dependencies, and (usually) its own `CLAUDE.md`. The outer `small_nice/.git` only tracks the top-level `README.md`.

**Operational consequence:** `git status` from the root reports the children as untracked directories (`??`). To see real working state for a project, `cd` into it. Commits, branches, and pushes belong to the *inner* repo, not the outer one. Do not `git add` a child directory from the root — you would only stage the empty placeholder, not the project's contents.

## Subproject map

When the user mentions any of these names, route work to that directory and read its local `CLAUDE.md` / `README.md` first.

| Directory | Stack | Purpose | Has local CLAUDE.md |
|---|---|---|---|
| `appointmaker/` | Python 3.11 + Playwright + launchd | Mac-only daemon that polls Costco Pointe-Claire tire-appointment slots every ~10 min and auto-books the earliest. See `appointmaker/README.md`. | No (uses README) |
| `jobhuntingagent/` | Python 3.12 (uv), FastAPI, ChromaDB, Anthropic SDK, Camoufox/Playwright | Multi-board job search → Claude-scored matching → contact enrichment → auto-apply, with a vanilla-Alpine dashboard. | **Yes** — read it. |
| `xRadar/` | Vanilla JS, Chrome MV3 extension (no build step) | Curated X/Twitter feed via DOM scraping; user-triggered shuttle-tab refresh, no API keys. | **Yes** — read it. |
| `sportrecorder/` | Swift 5 / SwiftUI / AVFoundation, Xcode 15+, iOS 17+ | iPhone app for recording ringette games with a broadcast-style scoreboard overlay. | **Yes** — read it. |
| `facebook_marketplace_search/` | (empty stub) | Spec only — see top-level `README.md` for the intent (search FB Marketplace and validate filters against returned listings). No code yet. | No |
| `Marketing-Analytics-Assignments/` | SQL + dashboards | Improvado interview takehomes (Marketing Analyst, Engagement Lead, TCS). Data files + deliverables. | No |
| `OpenAI/` | Markdown / HTML | Written-deliverable interview brief (ASE Operator Brief). Not code. | No |
| `test-git/`, `test-claude-team/` | — | Throwaway scratch repos. Ignore unless explicitly asked. | No |

## Per-project commands

These are the ones easy to get wrong from memory; trust the local CLAUDE.md / README otherwise.

**`appointmaker/`** — driven by venv + `uv`-style pip; tests live in `tests/` and a real-Costco smoke marker is excluded by default:
```
source .venv/bin/activate
pytest                                # unit tests only (smoke excluded via addopts)
pytest -m smoke tests/test_smoke.py -s   # opt-in smoke against real Costco
python scripts/setup.py               # interactive: capture session + selectors
./scripts/install_launchd.sh          # arm the launchd agent
launchctl unload launchd/com.binliu.costco-tire.plist   # disarm
```

**`jobhuntingagent/`** — managed with `uv`; CLI entrypoint is `jobhunter`:
```
uv run jobhunter dashboard            # FastAPI dashboard on :8080
uv run jobhunter run                  # full pipeline cycle
uv run pytest tests/test_api.py -k test_name   # single test
```
`uv run` may rebuild the venv; if a long-running dashboard loses its venv, restart it (per local CLAUDE.md). ChromaDB is pinned `<1.0.0` — do not bump.

**`xRadar/`** — there is no build, no npm, no test runner. Iteration is "edit → reload extension at `chrome://extensions` → refresh any open x.com tab." Content-script changes specifically require the x.com tab refresh, not just the extension reload.

**`sportrecorder/`** — Xcode-only:
```
open SportRecorder/SportRecorder.xcodeproj
# then Cmd+R from Xcode against a connected iPhone
```

## Working conventions across projects

- **Always operate inside the relevant subproject's git repo.** Branches, commits, and PRs belong to the child repo. The outer repo is essentially a folder.
- **Read the child `CLAUDE.md` before editing.** `jobhuntingagent`, `xRadar`, and `sportrecorder` have substantive ones with architecture notes, design constraints, and known fragilities that are easy to violate.
- **Don't unify tooling across projects.** They were intentionally chosen per-project (uv vs. raw venv vs. no build at all). Don't migrate one to match another.
- **Do not commit the heavy assets** under `sportrecorder/` (videos and large PNGs are git-ignored in that project) or PDFs under `jobhuntingagent/`. They stay local.

## What's deliberately *not* in this file

Per-project architecture, data flow, scraper selectors, build invariants, and known fragilities live in each subproject's own `CLAUDE.md`. Treat this file as a routing index; don't duplicate that material here.
