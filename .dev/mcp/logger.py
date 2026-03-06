from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from .config import ROOT_DIR
    from .models import RoundResult
except ImportError:
    from config import ROOT_DIR
    from models import RoundResult


class RunLogger:
    def __init__(self, log_dir: str, run_label: str | None = None) -> None:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        suffix = f"-{run_label}" if run_label else ""
        self.run_id = f"{timestamp}{suffix}"
        self.run_dir = ROOT_DIR / log_dir / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def write_json(self, rel_path: str, payload: dict[str, Any]) -> None:
        path = self.run_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    def write_text(self, rel_path: str, content: str) -> None:
        path = self.run_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def log_run_start(self, payload: dict[str, Any]) -> None:
        self.write_json("run.json", payload)

    def log_round(self, round_result: RoundResult) -> None:
        base = f"round-{round_result.round_number}"
        self.write_text(f"{base}/artifact.before.txt", round_result.artifact_before)
        self.write_text(f"{base}/artifact.after.txt", round_result.artifact_after)
        self.write_text(f"{base}/diff.patch", round_result.diff_text)
        self.write_json(f"{base}/metrics.json", round_result.to_dict())
        for review in round_result.reviews:
            self.write_json(f"{base}/reviews/{review.agent}.json", review.to_dict())

    def log_final(self, payload: dict[str, Any]) -> None:
        self.write_json("final.json", payload)
