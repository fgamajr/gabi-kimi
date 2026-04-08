from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

H3RoutingStatus = Literal["shadow", "active", "disabled"]
H3SemanticMode = Literal["heuristic", "fallback", "llm"]
H3ViewLayer = Literal["h2", "h3", "h2_fallback"]

GENERIC_TOPICS = {
    "controle_externo",
    "normativo",
    "regulacao",
    "administrativo",
}

GATE_CODES = (
    "h2_missing_entities",
    "missing_structured_fields",
    "low_confidence",
    "weak_summary",
    "generic_topics",
    "sparse_entities",
    "signature_only",
    "source_conservative",
    "fallback_only",
    "source_residual",
)

CONSERVATIVE_SOURCES = {
    "tcu_btcu",
    "tcu_boletim_jurisprudencia",
    "tcu_boletim_pessoal",
}

H3_VERSION = "1.0.0"
H3_HASH_VERSION = "1"

REQUIRED_H3_INPUT_FIELDS = (
    "raw_id",
    "source_type",
    "h2_summary_short",
    "h2_summary_structured",
    "h2_topics",
    "h2_status",
    "h2_mode",
    "h2_extraction_confidence_overall",
)

OPTIONAL_H3_INPUT_FIELDS = (
    "legal_entities",
    "tags_flat",
    "structured_fields_subset",
)


@dataclass(frozen=True)
class H3Input:
    raw_id: str
    source_type: str
    h2_summary_short: str | None
    h2_summary_structured: dict[str, Any] | None
    h2_topics: list[str]
    h2_status: str
    h2_mode: str | None
    h2_extraction_confidence_overall: float
    legal_entities: list[dict[str, Any]] | None = None
    tags_flat: list[str] | None = None
    structured_fields_subset: dict[str, Any] | None = None


@dataclass(frozen=True)
class SemanticView:
    raw_id: str
    source_type: str
    view_layer: H3ViewLayer
    status: str
    mode: str | None
    summary_short: str | None
    summary_structured: dict[str, Any] | None
    topics: list[str]
    gate_decision: dict[str, Any] | None
    quality_flags: list[str]
    extraction_confidence_overall: float | None
    interpretation_confidence_overall: float | None


class H3RawAccess:
    def __init__(self, conn: Any):
        self._conn = conn

    def fetch_body_tagged_xml(self, raw_id: str, source_type: str, *, reason: str) -> str | None:
        table = f"parsed.{source_type}"
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO h3_governance.h3_raw_access_log (source_type, raw_id, access_reason, accessed_at)
                VALUES (%s, %s, %s, NOW())
                """,
                (source_type, raw_id, reason[:200]),
            )
            cur.execute(f"SELECT body_tagged_xml FROM {table} WHERE raw_id = %s", (raw_id,))
            row = cur.fetchone()
        return row[0] if row else None


def build_h3_input(row: dict[str, Any]) -> H3Input:
    confidence_fields = row.get("confidence_fields") or {}
    overall = float(confidence_fields.get("overall") or 0.0)
    return H3Input(
        raw_id=str(row["raw_id"]),
        source_type=str(row["source_type"]),
        h2_summary_short=(row.get("summary_short") or None),
        h2_summary_structured=row.get("summary_structured") if isinstance(row.get("summary_structured"), dict) else None,
        h2_topics=list(row.get("topics") or []),
        h2_status=str(row.get("enrichment_status") or "pending"),
        h2_mode=str(row.get("enrichment_mode") or "") or None,
        h2_extraction_confidence_overall=overall,
        legal_entities=row.get("legal_entities") if isinstance(row.get("legal_entities"), list) else None,
        tags_flat=list(row.get("tags_flat") or []),
        structured_fields_subset=row.get("structured_fields") if isinstance(row.get("structured_fields"), dict) else None,
    )


def build_h3_input_payload(inp: H3Input) -> dict[str, Any]:
    return {
        "raw_id": inp.raw_id,
        "source_type": inp.source_type,
        "h2_summary_short": inp.h2_summary_short,
        "h2_summary_structured": inp.h2_summary_structured,
        "h2_topics": inp.h2_topics,
        "h2_status": inp.h2_status,
        "h2_mode": inp.h2_mode,
        "h2_extraction_confidence_overall": round(inp.h2_extraction_confidence_overall, 6),
        "legal_entities": inp.legal_entities or [],
        "tags_flat": inp.tags_flat or [],
        "structured_fields_subset": inp.structured_fields_subset or {},
    }


def build_h3_input_hash(
    inp: H3Input,
    *,
    h3_version: str = H3_VERSION,
    hash_version: str = H3_HASH_VERSION,
) -> str:
    payload = {
        "hash_version": hash_version,
        "h3_version": h3_version,
        "input": build_h3_input_payload(inp),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _generic_topics_only(topics: list[str]) -> bool:
    if not topics:
        return True
    return all(topic in GENERIC_TOPICS for topic in topics)


def derive_quality_flags(
    inp: H3Input,
    *,
    summary_short: str | None = None,
    summary_structured: dict[str, Any] | None = None,
    topics: list[str] | None = None,
    confidence_overall: float | None = None,
    semantic_status: str | None = None,
    semantic_mode: str | None = None,
) -> list[str]:
    current_summary = summary_short if summary_short is not None else inp.h2_summary_short
    current_structured = summary_structured if summary_structured is not None else inp.h2_summary_structured
    current_topics = topics if topics is not None else inp.h2_topics
    current_confidence = confidence_overall if confidence_overall is not None else inp.h2_extraction_confidence_overall
    current_status = semantic_status or inp.h2_status
    current_mode = semantic_mode or inp.h2_mode
    flags: list[str] = []
    if current_status == "done_fallback" or current_mode == "fallback":
        flags.append("fallback_only")
    if not current_structured:
        flags.append("missing_structured_fields")
    if not (current_summary or "").strip():
        flags.append("weak_summary")
    if _generic_topics_only(current_topics or []):
        flags.append("generic_topics")
    if float(current_confidence or 0.0) < 0.70:
        flags.append("low_confidence")
    if not inp.legal_entities:
        flags.append("sparse_entities")
    if inp.tags_flat and set(inp.tags_flat) == {"assinatura"}:
        flags.append("signature_only")
    if inp.source_type in CONSERVATIVE_SOURCES and current_status != "done_full":
        flags.append("source_conservative")
    return list(dict.fromkeys(flags))


def build_gate_decision(
    inp: H3Input,
    quality_flags: list[str],
    *,
    confidence_overall: float | None = None,
    semantic_status: str | None = None,
    semantic_mode: str | None = None,
) -> dict[str, Any]:
    primary_code = quality_flags[0] if quality_flags else "source_residual"
    source_layer = "h2" if primary_code in {"fallback_only", "source_conservative", "signature_only", "h2_missing_entities"} else "h3"
    return {
        "primary_code": primary_code,
        "contributing_codes": quality_flags,
        "source_layer": source_layer,
        "evidence": {
            "semantic_status": semantic_status or inp.h2_status,
            "semantic_mode": semantic_mode or inp.h2_mode,
            "extraction_confidence_overall": inp.h2_extraction_confidence_overall,
            "interpretation_confidence_overall": confidence_overall if confidence_overall is not None else inp.h2_extraction_confidence_overall,
        },
    }


def project_semantic_status(inp: H3Input, quality_flags: list[str]) -> str:
    if "fallback_only" in quality_flags:
        return "done_fallback"
    return inp.h2_status


def project_semantic_mode(inp: H3Input) -> H3SemanticMode:
    if inp.h2_mode == "fallback" or inp.h2_status == "done_fallback":
        return "fallback"
    return "heuristic"


def project_semantic_row(inp: H3Input) -> dict[str, Any]:
    extraction = float(inp.h2_extraction_confidence_overall)
    mode = project_semantic_mode(inp)
    quality_flags = derive_quality_flags(
        inp,
        confidence_overall=extraction,
        semantic_mode=mode,
    )
    status = project_semantic_status(inp, quality_flags)
    return {
        "raw_id": inp.raw_id,
        "source_type": inp.source_type,
        "semantic_mode": mode,
        "used_layers": [mode],
        "semantic_status": status,
        "semantic_summary_short": inp.h2_summary_short,
        "semantic_summary_structured": inp.h2_summary_structured,
        "semantic_topics": list(inp.h2_topics),
        "gate_decision": build_gate_decision(
            inp,
            quality_flags,
            confidence_overall=extraction,
            semantic_status=status,
            semantic_mode=mode,
        ),
        "quality_flags": quality_flags,
        "extraction_confidence_overall": extraction,
        "interpretation_confidence_overall": extraction,
    }


def build_semantic_view_from_h2(row: dict[str, Any], *, view_layer: H3ViewLayer) -> SemanticView:
    inp = build_h3_input(row)
    projected = project_semantic_row(inp)
    return SemanticView(
        raw_id=inp.raw_id,
        source_type=inp.source_type,
        view_layer=view_layer,
        status=projected["semantic_status"],
        mode=projected["semantic_mode"],
        summary_short=projected["semantic_summary_short"],
        summary_structured=projected["semantic_summary_structured"],
        topics=projected["semantic_topics"],
        gate_decision=projected["gate_decision"],
        quality_flags=projected["quality_flags"],
        extraction_confidence_overall=projected["extraction_confidence_overall"],
        interpretation_confidence_overall=projected["interpretation_confidence_overall"],
    )


def build_semantic_view_from_h3(row: dict[str, Any]) -> SemanticView:
    return SemanticView(
        raw_id=str(row["raw_id"]),
        source_type=str(row["source_type"]),
        view_layer="h3",
        status=str(row.get("semantic_status") or "pending"),
        mode=str(row.get("semantic_mode") or "") or None,
        summary_short=row.get("semantic_summary_short") or None,
        summary_structured=row.get("semantic_summary_structured") if isinstance(row.get("semantic_summary_structured"), dict) else None,
        topics=list(row.get("semantic_topics") or []),
        gate_decision=row.get("gate_decision") if isinstance(row.get("gate_decision"), dict) else None,
        quality_flags=list(row.get("quality_flags") or []),
        extraction_confidence_overall=float(row.get("extraction_confidence_overall")) if row.get("extraction_confidence_overall") is not None else None,
        interpretation_confidence_overall=float(row.get("interpretation_confidence_overall")) if row.get("interpretation_confidence_overall") is not None else None,
    )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
