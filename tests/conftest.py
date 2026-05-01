"""Make `src/fb_marketplace_search` importable regardless of editable-install state.

Some Python 3.12.x point releases skip `.pth` files whose names start with `_`
(treats them as "hidden"), which breaks hatchling's editable-install artifact.
This conftest sidesteps that by placing the project's `src/` on sys.path
explicitly when the test runner starts.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
