"""Shared test setup: make ``ssa`` importable and expose a fixture loader."""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load_fixture(name: str, mode: str = "r"):
    """Read a saved payload from tests/fixtures/ (no network)."""
    path = os.path.join(FIXTURES, name)
    with open(path, mode, encoding=None if "b" in mode else "utf-8") as f:
        return f.read()
