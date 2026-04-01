from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

from src.backend.repo_index.config import settings

SIGNAL_KEYS = ("reranker", "vector", "bm25", "authority", "entity", "evidence")

DEFAULT_SCORING_PROFILES: dict[str, dict[str, float]] = {
    "exact_match": {
        "reranker": 0.35,
        "vector": 0.15,
        "bm25": 0.35,
        "authority": 0.10,
        "entity": 0.05,
        "evidence": 0.0,
    },
    "aggregation": {
        "reranker": 0.40,
        "vector": 0.25,
        "bm25": 0.10,
        "authority": 0.15,
        "entity": 0.10,
        "evidence": 0.0,
    },
    "summary": {
        "reranker": 0.50,
        "vector": 0.25,
        "bm25": 0.10,
        "authority": 0.10,
        "entity": 0.05,
        "evidence": 0.0,
    },
    "factual": {
        "reranker": 0.40,
        "vector": 0.20,
        "bm25": 0.20,
        "authority": 0.10,
        "entity": 0.05,
        "evidence": 0.05,
    },
    "exploratory": {
        "reranker": 0.40,
        "vector": 0.30,
        "bm25": 0.15,
        "authority": 0.10,
        "entity": 0.05,
        "evidence": 0.0,
    },
    "evidential": {
        "reranker": 0.40,
        "vector": 0.20,
        "bm25": 0.20,
        "authority": 0.10,
        "entity": 0.05,
        "evidence": 0.05,
    },
    "legal_reference": {
        "reranker": 0.35,
        "vector": 0.20,
        "bm25": 0.25,
        "authority": 0.15,
        "entity": 0.05,
        "evidence": 0.0,
    },
    "accountability": {
        "reranker": 0.45,
        "vector": 0.10,
        "bm25": 0.10,
        "authority": 0.10,
        "entity": 0.25,
        "evidence": 0.0,
    },
    "recommendation": {
        "reranker": 0.55,
        "vector": 0.25,
        "bm25": 0.05,
        "authority": 0.10,
        "entity": 0.05,
        "evidence": 0.0,
    },
}


@dataclass(frozen=True)
class ScoringProfile:
    query_type: str
    weights: dict[str, float]
    source: str


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    normalized = {key: max(float(weights.get(key, 0.0)), 0.0) for key in SIGNAL_KEYS}
    total = sum(normalized.values())
    if total <= 0:
        fallback = DEFAULT_SCORING_PROFILES["factual"]
        total = sum(fallback.values())
        return {key: round(fallback.get(key, 0.0) / total, 6) for key in SIGNAL_KEYS}
    return {key: round(value / total, 6) for key, value in normalized.items()}


class AdaptiveScoringPolicy:
    def __init__(self) -> None:
        settings.ledger_root.mkdir(parents=True, exist_ok=True)
        self.profile_overrides = self._load_profiles()

    def _load_profiles(self) -> dict[str, dict[str, float]]:
        if not settings.scoring_profiles_path.exists():
            return {}
        payload = json.loads(settings.scoring_profiles_path.read_text(encoding="utf-8"))
        profiles = payload.get("profiles", {})
        return {
            query_type: _normalize_weights(
                {**DEFAULT_SCORING_PROFILES[query_type], **weights}
            )
            for query_type, weights in profiles.items()
            if query_type in DEFAULT_SCORING_PROFILES
        }

    def _save_profiles(self) -> None:
        payload = {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "profiles": dict(sorted(self.profile_overrides.items())),
        }
        settings.scoring_profiles_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _write_feedback_row(self, row: dict) -> None:
        with settings.scoring_feedback_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def profile_for(self, query_type: str) -> ScoringProfile:
        weights = self.profile_overrides.get(query_type)
        if weights is not None:
            return ScoringProfile(
                query_type=query_type, weights=weights, source="learned"
            )
        default = DEFAULT_SCORING_PROFILES.get(
            query_type, DEFAULT_SCORING_PROFILES["factual"]
        )
        return ScoringProfile(
            query_type=query_type, weights=_normalize_weights(default), source="default"
        )

    def register_feedback(
        self,
        *,
        query_type: str,
        success: bool,
        query: str | None = None,
        note: str | None = None,
    ) -> ScoringProfile:
        if query_type not in DEFAULT_SCORING_PROFILES:
            raise ValueError(
                f"Unsupported query type for scoring feedback: {query_type}"
            )
        current = dict(self.profile_for(query_type).weights)
        if success:
            current["reranker"] += 0.01
            current["authority"] += 0.005
        else:
            current["reranker"] += 0.03
            current["vector"] += 0.02
            current["bm25"] *= 0.9
            if query_type in {"evidential", "legal_reference"}:
                current["authority"] += 0.02
            if query_type == "evidential":
                current["evidence"] += 0.03
            if query_type in {"accountability", "factual"}:
                current["entity"] += 0.02
            if query_type == "recommendation":
                current["vector"] += 0.01
        updated = _normalize_weights(current)
        self.profile_overrides[query_type] = updated
        self._save_profiles()
        self._write_feedback_row(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "query": query,
                "query_type": query_type,
                "success": success,
                "note": note,
                "updated_weights": updated,
            }
        )
        return ScoringProfile(query_type=query_type, weights=updated, source="learned")

    def profiles(self) -> dict[str, dict[str, float]]:
        return {
            query_type: self.profile_for(query_type).weights
            for query_type in sorted(DEFAULT_SCORING_PROFILES)
        }

    def feedback_history(self, limit: int = 50) -> list[dict]:
        if not settings.scoring_feedback_path.exists():
            return []
        rows = [
            json.loads(line)
            for line in settings.scoring_feedback_path.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        return rows[-limit:]


@lru_cache(maxsize=1)
def get_scoring_policy() -> AdaptiveScoringPolicy:
    return AdaptiveScoringPolicy()


def register_scoring_feedback(
    *,
    query_type: str,
    success: bool,
    query: str | None = None,
    note: str | None = None,
) -> ScoringProfile:
    return get_scoring_policy().register_feedback(
        query_type=query_type,
        success=success,
        query=query,
        note=note,
    )
