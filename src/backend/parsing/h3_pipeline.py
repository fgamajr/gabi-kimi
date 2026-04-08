from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from src.backend.core.config import settings
from src.backend.parsing.h3_llm import H3_LLM_PROMPT_VERSION, H3_PROMPT_TEMPLATE, refine_semantic_projection_with_llm
from src.backend.parsing.h3_semantic import (
    H3_HASH_VERSION,
    H3_VERSION,
    H3RawAccess,
    SemanticView,
    build_h3_input,
    build_h3_input_hash,
    build_semantic_view_from_h2,
    build_semantic_view_from_h3,
    project_semantic_row,
)
from src.backend.parsing.source_parsers import SOURCE_TYPES

logger = logging.getLogger(__name__)


def _pg_url() -> str:
    return os.getenv("POSTGRES_URL", settings.POSTGRES_URL)


def _parsed_table(source_type: str) -> str:
    return f"parsed.{source_type}"


def _semantic_table(source_type: str) -> str:
    return f"parsed_semantic.{source_type}"


def _llm_allowed_for_source(
    source_type: str,
    *,
    llm_source_filters: tuple[str, ...] = (),
) -> bool:
    configured = tuple(item.strip() for item in llm_source_filters if item.strip())
    if configured:
        return source_type in configured
    env_configured = tuple(
        item.strip()
        for item in os.getenv("H3_LLM_SOURCE_ALLOWLIST", "").split(",")
        if item.strip()
    )
    if env_configured:
        return source_type in env_configured
    return False


@dataclass(frozen=True)
class H3QueueItem:
    queue_id: int
    source_type: str
    raw_id: str
    h3_version: str
    hash_version: str
    input_hash: str


class SemanticResolver:
    def __init__(self, dsn: str | None = None):
        self._dsn = dsn or _pg_url()

    def get_view(self, raw_id: str, source_type: str, *, view_context: str = "default") -> SemanticView | None:
        with psycopg.connect(self._dsn) as conn:
            return self._get_view_conn(conn, raw_id, source_type, view_context=view_context)

    def _get_view_conn(
        self,
        conn: psycopg.Connection,
        raw_id: str,
        source_type: str,
        *,
        view_context: str,
    ) -> SemanticView | None:
        routing_status = self._load_routing_status(conn, source_type)
        h2_row = self._load_h2_row(conn, source_type, raw_id)
        if not h2_row:
            return None
        if routing_status == "active":
            h3_row = self._load_h3_row(conn, source_type, raw_id)
            if h3_row:
                return build_semantic_view_from_h3(dict(h3_row))
            self._record_fallback(conn, source_type, raw_id, view_context=view_context, reason_code="missing_h3_row")
            conn.commit()
            return build_semantic_view_from_h2(dict(h2_row), view_layer="h2_fallback")
        return build_semantic_view_from_h2(dict(h2_row), view_layer="h2")

    def _load_routing_status(self, conn: psycopg.Connection, source_type: str) -> str:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM h3_governance.h3_routing WHERE source_type = %s",
                (source_type,),
            )
            row = cur.fetchone()
        return str(row[0]) if row else "disabled"

    def _load_h2_row(self, conn: psycopg.Connection, source_type: str, raw_id: str) -> dict[str, Any] | None:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"SELECT * FROM {_parsed_table(source_type)} WHERE raw_id = %s", (raw_id,))
            return cur.fetchone()

    def _load_h3_row(self, conn: psycopg.Connection, source_type: str, raw_id: str) -> dict[str, Any] | None:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"SELECT * FROM {_semantic_table(source_type)} WHERE raw_id = %s", (raw_id,))
            return cur.fetchone()

    def _record_fallback(
        self,
        conn: psycopg.Connection,
        source_type: str,
        raw_id: str,
        *,
        view_context: str,
        reason_code: str,
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO h3_governance.h3_fallback_log (
                    source_type, raw_id, fallback_from, fallback_to, reason_code, recorded_at, view_context, details
                ) VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s::jsonb)
                """,
                (
                    source_type,
                    raw_id,
                    "h3",
                    "h2",
                    reason_code,
                    view_context,
                    json.dumps({"routing_status": "active"}, ensure_ascii=False),
                ),
            )


def ensure_h3_routing_defaults(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        for source_type in SOURCE_TYPES:
            cur.execute(
                """
                INSERT INTO h3_governance.h3_routing (source_type, status, switched_at, switched_by, reason)
                VALUES (%s, 'disabled', NULL, NULL, 'bootstrap')
                ON CONFLICT (source_type) DO NOTHING
                """,
                (source_type,),
            )


def set_h3_routing_status(source_type: str, status: str, *, reason: str, switched_by: str) -> dict[str, Any]:
    with psycopg.connect(_pg_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO h3_governance.h3_routing (source_type, status, switched_at, switched_by, reason)
                VALUES (%s, %s, NOW(), %s, %s)
                ON CONFLICT (source_type)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    switched_at = EXCLUDED.switched_at,
                    switched_by = EXCLUDED.switched_by,
                    reason = EXCLUDED.reason
                """,
                (source_type, status, switched_by, reason[:1000]),
            )
        conn.commit()
    return {"source_type": source_type, "status": status, "reason": reason}


def enqueue_h3_batch(
    source_type: str,
    *,
    limit: int,
    priority: int,
    allowed_statuses: tuple[str, ...],
    raw_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    table = _parsed_table(source_type)
    selected: list[str] = []
    effective_limit = max(limit, len(raw_ids)) if raw_ids else limit
    raw_id_clause = "AND raw_id = ANY(%s)" if raw_ids else ""
    params: list[Any] = [list(allowed_statuses)]
    if raw_ids:
        params.append(list(raw_ids))
    params.append(effective_limit)
    with psycopg.connect(_pg_url()) as conn:
        ensure_h3_routing_defaults(conn)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT *
                FROM {table}
                WHERE enrichment_status = ANY(%s)
                  {raw_id_clause}
                ORDER BY updated_at DESC, raw_id ASC
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()
            for row in rows:
                inp = build_h3_input(dict(row))
                input_hash = build_h3_input_hash(inp)
                selected.append(inp.raw_id)
                cur.execute(
                    """
                    INSERT INTO parsed_semantic.enrichment_queue (
                        source_type, raw_id, h3_version, hash_version, input_hash,
                        status, next_retry_at, attempts, priority, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, 'pending', NOW(), 0, %s, NOW(), NOW())
                    ON CONFLICT (source_type, raw_id, h3_version, hash_version, input_hash)
                    DO UPDATE SET
                        status = 'pending',
                        next_retry_at = NOW(),
                        attempts = 0,
                        priority = EXCLUDED.priority,
                        updated_at = NOW()
                    """,
                    (source_type, inp.raw_id, H3_VERSION, H3_HASH_VERSION, input_hash, priority),
                )
        conn.commit()
    return {
        "source_type": source_type,
        "selected": len(selected),
        "raw_ids": selected,
        "priority": priority,
        "allowed_statuses": list(allowed_statuses),
    }


def _acquire_h3_queue_item(
    conn: psycopg.Connection,
    worker_id: str,
    *,
    source_filters: tuple[str, ...] = (),
    raw_id_filters: tuple[str, ...] = (),
) -> H3QueueItem | None:
    source_clause = "AND source_type = ANY(%s)" if source_filters else ""
    raw_id_clause = "AND raw_id = ANY(%s)" if raw_id_filters else ""
    params: list[Any] = []
    if source_filters:
        params.append(list(source_filters))
    if raw_id_filters:
        params.append(list(raw_id_filters))
    params.append(worker_id)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            WITH candidate AS (
                SELECT id
                FROM parsed_semantic.enrichment_queue
                WHERE (
                    (status = 'pending' AND next_retry_at <= NOW())
                    OR (status = 'running' AND locked_at < NOW() - INTERVAL '10 minutes')
                )
                """
            + source_clause
            + raw_id_clause
            + """
                ORDER BY priority ASC, next_retry_at ASC, id ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE parsed_semantic.enrichment_queue q
            SET status = 'running', locked_by = %s, locked_at = NOW(), updated_at = NOW()
            FROM candidate
            WHERE q.id = candidate.id
            RETURNING q.id, q.source_type, q.raw_id, q.h3_version, q.hash_version, q.input_hash
            """,
            params,
        )
        row = cur.fetchone()
    if not row:
        return None
    return H3QueueItem(
        queue_id=row["id"],
        source_type=row["source_type"],
        raw_id=row["raw_id"],
        h3_version=row["h3_version"],
        hash_version=row["hash_version"],
        input_hash=row["input_hash"],
    )


def _mark_h3_queue_done(conn: psycopg.Connection, queue_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE parsed_semantic.enrichment_queue
            SET status = 'done', locked_by = NULL, locked_at = NULL, updated_at = NOW()
            WHERE id = %s
            """,
            (queue_id,),
        )


def _mark_h3_queue_failed(conn: psycopg.Connection, queue_id: int, error: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE parsed_semantic.enrichment_queue
            SET
                status = CASE WHEN attempts + 1 >= 3 THEN 'failed' ELSE 'pending' END,
                attempts = attempts + 1,
                next_retry_at = NOW() + ((attempts + 1) * INTERVAL '2 minutes'),
                last_error = %s,
                locked_by = NULL,
                locked_at = NULL,
                updated_at = NOW()
            WHERE id = %s
            """,
            (error[:2000], queue_id),
        )


def _load_parsed_row(conn: psycopg.Connection, source_type: str, raw_id: str) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT * FROM {_parsed_table(source_type)} WHERE raw_id = %s", (raw_id,))
        return cur.fetchone()


def _upsert_semantic_projection(conn: psycopg.Connection, source_type: str, row: dict[str, Any]) -> None:
    table = _semantic_table(source_type)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {table} (
                raw_id, source_type, h3_version, hash_version, prompt_version, semantic_mode, used_layers,
                semantic_status, semantic_summary_short, semantic_summary_structured,
                semantic_topics, gate_decision, quality_flags,
                extraction_confidence_overall, interpretation_confidence_overall,
                input_hash, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s::jsonb,
                %s, %s::jsonb, %s,
                %s, %s,
                %s, NOW(), NOW()
            )
            ON CONFLICT (raw_id) DO UPDATE SET
                h3_version = EXCLUDED.h3_version,
                hash_version = EXCLUDED.hash_version,
                prompt_version = EXCLUDED.prompt_version,
                semantic_mode = EXCLUDED.semantic_mode,
                used_layers = EXCLUDED.used_layers,
                semantic_status = EXCLUDED.semantic_status,
                semantic_summary_short = EXCLUDED.semantic_summary_short,
                semantic_summary_structured = EXCLUDED.semantic_summary_structured,
                semantic_topics = EXCLUDED.semantic_topics,
                gate_decision = EXCLUDED.gate_decision,
                quality_flags = EXCLUDED.quality_flags,
                extraction_confidence_overall = EXCLUDED.extraction_confidence_overall,
                interpretation_confidence_overall = EXCLUDED.interpretation_confidence_overall,
                input_hash = EXCLUDED.input_hash,
                updated_at = NOW()
            """,
            (
                row["raw_id"],
                row["source_type"],
                H3_VERSION,
                H3_HASH_VERSION,
                row.get("prompt_version"),
                row["semantic_mode"],
                row["used_layers"],
                row["semantic_status"],
                row["semantic_summary_short"],
                json.dumps(row["semantic_summary_structured"], ensure_ascii=False) if row["semantic_summary_structured"] is not None else None,
                row["semantic_topics"],
                json.dumps(row["gate_decision"], ensure_ascii=False),
                row["quality_flags"],
                row["extraction_confidence_overall"],
                row["interpretation_confidence_overall"],
                row["input_hash"],
            ),
        )


def _ensure_prompt_registry_entry(
    conn: psycopg.Connection,
    *,
    source_type: str,
    prompt_version: str,
    model: str,
    template: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO h3_governance.prompt_registry (
                prompt_version, source_type, template, model_id, temperature, max_tokens, created_at, created_by, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, %s)
            ON CONFLICT (prompt_version) DO NOTHING
            """,
            (
                prompt_version,
                source_type,
                template,
                model,
                float(os.getenv("H2_LLM_TEMPERATURE", "0.0")),
                int(os.getenv("H2_LLM_MAX_TOKENS", "512")),
                "codex",
                "H3 v1.1 semantic refinement prompt",
            ),
        )


def _attach_llm_evidence(projected: dict[str, Any], **updates: Any) -> None:
    gate_decision = dict(projected.get("gate_decision") or {})
    evidence = dict(gate_decision.get("evidence") or {})
    for key, value in updates.items():
        if value is None:
            continue
        evidence[key] = value
    gate_decision["evidence"] = evidence
    projected["gate_decision"] = gate_decision


def process_one_semantic(
    worker_id: str,
    *,
    source_filters: tuple[str, ...] = (),
    llm_source_filters: tuple[str, ...] = (),
    raw_id_filters: tuple[str, ...] = (),
    model: str = "qwen3",
    llm_mode: str = "fast",
    max_text_chars: int = 12000,
) -> bool:
    with psycopg.connect(_pg_url()) as conn:
        item = _acquire_h3_queue_item(
            conn,
            worker_id=worker_id,
            source_filters=source_filters,
            raw_id_filters=raw_id_filters,
        )
        if item is None:
            conn.commit()
            return False
        parsed_row = _load_parsed_row(conn, item.source_type, item.raw_id)
        if not parsed_row:
            _mark_h3_queue_failed(conn, item.queue_id, "parsed row missing")
            conn.commit()
            return True
        try:
            inp = build_h3_input(dict(parsed_row))
            projected = project_semantic_row(inp)
            projected["prompt_version"] = None
            llm_allowed = _llm_allowed_for_source(
                item.source_type,
                llm_source_filters=llm_source_filters,
            )
            _attach_llm_evidence(projected, llm_allowed=llm_allowed)
            if llm_allowed:
                raw_access = H3RawAccess(conn)
                raw_text = raw_access.fetch_body_tagged_xml(
                    item.raw_id,
                    item.source_type,
                    reason="h3_llm_refinement",
                )
                if raw_text:
                    prompt_text = raw_text[:max_text_chars]
                    try:
                        projected, meta = refine_semantic_projection_with_llm(
                            inp,
                            projected,
                            raw_text=prompt_text,
                            model=model,
                            llm_mode=llm_mode,
                        )
                        usage = dict(meta.get("usage") or {})
                        changed_fields = list(meta.get("changed_fields") or [])
                        _attach_llm_evidence(
                            projected,
                            llm_attempted=True,
                            llm_delta_material=bool(meta.get("delta_material")),
                            llm_promoted=projected["semantic_mode"] == "llm",
                            llm_changed_fields=changed_fields,
                            llm_model=model,
                            llm_provider=meta.get("provider"),
                            llm_prompt_tokens=usage.get("prompt_tokens"),
                            llm_completion_tokens=usage.get("completion_tokens"),
                            llm_total_tokens=usage.get("total_tokens"),
                        )
                        logger.info(
                            "h3_llm_eval source=%s raw_id=%s attempted=%s delta=%s promoted=%s changed_fields=%s model=%s provider=%s total_tokens=%s",
                            item.source_type,
                            item.raw_id,
                            True,
                            bool(meta.get("delta_material")),
                            projected["semantic_mode"] == "llm",
                            ",".join(changed_fields) or "-",
                            model,
                            meta.get("provider"),
                            usage.get("total_tokens"),
                        )
                        if projected["semantic_mode"] == "llm":
                            projected["prompt_version"] = H3_LLM_PROMPT_VERSION
                            _ensure_prompt_registry_entry(
                                conn,
                                source_type=item.source_type,
                                prompt_version=H3_LLM_PROMPT_VERSION,
                                model=model,
                                template=H3_PROMPT_TEMPLATE,
                            )
                    except Exception:
                        projected["prompt_version"] = None
                        _attach_llm_evidence(
                            projected,
                            llm_attempted=True,
                            llm_delta_material=False,
                            llm_promoted=False,
                            llm_error="llm_refinement_failed",
                        )
                        logger.warning(
                            "h3_llm_eval_failed source=%s raw_id=%s model=%s",
                            item.source_type,
                            item.raw_id,
                            model,
                        )
                else:
                    _attach_llm_evidence(
                        projected,
                        llm_attempted=False,
                        llm_delta_material=False,
                        llm_promoted=False,
                        llm_skip_reason="missing_raw_text",
                    )
            projected["input_hash"] = build_h3_input_hash(inp, h3_version=item.h3_version, hash_version=item.hash_version)
            _upsert_semantic_projection(conn, item.source_type, projected)
            _mark_h3_queue_done(conn, item.queue_id)
            conn.commit()
            return True
        except Exception as exc:
            _mark_h3_queue_failed(conn, item.queue_id, str(exc))
            conn.commit()
            return True
