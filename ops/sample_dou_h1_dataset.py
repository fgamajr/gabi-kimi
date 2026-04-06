from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from src.backend.core.config import settings


def _pg_url() -> str:
    return os.getenv("POSTGRES_URL", settings.POSTGRES_URL)


def build_sampling_sql(sample_size: int) -> str:
    return f"""
WITH base AS (
    SELECT
        id,
        all_fields,
        COALESCE(NULLIF(all_fields->>'section_normalized', ''), NULLIF(all_fields->>'section', ''), 'unknown') AS section_bucket,
        COALESCE(NULLIF(all_fields->>'art_type_normalized', ''), NULLIF(all_fields->>'art_type', ''), 'unknown') AS art_type_bucket,
        COALESCE(NULLIF(all_fields->>'issuing_organ', ''), NULLIF(all_fields->>'orgao', ''), 'unknown') AS orgao_bucket,
        COALESCE(SUBSTRING(all_fields->>'pub_date' FROM 1 FOR 4), 'unknown') AS year_bucket
    FROM raw.dou_documents_raw
),
strata AS (
    SELECT
        section_bucket,
        art_type_bucket,
        orgao_bucket,
        year_bucket,
        COUNT(*)::bigint AS cnt
    FROM base
    GROUP BY 1,2,3,4
),
alloc AS (
    SELECT
        section_bucket,
        art_type_bucket,
        orgao_bucket,
        year_bucket,
        GREATEST(
            1,
            ROUND(({sample_size}::numeric * cnt::numeric) / (SELECT SUM(cnt) FROM strata))
        )::int AS n
    FROM strata
),
ranked AS (
    SELECT
        b.*,
        ROW_NUMBER() OVER (
            PARTITION BY b.section_bucket, b.art_type_bucket, b.orgao_bucket, b.year_bucket
            ORDER BY md5(b.id)
        ) AS rn
    FROM base b
)
SELECT
    r.id,
    r.section_bucket,
    r.art_type_bucket,
    r.orgao_bucket,
    r.year_bucket,
    r.all_fields
FROM ranked r
JOIN alloc a
  ON a.section_bucket = r.section_bucket
 AND a.art_type_bucket = r.art_type_bucket
 AND a.orgao_bucket = r.orgao_bucket
 AND a.year_bucket = r.year_bucket
WHERE r.rn <= a.n
LIMIT {sample_size};
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build stratified DOU sample for H1 calibration")
    parser.add_argument("--postgres-url", default=_pg_url())
    parser.add_argument("--sample-size", type=int, default=10_000)
    parser.add_argument("--output", default="ops/data/dou_h1_sample_10000.jsonl")
    args = parser.parse_args()

    sql = build_sampling_sql(sample_size=args.sample_size)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with psycopg.connect(args.postgres_url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql)
            with out_path.open("w", encoding="utf-8") as out:
                for row in cur:
                    fields = row["all_fields"] or {}
                    payload = {
                        "raw_id": row["id"],
                        "strata": {
                            "section": row["section_bucket"],
                            "art_type": row["art_type_bucket"],
                            "orgao": row["orgao_bucket"],
                            "year": row["year_bucket"],
                        },
                        "raw_text": fields.get("texto") or fields.get("content_html") or "",
                        "raw_fields": fields,
                    }
                    out.write(json.dumps(payload, ensure_ascii=False) + "\n")
                    count += 1
    print(json.dumps({"output": str(out_path), "count": count}, ensure_ascii=False))


if __name__ == "__main__":
    main()
