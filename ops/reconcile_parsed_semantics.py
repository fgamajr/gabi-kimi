from __future__ import annotations

import argparse
import json
import os

import psycopg
from psycopg.rows import dict_row

from src.backend.core.config import settings
from src.backend.parsing.h2_postprocess import (
    H2_ENRICHMENT_VERSION,
    build_summary_short,
    build_summary_structured,
    classify_enrichment_status,
    clean_text,
    derive_legal_entities,
    derive_topics,
    fallback_tags,
)
from src.backend.parsing.h2_semantic import parse_spans_tolerant, tags_flat
from src.backend.parsing.h2_vocab import ALLOWED_TAGS_VERSION, tags_for_source
from src.backend.parsing.source_parsers import SOURCE_TYPES


def _pg_url() -> str:
    return os.getenv("POSTGRES_URL", settings.POSTGRES_URL)


def _normalize_pub_date(value: str | None) -> str | None:
    if not value:
        return None
    return str(value).strip()[:10] or None


def _load_raw_pub_date(conn: psycopg.Connection, raw_id: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT all_fields->>'pub_date' FROM raw.dou_documents_raw WHERE id = %s", (raw_id,))
        row = cur.fetchone()
    if not row:
        return None
    return _normalize_pub_date(row[0])


def _coerce_topics(source_type: str, topics: list[str] | None, text: str, structured: dict[str, object]) -> list[str]:
    out = [str(x).strip() for x in topics or [] if str(x).strip() and str(x).strip() != source_type]
    if out:
        return out[:8]
    return derive_topics(source_type, text, structured)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile parsed semantic fields and statuses")
    parser.add_argument("--source", choices=list(SOURCE_TYPES))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    sources = (args.source,) if args.source else SOURCE_TYPES
    updated = 0
    with psycopg.connect(_pg_url()) as conn:
        for source_type in sources:
            where = ""
            params: list[object] = []
            if args.limit > 0:
                where = " ORDER BY updated_at DESC LIMIT %s"
                params.append(args.limit)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(f"SELECT * FROM parsed.{source_type}{where}", params)
                rows = cur.fetchall()
            for row in rows:
                raw_id = row["raw_id"]
                structured = row.get("structured_fields") or {}
                body = row.get("body_tagged_xml") or ""
                text = clean_text(body)
                allowed = tags_for_source(source_type)
                spans_model, _ = parse_spans_tolerant(row.get("tag_spans") or [])
                span_tags = tags_flat(spans_model)
                tags = span_tags or fallback_tags(allowed, row.get("section_map") or {})
                topics = _coerce_topics(source_type, row.get("topics"), text, structured)
                legal_entities = row.get("legal_entities") or derive_legal_entities(text, structured)
                summary_structured = row.get("summary_structured")
                if not isinstance(summary_structured, dict) or summary_structured.get("modo") == "preview_fallback":
                    summary_structured = build_summary_structured(source_type, text, structured, topics, legal_entities)
                summary_short = clean_text(row.get("summary_short") or "")
                if not summary_short:
                    summary_short = build_summary_short(source_type, text, structured, topics)

                used_fallback = False
                if isinstance(row.get("summary_structured"), dict):
                    used_fallback = str(row["summary_structured"].get("mode") or row["summary_structured"].get("modo") or "").startswith(
                        "fallback"
                    ) or str(row["summary_structured"].get("modo") or "") == "preview_fallback"
                status = classify_enrichment_status(
                    source_type,
                    used_fallback=used_fallback,
                    spans_count=len(spans_model),
                    tags_count=len(tags),
                    summary_short=summary_short,
                    summary_structured=summary_structured,
                    topics=topics,
                    legal_entities=legal_entities,
                )

                pub_date = row.get("pub_date")
                if source_type == "dou_documents" and pub_date is None:
                    pub_date = _normalize_pub_date(
                        structured.get("pub_date") or structured.get("data_publicacao") or structured.get("data_dou")
                    )
                    if pub_date is None:
                        pub_date = _load_raw_pub_date(conn, raw_id)

                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        UPDATE parsed.{source_type}
                        SET
                            pub_date = COALESCE(%s, pub_date),
                            enrichment_status = %s,
                            enrichment_version = %s,
                            h2_version = %s,
                            tags_flat = %s,
                            summary_short = %s,
                            summary_structured = %s::jsonb,
                            legal_entities = %s::jsonb,
                            topics = %s,
                            updated_at = NOW()
                        WHERE raw_id = %s
                        """,
                        (
                            pub_date,
                            status,
                            H2_ENRICHMENT_VERSION,
                            ALLOWED_TAGS_VERSION,
                            tags,
                            summary_short,
                            json.dumps(summary_structured, ensure_ascii=False),
                            json.dumps(legal_entities, ensure_ascii=False),
                            topics,
                            raw_id,
                        ),
                    )
                updated += 1
        conn.commit()
    print(json.dumps({"updated": updated, "sources": list(sources)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
