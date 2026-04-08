from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import subprocess
from typing import Any
import uuid

import psycopg
from psycopg.rows import dict_row

from src.backend.core.config import settings
from src.backend.parsing.h2_postprocess import H2_ENRICHMENT_VERSION
from src.backend.parsing.h3_llm import H3_LLM_PROMPT_VERSION
from src.backend.parsing.h3_semantic import H3_VERSION
from src.backend.parsing.source_parsers import SOURCE_TYPES


DEFAULT_BENCHMARK_SIZE = 30
DEFAULT_ROTATING_SIZE = 200
DEFAULT_CANARY_PCT = 0.05


@dataclass(frozen=True)
class SourceRoundConfig:
    source_type: str
    benchmark_n: int
    rotating_n: int
    canary_pct: float


@dataclass(frozen=True)
class VersionState:
    source_type: str
    raw_id: str
    content_hash: str
    parser_version: str
    h2_version: str
    h3_version: str
    h3_prompt_version: str
    h1_status: str
    h2_status: str
    h3_status: str


def _pg_url() -> str:
    return os.getenv("POSTGRES_URL", settings.POSTGRES_URL)


def make_round_id(seed: int) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"audit-{stamp}-{seed}-{uuid.uuid4().hex[:8]}"


def benchmark_size_for_source(source_type: str) -> int:
    if source_type == "dou_documents":
        return 100
    if source_type == "tcu_jurisprudencia_selecionada":
        return 50
    return DEFAULT_BENCHMARK_SIZE


def rotating_size_for_source(source_type: str) -> int:
    if source_type == "dou_documents":
        return 385
    if source_type == "tcu_jurisprudencia_selecionada":
        return 100
    return DEFAULT_ROTATING_SIZE


def config_for_source(source_type: str) -> SourceRoundConfig:
    return SourceRoundConfig(
        source_type=source_type,
        benchmark_n=benchmark_size_for_source(source_type),
        rotating_n=rotating_size_for_source(source_type),
        canary_pct=DEFAULT_CANARY_PCT,
    )


def stable_rank(raw_id: str, seed: int) -> str:
    payload = f"{seed}:{raw_id}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=os.getcwd())
            .strip()
        )
    except Exception:
        return ""


def _current_state_sql(source_type: str) -> str:
    return f"""
        SELECT
            p.source_type,
            p.raw_id,
            p.content_hash,
            p.parser_version,
            COALESCE(p.h2_version, '{H2_ENRICHMENT_VERSION}') AS h2_version,
            COALESCE(s.h3_version, '') AS h3_version,
            COALESCE(s.prompt_version, '') AS h3_prompt_version,
            COALESCE(p.h1_status, '') AS h1_status,
            COALESCE(p.enrichment_status, '') AS h2_status,
            COALESCE(s.semantic_status, '') AS h3_status
        FROM parsed.{source_type} AS p
        LEFT JOIN parsed_semantic.{source_type} AS s
          ON s.raw_id = p.raw_id
    """


def _version_state_from_row(row: dict[str, Any]) -> VersionState:
    return VersionState(
        source_type=str(row["source_type"]),
        raw_id=str(row["raw_id"]),
        content_hash=str(row.get("content_hash") or ""),
        parser_version=str(row.get("parser_version") or ""),
        h2_version=str(row.get("h2_version") or ""),
        h3_version=str(row.get("h3_version") or ""),
        h3_prompt_version=str(row.get("h3_prompt_version") or ""),
        h1_status=str(row.get("h1_status") or ""),
        h2_status=str(row.get("h2_status") or ""),
        h3_status=str(row.get("h3_status") or ""),
    )


def current_states_for_source(
    conn: psycopg.Connection,
    source_type: str,
    *,
    raw_ids: tuple[str, ...] = (),
) -> list[VersionState]:
    where = " WHERE p.raw_id = ANY(%s)" if raw_ids else ""
    params: list[Any] = []
    if raw_ids:
        params.append(list(raw_ids))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_current_state_sql(source_type) + where, params)
        rows = cur.fetchall()
    return [_version_state_from_row(dict(row)) for row in rows]


def current_state_index(
    conn: psycopg.Connection,
    source_type: str,
    *,
    raw_ids: tuple[str, ...] = (),
) -> dict[str, VersionState]:
    return {row.raw_id: row for row in current_states_for_source(conn, source_type, raw_ids=raw_ids)}


def create_round(
    conn: psycopg.Connection,
    *,
    round_id: str,
    seed: int,
    config_json: dict[str, Any],
    triggered_by: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit.round (round_id, seed, config_json, git_sha, triggered_by)
            VALUES (%s, %s, %s::jsonb, %s, %s)
            ON CONFLICT (round_id) DO UPDATE SET
                seed = EXCLUDED.seed,
                config_json = EXCLUDED.config_json,
                git_sha = EXCLUDED.git_sha,
                triggered_by = EXCLUDED.triggered_by
            """,
            (round_id, seed, json.dumps(config_json, ensure_ascii=False), _git_sha(), triggered_by),
        )


def snapshot_population(
    conn: psycopg.Connection,
    *,
    round_id: str,
    source_type: str,
    seed: int,
) -> int:
    eligibility_sql = _current_state_sql(source_type)
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM ({eligibility_sql}) AS eligible")
        row_count = int(cur.fetchone()[0])
        cur.execute(
            """
            INSERT INTO audit.population_snapshot (round_id, source_type, as_of_ts, row_count, eligibility_sql, seed)
            VALUES (%s, %s, NOW(), %s, %s, %s)
            RETURNING snapshot_id
            """,
            (round_id, source_type, row_count, eligibility_sql, seed),
        )
        snapshot_id = int(cur.fetchone()[0])
    return snapshot_id


def has_matching_approval(conn: psycopg.Connection, state: VersionState, *, judge_version: str) -> bool:
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
                state.source_type,
                state.raw_id,
                state.content_hash,
                state.parser_version,
                state.h2_version,
                state.h3_version,
                state.h3_prompt_version,
                judge_version,
            ),
        )
        return cur.fetchone() is not None


def has_matching_process(conn: psycopg.Connection, state: VersionState) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM audit.process_cache
            WHERE source_type = %s
              AND raw_id = %s
              AND content_hash = %s
              AND parser_version = %s
              AND h2_version = %s
              AND h3_version = %s
              AND h3_prompt_version = %s
            LIMIT 1
            """,
            (
                state.source_type,
                state.raw_id,
                state.content_hash,
                state.parser_version,
                state.h2_version,
                state.h3_version,
                state.h3_prompt_version,
            ),
        )
        return cur.fetchone() is not None


def deterministic_pick(states: list[VersionState], *, seed: int, limit: int) -> list[VersionState]:
    ranked = sorted(states, key=lambda state: (stable_rank(state.raw_id, seed), state.raw_id))
    return ranked[:limit]


def bootstrap_benchmark(
    conn: psycopg.Connection,
    *,
    source_type: str,
    seed: int,
    limit: int,
) -> list[str]:
    states = current_states_for_source(conn, source_type)
    selected = deterministic_pick(states, seed=seed, limit=limit)
    raw_ids = [state.raw_id for state in selected]
    with conn.cursor() as cur:
        for raw_id in raw_ids:
            cur.execute(
                """
                INSERT INTO audit.benchmark_registry (source_type, raw_id, created_by)
                VALUES (%s, %s, %s)
                ON CONFLICT (source_type, raw_id) DO NOTHING
                """,
                (source_type, raw_id, "audit_sampler"),
            )
    return raw_ids


def benchmark_ids(conn: psycopg.Connection, source_type: str, *, seed: int, limit: int) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT raw_id
            FROM audit.benchmark_registry
            WHERE source_type = %s
            ORDER BY raw_id ASC
            LIMIT %s
            """,
            (source_type, limit),
        )
        rows = [str(row[0]) for row in cur.fetchall()]
    if rows:
        return rows
    return bootstrap_benchmark(conn, source_type=source_type, seed=seed, limit=limit)


def rotating_states(
    conn: psycopg.Connection,
    source_type: str,
    *,
    seed: int,
    limit: int,
    judge_version: str,
    exclude_raw_ids: set[str],
) -> list[VersionState]:
    states = [
        state
        for state in current_states_for_source(conn, source_type)
        if state.raw_id not in exclude_raw_ids and not has_matching_approval(conn, state, judge_version=judge_version)
    ]
    return deterministic_pick(states, seed=seed, limit=limit)


def canary_states(
    conn: psycopg.Connection,
    source_type: str,
    *,
    seed: int,
    pct: float,
    exclude_raw_ids: set[str],
    judge_version: str,
) -> list[VersionState]:
    approved = [
        state
        for state in current_states_for_source(conn, source_type)
        if state.raw_id not in exclude_raw_ids and has_matching_approval(conn, state, judge_version=judge_version)
    ]
    if not approved:
        return []
    count = max(1, math.ceil(len(approved) * pct))
    return deterministic_pick(approved, seed=seed, limit=count)


def write_cohort(
    conn: psycopg.Connection,
    *,
    round_id: str,
    source_type: str,
    snapshot_id: int,
    cohort_type: str,
    raw_ids: list[str],
    seed: int,
) -> None:
    with conn.cursor() as cur:
        for raw_id in raw_ids:
            cur.execute(
                """
                INSERT INTO audit.cohort (round_id, source_type, raw_id, cohort_type, snapshot_id, selection_seed)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (round_id, source_type, raw_id, cohort_type) DO NOTHING
                """,
                (round_id, source_type, raw_id, cohort_type, snapshot_id, seed),
            )


def plan_source_round(
    conn: psycopg.Connection,
    *,
    round_id: str,
    source_type: str,
    seed: int,
    judge_version: str,
) -> dict[str, Any]:
    source_config = config_for_source(source_type)
    snapshot_id = snapshot_population(conn, round_id=round_id, source_type=source_type, seed=seed)
    benchmark = benchmark_ids(conn, source_type, seed=42, limit=source_config.benchmark_n)
    rotating = rotating_states(
        conn,
        source_type,
        seed=seed,
        limit=source_config.rotating_n,
        judge_version=judge_version,
        exclude_raw_ids=set(benchmark),
    )
    canary = canary_states(
        conn,
        source_type,
        seed=seed + 17,
        pct=source_config.canary_pct,
        exclude_raw_ids=set(benchmark) | {state.raw_id for state in rotating},
        judge_version=judge_version,
    )
    write_cohort(
        conn,
        round_id=round_id,
        source_type=source_type,
        snapshot_id=snapshot_id,
        cohort_type="benchmark",
        raw_ids=benchmark,
        seed=42,
    )
    write_cohort(
        conn,
        round_id=round_id,
        source_type=source_type,
        snapshot_id=snapshot_id,
        cohort_type="rotating",
        raw_ids=[state.raw_id for state in rotating],
        seed=seed,
    )
    write_cohort(
        conn,
        round_id=round_id,
        source_type=source_type,
        snapshot_id=snapshot_id,
        cohort_type="canary",
        raw_ids=[state.raw_id for state in canary],
        seed=seed + 17,
    )
    return {
        "source_type": source_type,
        "snapshot_id": snapshot_id,
        "benchmark": len(benchmark),
        "rotating": len(rotating),
        "canary": len(canary),
    }


def round_raw_ids_by_source(conn: psycopg.Connection, round_id: str) -> dict[str, list[str]]:
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
        rows = cur.fetchall()
    out: dict[str, list[str]] = {}
    for row in rows:
        out.setdefault(str(row["source_type"]), []).append(str(row["raw_id"]))
    return out


def processing_raw_ids_by_source(conn: psycopg.Connection, round_id: str) -> dict[str, list[str]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT source_type, raw_id
            FROM audit.cohort
            WHERE round_id = %s
            ORDER BY source_type ASC, raw_id ASC
            """,
            (round_id,),
        )
        cohort_rows = cur.fetchall()
    grouped: dict[str, list[str]] = {}
    state_cache: dict[str, dict[str, VersionState]] = {}
    for row in cohort_rows:
        source_type = str(row["source_type"])
        raw_id = str(row["raw_id"])
        if source_type not in state_cache:
            state_cache[source_type] = current_state_index(conn, source_type)
        state = state_cache[source_type].get(raw_id)
        if state is None or not has_matching_process(conn, state):
            grouped.setdefault(source_type, []).append(raw_id)
    return grouped


def upsert_process_cache(conn: psycopg.Connection, state: VersionState) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit.process_cache (
                source_type, raw_id, content_hash, parser_version, h2_version, h3_version, h3_prompt_version,
                h1_status, h2_status, h3_status, materialized_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (
                source_type, raw_id, content_hash, parser_version, h2_version, h3_version, h3_prompt_version
            ) DO UPDATE SET
                h1_status = EXCLUDED.h1_status,
                h2_status = EXCLUDED.h2_status,
                h3_status = EXCLUDED.h3_status,
                materialized_at = NOW()
            """,
            (
                state.source_type,
                state.raw_id,
                state.content_hash,
                state.parser_version,
                state.h2_version,
                state.h3_version,
                state.h3_prompt_version,
                state.h1_status,
                state.h2_status,
                state.h3_status,
            ),
        )


def mark_round_finished(conn: psycopg.Connection, round_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE audit.round SET finished_at = NOW() WHERE round_id = %s", (round_id,))


def round_sources(conn: psycopg.Connection, round_id: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT source_type FROM audit.cohort WHERE round_id = %s ORDER BY source_type ASC",
            (round_id,),
        )
        return [str(row[0]) for row in cur.fetchall()]
