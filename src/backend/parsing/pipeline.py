from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any

import psycopg
from psycopg.rows import dict_row

from src.backend.core.config import settings
from src.backend.parsing.h2_llm import build_h2_prompt, call_local_llm
from src.backend.parsing.h2_semantic import parse_spans, render_tagged_xml, tags_flat, validate_spans
from src.backend.parsing.h2_vocab import ALLOWED_TAGS_VERSION, tags_for_source
from src.backend.parsing.source_parsers import PARSER_REGISTRY, SOURCE_TYPES

RAW_TABLE_BY_SOURCE: dict[str, str] = {
    "dou_documents": "raw.dou_documents_raw",
    "tcu_acordao_completo": "raw.tcu_acordao_completo_raw",
    "tcu_jurisprudencia_selecionada": "raw.tcu_jurisprudencia_selecionada_raw",
    "tcu_resposta_consulta": "raw.tcu_resposta_consulta_raw",
    "tcu_sumula": "raw.tcu_sumula_raw",
    "tcu_boletim_jurisprudencia": "raw.tcu_boletim_jurisprudencia_raw",
    "tcu_boletim_pessoal": "raw.tcu_boletim_pessoal_raw",
    "tcu_boletim_informativo_lc": "raw.tcu_boletim_informativo_lc_raw",
    "tcu_normas": "raw.tcu_normas_raw",
    "tcu_btcu": "raw.tcu_btcu_raw",
    "tcu_publicacoes": "raw.tcu_publicacoes_raw",
}


def _pg_url() -> str:
    return os.getenv("POSTGRES_URL", settings.POSTGRES_URL)


def _parsed_table(source_type: str) -> str:
    return f"parsed.{source_type}"


def _row_all_fields_sql(source_type: str, limit: int, offset: int) -> tuple[str, tuple[Any, ...]]:
    table = RAW_TABLE_BY_SOURCE[source_type]
    if source_type in {"dou_documents", "tcu_btcu", "tcu_publicacoes"}:
        sql = f"""
            SELECT id, all_fields
            FROM {table}
            ORDER BY dumped_at DESC, id
            LIMIT %s OFFSET %s
        """
        return sql, (limit, offset)
    sql = f"""
        SELECT id, (to_jsonb(t) - 'id' - 'source_type' - 'dumped_at') AS all_fields
        FROM {table} AS t
        ORDER BY dumped_at DESC, id
        LIMIT %s OFFSET %s
    """
    return sql, (limit, offset)


def _enrichment_input_hash(source_type: str, body_tagged_xml: str, content_hash: str, h2_version: str) -> str:
    payload = f"{source_type}|{content_hash}|{h2_version}|{body_tagged_xml}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _upsert_parsed(conn: psycopg.Connection, source_type: str, parsed: Any, prompt_version: str, h2_version: str) -> None:
    table = _parsed_table(source_type)
    s = parsed.structured_fields
    h1 = parsed.h1
    pub_date = s.get("pub_date") or s.get("data_publicacao") or s.get("data_dou")
    data_sessao = s.get("data_sessao")
    numero_acordao = s.get("numero_acordao")
    ano_acordao = s.get("ano_acordao")
    numero_norma = s.get("numero_norma")
    ano_norma = s.get("ano_norma")
    colegiado = s.get("colegiado")
    orgao_emissor = s.get("orgao_emissor")
    art_type = s.get("art_type")
    tipo_norma = s.get("tipo_norma")
    enrichment_input_hash = _enrichment_input_hash(source_type, parsed.body_tagged_xml, parsed.content_hash, h2_version)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {table} (
                raw_id, source_type, pub_date, data_sessao, numero_acordao, ano_acordao,
                numero_norma, ano_norma, colegiado, orgao_emissor, art_type, tipo_norma,
                structured_fields, section_map, body_tagged_xml, content_hash, parser_version,
                h1_tipo, h1_subtipo, h1_confidence, h1_method, h1_version, h1_status,
                enrichment_status, h2_version, prompt_version, enrichment_input_hash,
                parsed_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s, NOW(), NOW()
            )
            ON CONFLICT (raw_id) DO UPDATE SET
                pub_date = EXCLUDED.pub_date,
                data_sessao = EXCLUDED.data_sessao,
                numero_acordao = EXCLUDED.numero_acordao,
                ano_acordao = EXCLUDED.ano_acordao,
                numero_norma = EXCLUDED.numero_norma,
                ano_norma = EXCLUDED.ano_norma,
                colegiado = EXCLUDED.colegiado,
                orgao_emissor = EXCLUDED.orgao_emissor,
                art_type = EXCLUDED.art_type,
                tipo_norma = EXCLUDED.tipo_norma,
                structured_fields = EXCLUDED.structured_fields,
                section_map = EXCLUDED.section_map,
                body_tagged_xml = EXCLUDED.body_tagged_xml,
                content_hash = EXCLUDED.content_hash,
                parser_version = EXCLUDED.parser_version,
                h1_tipo = EXCLUDED.h1_tipo,
                h1_subtipo = EXCLUDED.h1_subtipo,
                h1_confidence = EXCLUDED.h1_confidence,
                h1_method = EXCLUDED.h1_method,
                h1_version = EXCLUDED.h1_version,
                h1_status = EXCLUDED.h1_status,
                enrichment_status = CASE
                    WHEN {table}.enrichment_input_hash = EXCLUDED.enrichment_input_hash
                     AND {table}.h2_version = EXCLUDED.h2_version
                     AND {table}.prompt_version = EXCLUDED.prompt_version
                    THEN {table}.enrichment_status
                    ELSE 'pending'
                END,
                h2_version = EXCLUDED.h2_version,
                prompt_version = EXCLUDED.prompt_version,
                enrichment_input_hash = EXCLUDED.enrichment_input_hash,
                updated_at = NOW();
            """,
            (
                parsed.raw_id,
                source_type,
                pub_date,
                data_sessao,
                numero_acordao,
                ano_acordao,
                numero_norma,
                ano_norma,
                colegiado,
                orgao_emissor,
                art_type,
                tipo_norma,
                json.dumps(parsed.structured_fields, ensure_ascii=False, default=str),
                json.dumps(parsed.section_map, ensure_ascii=False, default=str),
                parsed.body_tagged_xml,
                parsed.content_hash,
                parsed.parser_version,
                h1.tipo if h1 else None,
                h1.subtipo if h1 else None,
                h1.confidence if h1 else None,
                h1.method if h1 else None,
                h1.version if h1 else None,
                h1.status if h1 else None,
                h2_version,
                prompt_version,
                enrichment_input_hash,
            ),
        )
        cur.execute(
            """
            INSERT INTO parsed.enrichment_queue (
                source_type, raw_id, content_hash, h2_version, prompt_version, input_hash,
                status, next_retry_at, attempts, priority, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, 'pending', NOW(), 0, 100, NOW(), NOW())
            ON CONFLICT (source_type, raw_id, h2_version, prompt_version, input_hash)
            DO UPDATE SET
                status = 'pending',
                next_retry_at = NOW(),
                updated_at = NOW();
            """,
            (
                source_type,
                parsed.raw_id,
                parsed.content_hash,
                h2_version,
                prompt_version,
                enrichment_input_hash,
            ),
        )


def run_parse(source_type: str, *, limit: int, offset: int, prompt_version: str, h2_version: str) -> int:
    parser = PARSER_REGISTRY[source_type]
    sql, params = _row_all_fields_sql(source_type, limit, offset)
    parsed_count = 0
    with psycopg.connect(_pg_url()) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        for row in rows:
            parsed = parser.parse(raw_id=row["id"], raw_data=row["all_fields"] or {})
            _upsert_parsed(conn, source_type, parsed, prompt_version=prompt_version, h2_version=h2_version)
            parsed_count += 1
        conn.commit()
    return parsed_count


@dataclass(frozen=True)
class QueueItem:
    queue_id: int
    source_type: str
    raw_id: str
    h2_version: str
    prompt_version: str
    input_hash: str


def _acquire_queue_item(conn: psycopg.Connection, worker_id: str) -> QueueItem | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            WITH candidate AS (
                SELECT id
                FROM parsed.enrichment_queue
                WHERE (
                    (status = 'pending' AND next_retry_at <= NOW())
                    OR (status = 'running' AND locked_at < NOW() - INTERVAL '10 minutes')
                )
                ORDER BY priority ASC, next_retry_at ASC, id ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE parsed.enrichment_queue q
            SET status = 'running', locked_by = %s, locked_at = NOW(), updated_at = NOW()
            FROM candidate
            WHERE q.id = candidate.id
            RETURNING q.id, q.source_type, q.raw_id, q.h2_version, q.prompt_version, q.input_hash;
            """,
            (worker_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return QueueItem(
        queue_id=row["id"],
        source_type=row["source_type"],
        raw_id=row["raw_id"],
        h2_version=row["h2_version"],
        prompt_version=row["prompt_version"],
        input_hash=row["input_hash"],
    )


def _load_parsed_doc(conn: psycopg.Connection, source_type: str, raw_id: str) -> dict[str, Any] | None:
    table = _parsed_table(source_type)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT * FROM {table} WHERE raw_id = %s", (raw_id,))
        return cur.fetchone()


def _mark_queue_done(conn: psycopg.Connection, queue_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE parsed.enrichment_queue
            SET status = 'done', locked_by = NULL, locked_at = NULL, updated_at = NOW()
            WHERE id = %s
            """,
            (queue_id,),
        )


def _mark_queue_failed(conn: psycopg.Connection, queue_id: int, error: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE parsed.enrichment_queue
            SET
                status = CASE WHEN attempts + 1 >= 5 THEN 'failed' ELSE 'pending' END,
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


def _update_enrichment(
    conn: psycopg.Connection,
    source_type: str,
    raw_id: str,
    *,
    status: str,
    spans: list[dict[str, Any]],
    tags: list[str],
    tagged_xml: str,
    summary_short: str | None,
    summary_long: str | None,
    summary_structured: dict[str, Any] | None,
    legal_entities: list[dict[str, Any]] | None,
    topics: list[str] | None,
    chunk_summaries: list[dict[str, Any]] | None,
) -> None:
    table = _parsed_table(source_type)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {table}
            SET
                enrichment_status = %s,
                tag_spans = %s::jsonb,
                tags_flat = %s,
                body_tagged_xml = CASE
                    WHEN COALESCE(%s, '') <> '' THEN %s
                    ELSE body_tagged_xml
                END,
                summary_short = %s,
                summary_long = %s,
                summary_structured = %s::jsonb,
                legal_entities = %s::jsonb,
                topics = %s,
                chunk_summaries = %s::jsonb,
                enrichment_version = %s,
                updated_at = NOW()
            WHERE raw_id = %s
            """,
            (
                status,
                json.dumps(spans, ensure_ascii=False),
                tags,
                tagged_xml,
                tagged_xml,
                summary_short,
                summary_long,
                json.dumps(summary_structured, ensure_ascii=False) if summary_structured is not None else None,
                json.dumps(legal_entities, ensure_ascii=False) if legal_entities is not None else None,
                topics,
                json.dumps(chunk_summaries, ensure_ascii=False) if chunk_summaries is not None else None,
                ALLOWED_TAGS_VERSION,
                raw_id,
            ),
        )


def process_one_enrichment(worker_id: str, model: str) -> bool:
    with psycopg.connect(_pg_url()) as conn:
        item = _acquire_queue_item(conn, worker_id=worker_id)
        if item is None:
            conn.commit()
            return False
        parsed_doc = _load_parsed_doc(conn, source_type=item.source_type, raw_id=item.raw_id)
        if not parsed_doc:
            _mark_queue_failed(conn, item.queue_id, "parsed row missing")
            conn.commit()
            return True

        try:
            text = parsed_doc.get("body_tagged_xml") or ""
            allowed = tags_for_source(item.source_type)
            if not text or not allowed:
                _update_enrichment(
                    conn,
                    item.source_type,
                    item.raw_id,
                    status="skipped",
                    spans=[],
                    tags=[],
                    tagged_xml="",
                    summary_short=None,
                    summary_long=None,
                    summary_structured=None,
                    legal_entities=None,
                    topics=None,
                    chunk_summaries=None,
                )
                _mark_queue_done(conn, item.queue_id)
                conn.commit()
                return True

            prompt = build_h2_prompt(text=text, allowed_tags=allowed, source_type=item.source_type)
            out = call_local_llm(prompt=prompt, model=model)
            spans_model = parse_spans(out.get("tag_spans", []))
            validate_spans(text=text, spans=spans_model, allowed_tags=allowed)
            spans = [x.model_dump() for x in spans_model]
            tags = tags_flat(spans_model)
            tagged_xml = render_tagged_xml(text, spans_model)
            _update_enrichment(
                conn,
                item.source_type,
                item.raw_id,
                status="done",
                spans=spans,
                tags=tags,
                tagged_xml=tagged_xml,
                summary_short=out.get("summary_short"),
                summary_long=out.get("summary_long"),
                summary_structured=out.get("summary_structured"),
                legal_entities=out.get("legal_entities"),
                topics=out.get("topics"),
                chunk_summaries=out.get("chunk_summaries"),
            )
            _mark_queue_done(conn, item.queue_id)
            conn.commit()
            return True
        except Exception as exc:
            _mark_queue_failed(conn, item.queue_id, str(exc))
            table = _parsed_table(item.source_type)
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {table} SET enrichment_status = 'failed', updated_at = NOW() WHERE raw_id = %s",
                    (item.raw_id,),
                )
            conn.commit()
            return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Parsed pipeline (H1/H2) for source-separated raw tables")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_parse = sub.add_parser("parse", help="Run raw -> parsed upsert for one source")
    p_parse.add_argument("--source", choices=list(SOURCE_TYPES), required=True)
    p_parse.add_argument("--limit", type=int, default=1000)
    p_parse.add_argument("--offset", type=int, default=0)
    p_parse.add_argument("--prompt-version", default="1.0.0")
    p_parse.add_argument("--h2-version", default=ALLOWED_TAGS_VERSION)

    p_worker = sub.add_parser("h2-worker", help="Run H2 enrichment worker")
    p_worker.add_argument("--max-jobs", type=int, default=1)
    p_worker.add_argument("--worker-id", default=f"worker-{os.getpid()}")
    p_worker.add_argument("--model", default=os.getenv("H2_LLM_MODEL", "qwen3"))

    args = parser.parse_args()
    if args.cmd == "parse":
        count = run_parse(
            args.source,
            limit=args.limit,
            offset=args.offset,
            prompt_version=args.prompt_version,
            h2_version=args.h2_version,
        )
        print(json.dumps({"source": args.source, "parsed": count}, ensure_ascii=False))
        return

    processed = 0
    for _ in range(args.max_jobs):
        had = process_one_enrichment(worker_id=args.worker_id, model=args.model)
        if not had:
            break
        processed += 1
    print(json.dumps({"processed": processed, "worker_id": args.worker_id}, ensure_ascii=False))


if __name__ == "__main__":
    main()
