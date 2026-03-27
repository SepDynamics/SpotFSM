"""Runtime helpers for loading the compiled manifold extension."""

from __future__ import annotations

import importlib
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType

MODULE_NAME = "manifold_engine"


@lru_cache(maxsize=1)
def load_manifold_engine() -> ModuleType:
    """Import the compiled extension from the active environment or local build tree."""
    try:
        return importlib.import_module(MODULE_NAME)
    except ModuleNotFoundError as initial_error:
        repo_root = Path(__file__).resolve().parents[3]
        search_roots = (
            repo_root / "build" / "src" / "core",
            repo_root / "build" / "lib",
            repo_root / "src" / "core",
        )

        for root in search_roots:
            if not root.exists():
                continue
            if any(root.glob("manifold_engine*.so")) or any(root.glob("manifold_engine*.pyd")):
                sys.path.insert(0, str(root))
                return importlib.import_module(MODULE_NAME)

        raise ModuleNotFoundError(
            "Unable to import 'manifold_engine'. Build it with "
            "`cmake -S . -B build && cmake --build build --target manifold_engine`, "
            "or add the extension directory to PYTHONPATH."
        ) from initial_error
