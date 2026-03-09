#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))

from src.backend.apps.analytics_cache import ensure_analytics_cache_schema, refresh_analytics_cache


def main() -> None:
    ensure_analytics_cache_schema()
    refresh_analytics_cache(source="script")
    print("analytics_cache refreshed")


if __name__ == "__main__":
    main()
