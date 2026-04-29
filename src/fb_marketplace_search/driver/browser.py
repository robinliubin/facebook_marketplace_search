"""Camoufox browser launcher with persistent storage_state.

The runtime imports `camoufox` lazily so unit tests (and `--help`) work
without the optional dependency installed.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Iterator, Optional

from ..config import Settings


class BrowserSessionMissing(RuntimeError):
    """No saved storage_state on disk. User needs to run `fbms setup` first."""


def _import_camoufox():
    try:
        from camoufox.sync_api import Camoufox  # type: ignore
        return Camoufox
    except ImportError as exc:
        raise RuntimeError(
            "camoufox not installed. Run `uv sync` (or `pip install camoufox && "
            "playwright install firefox`) per the README."
        ) from exc


@contextlib.contextmanager
def open_page(
    settings: Settings, *, require_session: bool = True
) -> Iterator["object"]:
    """Yield a Playwright Page, with persistent storage_state loaded.

    require_session=True (search): raises BrowserSessionMissing if state.json
        is absent.
    require_session=False (setup): allows a fresh, logged-out browser.
    """
    Camoufox = _import_camoufox()

    if require_session and not settings.state_path.exists():
        raise BrowserSessionMissing(
            f"No saved session at {settings.state_path}. Run `fbms setup` first."
        )

    state_path: Optional[str] = (
        str(settings.state_path) if settings.state_path.exists() else None
    )
    headful = settings.headful or settings.debug
    cf_kwargs = {
        "headless": not headful,
        "locale": settings.locale,
    }
    if state_path:
        cf_kwargs["storage_state"] = state_path

    with Camoufox(**cf_kwargs) as browser:
        page = browser.new_page()
        try:
            yield page
        finally:
            try:
                page.close()
            except Exception:
                pass


def save_session(settings: Settings) -> None:
    """Used by the `setup` flow — implemented in driver.login."""
    raise NotImplementedError("call driver.login.run_login_flow")
