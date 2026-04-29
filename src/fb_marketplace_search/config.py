"""Path resolution and sentinel constants. No I/O on import.

Per architecture §2 module 1: paths default to `~/.fb_marketplace_search/`,
overridable via `FB_MARKETPLACE_HOME`. No global singletons; callers
construct a `Settings` and pass it explicitly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_HOME_DIR = "~/.fb_marketplace_search"
DEFAULT_PAGES = 3
DEFAULT_MIN_INTERVAL_SECONDS = 5 * 60
DEFAULT_MAX_DESCRIPTION_REFETCH = 25
DEFAULT_USER_LOCALE = "en-CA"


@dataclass(frozen=True)
class Settings:
    home: Path
    db_path: Path
    state_path: Path
    last_failure_path: Path
    pages: int = DEFAULT_PAGES
    min_interval_seconds: int = DEFAULT_MIN_INTERVAL_SECONDS
    max_description_refetch: int = DEFAULT_MAX_DESCRIPTION_REFETCH
    locale: str = DEFAULT_USER_LOCALE
    headful: bool = False
    debug: bool = False


def resolve_home() -> Path:
    raw = os.environ.get("FB_MARKETPLACE_HOME") or DEFAULT_HOME_DIR
    return Path(raw).expanduser().resolve()


def make_settings(
    *,
    home: Path | None = None,
    db_path: Path | None = None,
    pages: int = DEFAULT_PAGES,
    headful: bool = False,
    debug: bool = False,
) -> Settings:
    h = home if home is not None else resolve_home()
    return Settings(
        home=h,
        db_path=db_path if db_path is not None else h / "db.sqlite",
        state_path=h / "state.json",
        last_failure_path=h / "last_failure.html",
        pages=pages,
        headful=headful,
        debug=debug,
    )


def ensure_home(settings: Settings) -> None:
    settings.home.mkdir(parents=True, exist_ok=True)
