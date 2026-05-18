"""Make the repo root importable so `from scripts import ...` works.

The top-level ``scripts/`` dir has no ``__init__.py`` (intentional: it's a
collection of CLI scripts, not a library), so pytest's rootdir-based
collection cannot import it as a package unless rootdir is on sys.path.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
