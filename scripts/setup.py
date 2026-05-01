"""One-time interactive login. Mirrors appointmaker/scripts/setup.py.

Wraps `fbms setup` so users can run `python scripts/setup.py` from a fresh
checkout, mirroring the convention from sibling projects.
"""

from __future__ import annotations

import sys


def main() -> int:
    from fb_marketplace_search.cli import cmd_setup

    return cmd_setup()


if __name__ == "__main__":
    sys.exit(main())
