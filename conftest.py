"""Test-time path guard for this checkout.

Pytest on this machine can resolve a sibling `scripts` package before the local
repo root. Prepending the checkout root keeps test imports bound to this
repository without requiring callers to set `PYTHONPATH` manually.
"""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
