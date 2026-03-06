"""Compatibility package that forwards Python modules to src/backend/dbsync."""

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
__path__ = [
    str(_ROOT / "dbsync"),
    str(_ROOT / "src" / "backend" / "dbsync"),
]
