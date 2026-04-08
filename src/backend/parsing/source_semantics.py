from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.backend.parsing.source_parsers import SOURCE_TYPES


@dataclass(frozen=True)
class SourceSemanticContract:
    source_type: str
    semantic_kind: str
    primary_sections: tuple[str, ...]
    secondary_sections: tuple[str, ...]
    ementary_fields: tuple[str, ...]
    semantic_fields: tuple[str, ...]
    decision_field: str | None = None
    problem_field: str | None = None
    year_field: str | None = None
    llm_prompt_template: str | None = None
    llm_prompt_version: str | None = None
    topic_policy: dict[str, Any] | None = None
    gate_policy: dict[str, Any] | None = None


def _contracts_path() -> Path:
    return Path(__file__).resolve().parents[3] / "ops" / "config" / "source_semantics.yaml"


def _as_tuple(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"expected list[str], got {type(value).__name__}")
    return tuple(str(item).strip() for item in value if str(item).strip())


def _build_contract(source_type: str, payload: dict[str, Any]) -> SourceSemanticContract:
    return SourceSemanticContract(
        source_type=source_type,
        semantic_kind=str(payload.get("semantic_kind") or "").strip(),
        primary_sections=_as_tuple(payload.get("primary_sections")),
        secondary_sections=_as_tuple(payload.get("secondary_sections")),
        ementary_fields=_as_tuple(payload.get("ementary_fields")),
        semantic_fields=_as_tuple(payload.get("semantic_fields")),
        decision_field=str(payload.get("decision_field")).strip() if payload.get("decision_field") else None,
        problem_field=str(payload.get("problem_field")).strip() if payload.get("problem_field") else None,
        year_field=str(payload.get("year_field")).strip() if payload.get("year_field") else None,
        llm_prompt_template=str(payload.get("llm_prompt_template")).strip() if payload.get("llm_prompt_template") else None,
        llm_prompt_version=str(payload.get("llm_prompt_version")).strip() if payload.get("llm_prompt_version") else None,
        topic_policy=dict(payload.get("topic_policy") or {}),
        gate_policy=dict(payload.get("gate_policy") or {}),
    )


@lru_cache(maxsize=1)
def load_source_semantics() -> dict[str, SourceSemanticContract]:
    path = _contracts_path()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("source_semantics config must be a mapping")
    unknown = set(raw) - set(SOURCE_TYPES)
    if unknown:
        raise ValueError(f"unknown source semantics configured: {sorted(unknown)}")
    missing = set(SOURCE_TYPES) - set(raw)
    if missing:
        raise ValueError(f"missing source semantics for: {sorted(missing)}")
    contracts = {source_type: _build_contract(source_type, dict(payload or {})) for source_type, payload in raw.items()}
    for source_type, contract in contracts.items():
        if not contract.semantic_kind:
            raise ValueError(f"semantic_kind missing for {source_type}")
        if not contract.semantic_fields:
            raise ValueError(f"semantic_fields missing for {source_type}")
    return contracts


def get_semantic_contract(source_type: str) -> SourceSemanticContract:
    try:
        return load_source_semantics()[source_type]
    except KeyError as exc:
        raise KeyError(f"no semantic contract for source {source_type}") from exc
