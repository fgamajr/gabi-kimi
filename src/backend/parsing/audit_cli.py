from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from ops.generate_data_catalog_html import generate_html
from src.backend.core.config import settings
from src.backend.parsing.audit_judge import (
    JUDGE_CONTRACT_VERSION,
    JUDGE_DIMENSIONS,
    JUDGE_PROMPT_VERSION,
    JUDGE_VERSION,
    JudgeDimension,
    PanelOpinion,
    judge_item,
    panel_healthcheck,
)
from src.backend.parsing.audit_sampler import (
    SOURCE_TYPES,
    create_round,
    current_state_index,
    make_round_id,
    mark_round_finished,
    plan_source_round,
    processing_raw_ids_by_source,
    round_raw_ids_by_source,
    upsert_process_cache,
)


def _pg_url() -> str:
    return os.getenv("POSTGRES_URL", settings.POSTGRES_URL)


def _parse_sources(value: str) -> list[str]:
    if not value:
        return list(SOURCE_TYPES)
    out = [item.strip() for item in value.split(",") if item.strip()]
    invalid = [item for item in out if item not in SOURCE_TYPES]
    if invalid:
        raise SystemExit(f"invalid source(s): {', '.join(invalid)}")
    return out


def _write_ids_file(path: Path, raw_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(raw_ids) + ("\n" if raw_ids else ""), encoding="utf-8")


def _load_round_rows(conn: psycopg.Connection, round_id: str) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT source_type, raw_id, cohort_type
            FROM audit.cohort
            WHERE round_id = %s
            ORDER BY source_type ASC, cohort_type ASC, raw_id ASC
            """,
            (round_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def _load_parsed_row(conn: psycopg.Connection, source_type: str, raw_id: str) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT * FROM parsed.{source_type} WHERE raw_id = %s", (raw_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def _load_semantic_row(conn: psycopg.Connection, source_type: str, raw_id: str) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT * FROM parsed_semantic.{source_type} WHERE raw_id = %s", (raw_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def _load_raw_row(conn: psycopg.Connection, source_type: str, raw_id: str) -> dict[str, Any] | None:
    table_candidates = (f"{source_type}_raw", f"{source_type}_raw_data")
    with conn.cursor(row_factory=dict_row) as cur:
        for table_name in table_candidates:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'raw' AND table_name = %s
                LIMIT 1
                """,
                (table_name,),
            )
            if cur.fetchone() is None:
                continue
            cur.execute(f"SELECT * FROM raw.{table_name} WHERE id = %s", (raw_id,))
            row = cur.fetchone()
            if row is not None:
                return dict(row)
    return None


def _has_cached_approval(conn: psycopg.Connection, *, source_type: str, raw_id: str, judge_version: str) -> bool:
    parsed_row = _load_parsed_row(conn, source_type, raw_id)
    if not parsed_row:
        return False
    semantic_row = _load_semantic_row(conn, source_type, raw_id) or {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM audit.approval_cache
            WHERE source_type = %s
              AND raw_id = %s
              AND content_hash = %s
              AND parser_version = %s
              AND h2_version = %s
              AND h3_version = %s
              AND h3_prompt_version = %s
              AND judge_version = %s
              AND final_verdict = 'approved'
            LIMIT 1
            """,
            (
                source_type,
                raw_id,
                str(parsed_row.get("content_hash") or ""),
                str(parsed_row.get("parser_version") or ""),
                str(parsed_row.get("h2_version") or ""),
                str(semantic_row.get("h3_version") or ""),
                str(semantic_row.get("prompt_version") or ""),
                judge_version,
            ),
        )
        return cur.fetchone() is not None


def _cached_expert_opinions(
    conn: psycopg.Connection,
    *,
    source_type: str,
    raw_id: str,
    parsed_row: dict[str, Any],
    semantic_row: dict[str, Any] | None,
) -> dict[str, PanelOpinion]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT expert_model_id, final_verdict, confidence, dimensions_json, issues_json, rationale, raw_response_json
            FROM audit.expert_opinion_cache
            WHERE source_type = %s
              AND raw_id = %s
              AND content_hash = %s
              AND parser_version = %s
              AND h2_version = %s
              AND h3_version = %s
              AND h3_prompt_version = %s
              AND judge_contract_version = %s
            """,
            (
                source_type,
                raw_id,
                str(parsed_row.get("content_hash") or ""),
                str(parsed_row.get("parser_version") or ""),
                str(parsed_row.get("h2_version") or ""),
                str((semantic_row or {}).get("h3_version") or ""),
                str((semantic_row or {}).get("prompt_version") or ""),
                JUDGE_CONTRACT_VERSION,
            ),
        )
        rows = cur.fetchall()
    cached: dict[str, PanelOpinion] = {}
    for row in rows:
        dimensions_payload = row["dimensions_json"] or {}
        dimensions = {}
        for dimension in JUDGE_DIMENSIONS:
            item = dimensions_payload.get(dimension) if isinstance(dimensions_payload, dict) else {}
            score = float(item.get("score", 0.0)) if isinstance(item, dict) else 0.0
            rationale = str(item.get("rationale") or "cached") if isinstance(item, dict) else "cached"
            dimensions[dimension] = JudgeDimension(score=score, rationale=rationale)
        issues_payload = row["issues_json"] if isinstance(row["issues_json"], list) else []
        cached[str(row["expert_model_id"])] = PanelOpinion(
            role="expert",
            agent_name=str(row["expert_model_id"]),
            provider="cached",
            model_id=str(row["expert_model_id"]),
            final_verdict=str(row["final_verdict"]),
            dimensions=dimensions,
            confidence=float(row["confidence"] or 0.0),
            issues=tuple(str(item) for item in issues_payload),
            rationale=str(row["rationale"] or ""),
            latency_ms=0.0,
            raw_response=row["raw_response_json"] if isinstance(row["raw_response_json"], dict) else {},
            error="",
        )
    return cached


def _persist_judge_result(
    conn: psycopg.Connection,
    *,
    round_id: str,
    source_type: str,
    raw_id: str,
    cohort_type: str,
    parsed_row: dict[str, Any],
    semantic_row: dict[str, Any] | None,
    verdict: Any,
    raw_row: dict[str, Any] | None,
    approved_by: str,
    judge_mode: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM audit.judge_verdict
            WHERE round_id = %s AND source_type = %s AND raw_id = %s
            """,
            (round_id, source_type, raw_id),
        )
        for opinion in [*verdict.experts, *verdict.jurors]:
            for dimension, item in opinion.dimensions.items():
                cur.execute(
                    """
                    INSERT INTO audit.judge_verdict (
                        round_id, source_type, raw_id, cohort_type, judge_version, judge_model, judge_prompt_version,
                        judge_method, role, final_verdict, dimension, score, rationale, confidence, error, latency_ms, raw_response_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        round_id,
                        source_type,
                        raw_id,
                        cohort_type,
                        JUDGE_CONTRACT_VERSION,
                        opinion.model_id,
                        verdict.prompt_version,
                        verdict.judge_method,
                        opinion.role,
                        opinion.final_verdict,
                        dimension,
                        item.score,
                        item.rationale,
                        opinion.confidence,
                        opinion.error,
                        opinion.latency_ms,
                        json.dumps(opinion.raw_response, ensure_ascii=False),
                    ),
                )
        for dimension, item in verdict.dimensions.items():
            cur.execute(
                """
                INSERT INTO audit.judge_verdict (
                    round_id, source_type, raw_id, cohort_type, judge_version, judge_model, judge_prompt_version,
                    judge_method, role, final_verdict, dimension, score, rationale, confidence, error, latency_ms, raw_response_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    round_id,
                    source_type,
                    raw_id,
                    cohort_type,
                    JUDGE_CONTRACT_VERSION,
                    verdict.model_id,
                    verdict.prompt_version,
                    verdict.judge_method,
                    "aggregate",
                    verdict.final_verdict,
                    dimension,
                    item.score,
                    item.rationale,
                    1.0 if verdict.quorum_ok else 0.0,
                    verdict.error,
                    0.0,
                    json.dumps(
                        {
                            "summary_rationale": verdict.summary_rationale,
                            "panel_models": list(verdict.panel_models),
                            "raw_excerpt_keys": list((raw_row or {}).keys())[:20],
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
        for opinion in verdict.experts:
            if opinion.error:
                continue
            cur.execute(
                """
                INSERT INTO audit.expert_opinion_cache (
                    source_type, raw_id, content_hash, parser_version, h2_version, h3_version, h3_prompt_version,
                    judge_contract_version, expert_model_id, final_verdict, confidence, dimensions_json, issues_json,
                    rationale, raw_response_json, responded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, NOW())
                ON CONFLICT (
                    source_type, raw_id, content_hash, parser_version, h2_version, h3_version, h3_prompt_version,
                    judge_contract_version, expert_model_id
                ) DO UPDATE SET
                    final_verdict = EXCLUDED.final_verdict,
                    confidence = EXCLUDED.confidence,
                    dimensions_json = EXCLUDED.dimensions_json,
                    issues_json = EXCLUDED.issues_json,
                    rationale = EXCLUDED.rationale,
                    raw_response_json = EXCLUDED.raw_response_json,
                    responded_at = NOW()
                """,
                (
                    source_type,
                    raw_id,
                    str(parsed_row.get("content_hash") or ""),
                    str(parsed_row.get("parser_version") or ""),
                    str(parsed_row.get("h2_version") or ""),
                    str((semantic_row or {}).get("h3_version") or ""),
                    str((semantic_row or {}).get("prompt_version") or ""),
                    JUDGE_CONTRACT_VERSION,
                    opinion.model_id,
                    opinion.final_verdict,
                    opinion.confidence,
                    json.dumps(
                        {
                            key: {"score": value.score, "rationale": value.rationale}
                            for key, value in opinion.dimensions.items()
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(list(opinion.issues), ensure_ascii=False),
                    opinion.rationale,
                    json.dumps(opinion.raw_response, ensure_ascii=False),
                ),
            )
        cur.execute(
            """
            INSERT INTO audit.judge_status (
                round_id, source_type, raw_id, judge_contract_version, judge_mode, status, attempts, final_verdict,
                quorum_ok, experts_used, jurors_used, panel_models, last_error, last_summary_json, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, 1, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, NOW())
            ON CONFLICT (round_id, source_type, raw_id) DO UPDATE SET
                judge_contract_version = EXCLUDED.judge_contract_version,
                judge_mode = EXCLUDED.judge_mode,
                status = EXCLUDED.status,
                attempts = audit.judge_status.attempts + 1,
                final_verdict = EXCLUDED.final_verdict,
                quorum_ok = EXCLUDED.quorum_ok,
                experts_used = EXCLUDED.experts_used,
                jurors_used = EXCLUDED.jurors_used,
                panel_models = EXCLUDED.panel_models,
                last_error = EXCLUDED.last_error,
                last_summary_json = EXCLUDED.last_summary_json,
                updated_at = NOW()
            """,
            (
                round_id,
                source_type,
                raw_id,
                JUDGE_CONTRACT_VERSION,
                judge_mode,
                verdict.status,
                verdict.final_verdict if verdict.status == "judged" else None,
                verdict.quorum_ok,
                verdict.experts_used,
                verdict.jurors_used,
                json.dumps(list(verdict.panel_models), ensure_ascii=False),
                verdict.error or None,
                json.dumps(
                    {
                        "summary_rationale": verdict.summary_rationale,
                        "judge_method": verdict.judge_method,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        if verdict.status == "judged":
            cur.execute(
                """
                INSERT INTO audit.approval_cache (
                    source_type, raw_id, content_hash, parser_version, h2_version, h3_version, h3_prompt_version,
                    judge_version, final_verdict, approved_by, origin_round_id, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (
                    source_type, raw_id, content_hash, parser_version, h2_version, h3_version, h3_prompt_version, judge_version
                ) DO UPDATE SET
                    final_verdict = EXCLUDED.final_verdict,
                    approved_by = EXCLUDED.approved_by,
                    origin_round_id = EXCLUDED.origin_round_id,
                    notes = EXCLUDED.notes,
                    approved_at = NOW()
                """,
                (
                    source_type,
                    raw_id,
                    str(parsed_row.get("content_hash") or ""),
                    str(parsed_row.get("parser_version") or ""),
                    str(parsed_row.get("h2_version") or ""),
                    str((semantic_row or {}).get("h3_version") or ""),
                    str((semantic_row or {}).get("prompt_version") or ""),
                    JUDGE_CONTRACT_VERSION,
                    verdict.final_verdict,
                    approved_by,
                    round_id,
                    f"judge_prompt_version={JUDGE_PROMPT_VERSION}",
                ),
            )


def _plan_round(args: argparse.Namespace) -> None:
    sources = _parse_sources(args.sources)
    round_id = args.round_id or make_round_id(args.seed)
    config_json = {
        "sources": sources,
        "seed": args.seed,
        "judge_version": JUDGE_CONTRACT_VERSION,
        "judge_mode": args.judge_mode,
    }
    results: list[dict[str, Any]] = []
    with psycopg.connect(_pg_url()) as conn:
        create_round(
            conn,
            round_id=round_id,
            seed=args.seed,
            config_json=config_json,
            triggered_by=args.triggered_by,
        )
        for source_type in sources:
            results.append(
                plan_source_round(
                    conn,
                    round_id=round_id,
                    source_type=source_type,
                    seed=args.seed,
                    judge_version=JUDGE_CONTRACT_VERSION,
                )
            )
        conn.commit()
    print(json.dumps({"round_id": round_id, "sources": results}, ensure_ascii=False))


def _export_round_ids(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    manifest: dict[str, Any] = {"round_id": args.round_id, "sources": {}}
    with psycopg.connect(_pg_url()) as conn:
        all_ids = round_raw_ids_by_source(conn, args.round_id)
        process_ids = processing_raw_ids_by_source(conn, args.round_id)
    for source_type, raw_ids in all_ids.items():
        all_path = output_dir / f"{source_type}.all.txt"
        process_path = output_dir / f"{source_type}.process.txt"
        _write_ids_file(all_path, raw_ids)
        _write_ids_file(process_path, process_ids.get(source_type, []))
        manifest["sources"][source_type] = {
            "all": str(all_path),
            "process": str(process_path),
            "all_count": len(raw_ids),
            "process_count": len(process_ids.get(source_type, [])),
        }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


def _judge_round(args: argparse.Namespace) -> None:
    health = panel_healthcheck(args.judge_mode)
    if args.judge_mode == "official_judge" and not health["ready"]:
        raise SystemExit(json.dumps({"judge_mode": args.judge_mode, "errors": health["errors"]}, ensure_ascii=False))
    with psycopg.connect(_pg_url()) as conn:
        rows = _load_round_rows(conn, args.round_id)
        state_cache: dict[str, dict[str, Any]] = {}
        judged = 0
        skipped = 0
        pending = 0
        failed = 0
        for row in rows:
            source_type = str(row["source_type"])
            raw_id = str(row["raw_id"])
            cohort_type = str(row["cohort_type"])
            parsed_row = _load_parsed_row(conn, source_type, raw_id)
            if not parsed_row:
                continue
            semantic_row = _load_semantic_row(conn, source_type, raw_id)
            raw_row = _load_raw_row(conn, source_type, raw_id)
            if source_type not in state_cache:
                state_cache[source_type] = current_state_index(conn, source_type)
            state = state_cache[source_type].get(raw_id)
            if state is not None:
                upsert_process_cache(conn, state)
            if (not args.force_rejudge) and cohort_type != "canary" and _has_cached_approval(
                conn,
                source_type=source_type,
                raw_id=raw_id,
                judge_version=JUDGE_CONTRACT_VERSION,
            ):
                skipped += 1
                continue
            cached_experts = _cached_expert_opinions(
                conn,
                source_type=source_type,
                raw_id=raw_id,
                parsed_row=parsed_row,
                semantic_row=semantic_row,
            )
            verdict = judge_item(
                source_type=source_type,
                parsed_row=parsed_row,
                semantic_row=semantic_row,
                raw_row=raw_row,
                model=args.model,
                judge_mode=args.judge_mode,
                cached_expert_opinions=cached_experts,
            )
            _persist_judge_result(
                conn,
                round_id=args.round_id,
                source_type=source_type,
                raw_id=raw_id,
                cohort_type=cohort_type,
                parsed_row=parsed_row,
                semantic_row=semantic_row,
                verdict=verdict,
                raw_row=raw_row,
                approved_by=args.approved_by,
                judge_mode=args.judge_mode,
            )
            if verdict.status == "judged":
                judged += 1
            elif verdict.status == "pending_judge":
                pending += 1
            else:
                failed += 1
        mark_round_finished(conn, args.round_id)
        conn.commit()
    summary = {
        "round_id": args.round_id,
        "judge_mode": args.judge_mode,
        "judged": judged,
        "skipped": skipped,
        "pending_judge": pending,
        "failed": failed,
        "panel_health": health,
    }
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


def _report_round(args: argparse.Namespace) -> None:
    out = Path(args.output)
    generate_html(limit=args.limit, output=out, mode=args.mode, round_id=args.round_id)
    print(json.dumps({"round_id": args.round_id, "output": str(out)}, ensure_ascii=False))


def _promote_benchmark(args: argparse.Namespace) -> None:
    with psycopg.connect(_pg_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit.benchmark_registry (source_type, raw_id, created_by, origin_round_id)
                SELECT source_type, raw_id, %s, MAX(origin_round_id)
                FROM audit.approval_cache
                WHERE source_type = %s AND final_verdict = 'approved'
                GROUP BY source_type, raw_id
                HAVING COUNT(*) >= %s
                ON CONFLICT (source_type, raw_id) DO NOTHING
                """,
                (args.created_by, args.source, args.min_rounds),
            )
        conn.commit()
    print(json.dumps({"source": args.source, "min_rounds": args.min_rounds}, ensure_ascii=False))


def _assessment_summary(
    conn: psycopg.Connection,
    *,
    round_id: str,
    min_approval_rate: float,
    min_benchmark_approval_rate: float,
    min_canary_approval_rate: float,
    max_needs_review_rate: float,
    max_rejected_rate: float,
) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            WITH latest_verdict AS (
                SELECT DISTINCT ON (source_type, raw_id)
                    source_type,
                    raw_id,
                    final_verdict,
                    approved_at
                FROM audit.approval_cache
                ORDER BY source_type, raw_id, approved_at DESC
            )
            SELECT
                c.source_type,
                c.cohort_type,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE lv.final_verdict = 'approved') AS approved,
                COUNT(*) FILTER (WHERE lv.final_verdict = 'needs_review') AS needs_review,
                COUNT(*) FILTER (WHERE lv.final_verdict = 'rejected') AS rejected,
                COUNT(*) FILTER (
                    WHERE (js.status IS NULL AND lv.final_verdict IS NULL)
                       OR js.status IN ('pending_judge', 'judge_failed_retryable', 'judge_failed_terminal')
                ) AS pending_judge
            FROM audit.cohort c
            LEFT JOIN latest_verdict lv
              ON lv.source_type = c.source_type
             AND lv.raw_id = c.raw_id
            LEFT JOIN audit.judge_status js
              ON js.round_id = c.round_id
             AND js.source_type = c.source_type
             AND js.raw_id = c.raw_id
            WHERE c.round_id = %s
            GROUP BY c.source_type, c.cohort_type
            ORDER BY c.source_type, c.cohort_type
            """,
            (round_id,),
        )
        rows = [dict(row) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT
                source_type,
                raw_id,
                AVG(score) AS avg_score
            FROM audit.judge_verdict
            WHERE round_id = %s
            GROUP BY source_type, raw_id
            ORDER BY avg_score ASC, source_type ASC, raw_id ASC
            LIMIT 25
            """,
            (round_id,),
        )
        low_rows = [dict(row) for row in cur.fetchall()]

    by_source: dict[str, Any] = {}
    for row in rows:
        source_type = str(row["source_type"])
        cohort_type = str(row["cohort_type"])
        total = int(row["total"] or 0)
        approved = int(row["approved"] or 0)
        needs_review = int(row["needs_review"] or 0)
        rejected = int(row["rejected"] or 0)
        pending_judge = int(row["pending_judge"] or 0)
        approval_rate = (approved / total) if total else 0.0
        needs_review_rate = (needs_review / total) if total else 0.0
        rejected_rate = (rejected / total) if total else 0.0
        pending_rate = (pending_judge / total) if total else 0.0
        by_source.setdefault(source_type, {"cohorts": {}, "gate_passed": True, "failures": []})
        by_source[source_type]["cohorts"][cohort_type] = {
            "total": total,
            "approved": approved,
            "needs_review": needs_review,
            "rejected": rejected,
            "pending_judge": pending_judge,
            "approval_rate": round(approval_rate, 4),
            "needs_review_rate": round(needs_review_rate, 4),
            "rejected_rate": round(rejected_rate, 4),
            "pending_rate": round(pending_rate, 4),
        }

        required_approval = min_approval_rate
        if cohort_type == "benchmark":
            required_approval = min_benchmark_approval_rate
        elif cohort_type == "canary":
            required_approval = min_canary_approval_rate
        if total:
            if approval_rate < required_approval:
                by_source[source_type]["gate_passed"] = False
                by_source[source_type]["failures"].append(
                    f"{cohort_type}:approval_rate<{required_approval:.2f}"
                )
            if needs_review_rate > max_needs_review_rate:
                by_source[source_type]["gate_passed"] = False
                by_source[source_type]["failures"].append(
                    f"{cohort_type}:needs_review_rate>{max_needs_review_rate:.2f}"
                )
            if rejected_rate > max_rejected_rate:
                by_source[source_type]["gate_passed"] = False
                by_source[source_type]["failures"].append(
                    f"{cohort_type}:rejected_rate>{max_rejected_rate:.2f}"
                )
            if pending_judge > 0:
                by_source[source_type]["gate_passed"] = False
                by_source[source_type]["failures"].append(
                    f"{cohort_type}:pending_judge={pending_judge}"
                )

    failed_examples: dict[str, list[dict[str, Any]]] = {}
    for row in low_rows:
        failed_examples.setdefault(str(row["source_type"]), []).append(
            {"raw_id": str(row["raw_id"]), "avg_score": round(float(row["avg_score"] or 0.0), 4)}
        )

    overall_passed = all(item.get("gate_passed", False) for item in by_source.values()) if by_source else False
    return {
        "round_id": round_id,
        "gate_passed": overall_passed,
        "thresholds": {
            "min_approval_rate": min_approval_rate,
            "min_benchmark_approval_rate": min_benchmark_approval_rate,
            "min_canary_approval_rate": min_canary_approval_rate,
            "max_needs_review_rate": max_needs_review_rate,
            "max_rejected_rate": max_rejected_rate,
        },
        "sources": by_source,
        "lowest_scoring_items": failed_examples,
    }


def _assess_round(args: argparse.Namespace) -> None:
    with psycopg.connect(_pg_url()) as conn:
        summary = _assessment_summary(
            conn,
            round_id=args.round_id,
            min_approval_rate=args.min_approval_rate,
            min_benchmark_approval_rate=args.min_benchmark_approval_rate,
            min_canary_approval_rate=args.min_canary_approval_rate,
            max_needs_review_rate=args.max_needs_review_rate,
            max_rejected_rate=args.max_rejected_rate,
        )
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    if not summary["gate_passed"]:
        raise SystemExit(2)


def _panel_health(args: argparse.Namespace) -> None:
    summary = panel_healthcheck(args.judge_mode)
    print(json.dumps(summary, ensure_ascii=False))
    if args.judge_mode == "official_judge" and not summary["ready"]:
        raise SystemExit(2)


def _calibrate_panel(args: argparse.Namespace) -> None:
    with psycopg.connect(_pg_url()) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                WITH latest_panel AS (
                    SELECT DISTINCT ON (source_type, raw_id)
                        source_type,
                        raw_id,
                        final_verdict
                    FROM audit.approval_cache
                    ORDER BY source_type, raw_id, approved_at DESC
                ),
                latest_human AS (
                    SELECT DISTINCT ON (source_type, raw_id)
                        source_type,
                        raw_id,
                        final_verdict
                    FROM audit.human_review
                    WHERE (%s = '' OR round_id = %s)
                    ORDER BY source_type, raw_id, created_at DESC
                )
                SELECT
                    h.source_type,
                    h.raw_id,
                    h.final_verdict AS human_verdict,
                    p.final_verdict AS panel_verdict
                FROM latest_human h
                LEFT JOIN latest_panel p
                  ON p.source_type = h.source_type
                 AND p.raw_id = h.raw_id
                ORDER BY h.source_type, h.raw_id
                """,
                (args.round_id, args.round_id),
            )
            rows = [dict(row) for row in cur.fetchall()]
    compared = 0
    matched = 0
    by_source: dict[str, dict[str, int]] = {}
    mismatches: list[dict[str, Any]] = []
    for row in rows:
        source_type = str(row["source_type"])
        human_verdict = str(row["human_verdict"] or "")
        panel_verdict = str(row["panel_verdict"] or "")
        source_stats = by_source.setdefault(source_type, {"compared": 0, "matched": 0})
        if not panel_verdict:
            mismatches.append({"source_type": source_type, "raw_id": row["raw_id"], "human": human_verdict, "panel": "missing"})
            continue
        compared += 1
        source_stats["compared"] += 1
        if human_verdict == panel_verdict:
            matched += 1
            source_stats["matched"] += 1
        else:
            mismatches.append({"source_type": source_type, "raw_id": row["raw_id"], "human": human_verdict, "panel": panel_verdict})
    summary = {
        "round_id": args.round_id or None,
        "compared": compared,
        "matched": matched,
        "agreement": round((matched / compared), 4) if compared else 0.0,
        "min_agreement": args.min_agreement,
        "sources": {
            source: {
                "compared": stats["compared"],
                "matched": stats["matched"],
                "agreement": round((stats["matched"] / stats["compared"]), 4) if stats["compared"] else 0.0,
            }
            for source, stats in by_source.items()
        },
        "mismatches": mismatches[:50],
    }
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    if compared == 0 or summary["agreement"] < args.min_agreement:
        raise SystemExit(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Round-based audit workflow for H1/H2/H3")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan-round", help="Create round, population snapshots, and cohorts")
    p_plan.add_argument("--sources", default="")
    p_plan.add_argument("--seed", type=int, default=42)
    p_plan.add_argument("--round-id", default="")
    p_plan.add_argument("--triggered-by", default=os.getenv("USER", "codex"))
    p_plan.add_argument("--judge-mode", default=settings.AUDIT_JUDGE_MODE)

    p_export = sub.add_parser("export-round-ids", help="Export round IDs to raw-id files")
    p_export.add_argument("--round-id", required=True)
    p_export.add_argument("--output-dir", required=True)

    p_judge = sub.add_parser("judge-round", help="Run judge over round items and update caches")
    p_judge.add_argument("--round-id", required=True)
    p_judge.add_argument("--model", default=os.getenv("H2_LLM_MODEL", "qwen2.5:7b-instruct"))
    p_judge.add_argument("--approved-by", default=os.getenv("USER", "codex"))
    p_judge.add_argument("--judge-mode", default=settings.AUDIT_JUDGE_MODE)
    p_judge.add_argument("--force-rejudge", action="store_true")
    p_judge.add_argument("--output", default="")

    p_health = sub.add_parser("panel-health", help="Validate audit panel configuration and quorum")
    p_health.add_argument("--judge-mode", default=settings.AUDIT_JUDGE_MODE)

    p_report = sub.add_parser("report-round", help="Generate HTML report for a round")
    p_report.add_argument("--round-id", required=True)
    p_report.add_argument("--output", required=True)
    p_report.add_argument("--mode", choices=("tabs", "parsed-only"), default="parsed-only")
    p_report.add_argument("--limit", type=int, default=0)

    p_assess = sub.add_parser("assess-round", help="Apply objective quality gate to a round")
    p_assess.add_argument("--round-id", required=True)
    p_assess.add_argument("--output", default="")
    p_assess.add_argument("--min-approval-rate", type=float, default=0.85)
    p_assess.add_argument("--min-benchmark-approval-rate", type=float, default=0.90)
    p_assess.add_argument("--min-canary-approval-rate", type=float, default=0.80)
    p_assess.add_argument("--max-needs-review-rate", type=float, default=0.15)
    p_assess.add_argument("--max-rejected-rate", type=float, default=0.10)

    p_promote = sub.add_parser("promote-benchmark", help="Promote consistently approved items to benchmark")
    p_promote.add_argument("--source", choices=list(SOURCE_TYPES), required=True)
    p_promote.add_argument("--min-rounds", type=int, default=3)
    p_promote.add_argument("--created-by", default=os.getenv("USER", "codex"))

    p_calibrate = sub.add_parser("calibrate-panel", help="Compare panel verdicts against human reviews")
    p_calibrate.add_argument("--round-id", default="")
    p_calibrate.add_argument("--min-agreement", type=float, default=settings.AUDIT_PANEL_CALIBRATION_MIN_AGREEMENT)
    p_calibrate.add_argument("--output", default="")

    args = parser.parse_args()
    if args.cmd == "plan-round":
        _plan_round(args)
        return
    if args.cmd == "export-round-ids":
        _export_round_ids(args)
        return
    if args.cmd == "judge-round":
        _judge_round(args)
        return
    if args.cmd == "panel-health":
        _panel_health(args)
        return
    if args.cmd == "report-round":
        _report_round(args)
        return
    if args.cmd == "assess-round":
        _assess_round(args)
        return
    if args.cmd == "calibrate-panel":
        _calibrate_panel(args)
        return
    _promote_benchmark(args)


if __name__ == "__main__":
    main()
