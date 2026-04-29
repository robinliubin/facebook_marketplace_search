"""One-time interactive login. Mirrors appointmaker/scripts/setup.py shape.

Always headful. Navigates to facebook.com/login, then waits for the user
to log in by hand. Polls the DOM for the post-login signal (the global
nav search input). Once detected, dumps Playwright `storage_state` to
disk and exits.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from ..config import Settings, ensure_home
from .browser import _import_camoufox


POST_LOGIN_SIGNAL = 'input[aria-label*="Search" i]'
LOGIN_TIMEOUT_SECONDS = 600  # 10 minutes


def run_login_flow(settings: Settings) -> Path:
    """Launch headful Camoufox, wait for the user to log in, save state.

    Returns the path to the saved state file.
    """
    Camoufox = _import_camoufox()
    ensure_home(settings)

    print(
        "Opening Facebook in a browser window. Log in manually, then return here.",
        file=sys.stderr,
    )

    with Camoufox(headless=False, locale=settings.locale) as browser:
        page = browser.new_page()
        page.goto("https://www.facebook.com/login")
        deadline = time.time() + LOGIN_TIMEOUT_SECONDS
        while time.time() < deadline:
            try:
                if page.locator(POST_LOGIN_SIGNAL).count() > 0:
                    break
            except Exception:
                pass
            time.sleep(2)
        else:
            raise TimeoutError(
                f"Did not detect a post-login DOM signal within {LOGIN_TIMEOUT_SECONDS}s."
            )

        # Persist state.
        state_path = settings.state_path
        ctx = page.context
        ctx.storage_state(path=str(state_path))
        print(f"Saved session state to {state_path}", file=sys.stderr)

    return settings.state_path
