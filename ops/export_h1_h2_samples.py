from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


SOURCES = (
    "dou_documents",
    "tcu_acordao_completo",
    "tcu_jurisprudencia_selecionada",
    "tcu_resposta_consulta",
    "tcu_sumula",
    "tcu_boletim_jurisprudencia",
    "tcu_boletim_pessoal",
    "tcu_boletim_informativo_lc",
    "tcu_normas",
    "tcu_btcu",
    "tcu_publicacoes",
)


def _pg_url() -> str:
    return os.getenv("POSTGRES_URL", "postgresql://gabi:gabi@postgres:5432/gabi")


def _json_default(value: object) -> str:
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export 10-sample snapshots for H1/H2 inspection")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--out-dir", default="ops/data")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    h1_file = out_dir / f"h1_dou_sample_{args.limit}.jsonl"
    h2_file = out_dir / f"h2_all_sources_sample_{args.limit}.json"

    with psycopg.connect(_pg_url()) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    raw_id,
                    source_type,
                    h1_tipo,
                    h1_subtipo,
                    h1_confidence,
                    h1_method,
                    h1_version,
                    h1_status,
                    art_type,
                    orgao_emissor,
                    pub_date,
                    parser_version,
                    content_hash,
                    structured_fields,
                    section_map,
                    body_tagged_xml,
                    updated_at
                FROM parsed.dou_documents
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (args.limit,),
            )
            h1_rows = cur.fetchall()

        with h1_file.open("w", encoding="utf-8") as f:
            for row in h1_rows:
                payload = dict(row)
                if payload.get("updated_at") is not None:
                    payload["updated_at"] = str(payload["updated_at"])
                if payload.get("pub_date") is not None:
                    payload["pub_date"] = str(payload["pub_date"])
                f.write(json.dumps(payload, ensure_ascii=False, default=_json_default) + "\n")

        h2_payload: dict[str, list[dict[str, object]]] = {}
        with conn.cursor(row_factory=dict_row) as cur:
            for source in SOURCES:
                table = f"parsed.{source}"
                cur.execute(
                    f"""
                    SELECT
                        raw_id,
                        source_type,
                        enrichment_status,
                        enrichment_version,
                        h2_version,
                        prompt_version,
                        tag_spans,
                        tags_flat,
                        summary_short,
                        summary_long,
                        summary_structured,
                        legal_entities,
                        topics,
                        chunk_summaries,
                        updated_at
                    FROM {table}
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    (args.limit,),
                )
                rows = [dict(x) for x in cur.fetchall()]
                for item in rows:
                    if item.get("updated_at") is not None:
                        item["updated_at"] = str(item["updated_at"])
                h2_payload[source] = rows

        h2_file.write_text(
            json.dumps(h2_payload, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "h1_file": str(h1_file),
                "h1_count": len(h1_rows),
                "h2_file": str(h2_file),
                "sources": len(SOURCES),
                "per_source_limit": args.limit,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
