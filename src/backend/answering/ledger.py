from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.backend.answering.models import AnswerTrace
from src.backend.core.config import settings

logger = logging.getLogger(__name__)

_LEDGER_DIR = Path(settings.RETRIEVAL_AUDIT_LOG_PATH).parent / "answers"
_LEDGER_FILE = _LEDGER_DIR / "answers.jsonl"


def _ensure_dir() -> None:
    try:
        _LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning("could not create ledger dir: %s", exc)


def append_trace(trace: AnswerTrace) -> None:
    _ensure_dir()
    try:
        row = json.dumps(trace.model_dump(mode="json"), ensure_ascii=False)
        with _LEDGER_FILE.open("a", encoding="utf-8") as fh:
            fh.write(row + "\n")
    except Exception as exc:
        logger.warning("failed to write answer trace: %s", exc)


def get_trace(query_id: str) -> dict[str, Any] | None:
    if not _LEDGER_FILE.exists():
        return None
    try:
        for line in reversed(_LEDGER_FILE.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("query_id") == query_id:
                return row
    except Exception as exc:
        logger.warning("failed to read ledger: %s", exc)
    return None


def recent_traces(limit: int = 20) -> list[dict[str, Any]]:
    if not _LEDGER_FILE.exists():
        return []
    try:
        lines = [
            l
            for l in _LEDGER_FILE.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        rows = [json.loads(l) for l in lines[-limit:]]
        return list(reversed(rows))
    except Exception as exc:
        logger.warning("failed to read ledger: %s", exc)
        return []
