"""Append-only retrieval audit logging helpers."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from src.backend.core.config import settings


def append_retrieval_audit(payload: dict[str, Any], path: str | None = None) -> Path:
    """Append a single JSONL retrieval audit event."""
    target = Path(path or settings.RETRIEVAL_AUDIT_LOG_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "logged_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **payload,
    }
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, default=str))
        handle.write("\n")
    return target
