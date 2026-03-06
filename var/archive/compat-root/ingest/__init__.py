"""Compatibility package that forwards to src/backend/ingest."""

from pathlib import Path


__path__ = [str(Path(__file__).resolve().parents[1] / "src" / "backend" / "ingest")]
