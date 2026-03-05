#!/usr/bin/env python3
"""Targeted reprocessing of 2002 DOU records affected by Bug 1 (index docs) and Bug 2 (blob docs).

Workflow:
  1. Query PostgreSQL for affected 2002 records
  2. Delete them (CASCADE handles signatures, refs, media)
  3. Re-ingest source ZIPs for 2002 months (with bug fixes applied)
  4. Delete old doc IDs from Elasticsearch, index replacements

Usage:
  python -m scripts.reprocess_2002 --dry-run          # show affected records
  python -m scripts.reprocess_2002                     # reprocess + resync ES
  python -m scripts.reprocess_2002 --skip-es           # reprocess PG only
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import psycopg2

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.dou_ingest import DOUIngestor, _log
from ingest.es_indexer import ESClient


def _build_dsn() -> str:
    if os.getenv("PG_DSN"):
        return os.environ["PG_DSN"]
    return os.environ.get(
        "GABI_DSN",
        f"host={os.getenv('PGHOST', os.getenv('GABI_POSTGRES_HOST', 'localhost'))} "
        f"port={os.getenv('PGPORT', os.getenv('GABI_POSTGRES_PORT', '5433'))} "
        f"dbname={os.getenv('PGDATABASE', os.getenv('GABI_POSTGRES_DB', 'gabi'))} "
        f"user={os.getenv('PGUSER', os.getenv('GABI_POSTGRES_USER', 'gabi'))} "
        f"password={os.getenv('PGPASSWORD', os.getenv('GABI_POSTGRES_PASSWORD', 'gabi'))}"
    )


AFFECTED_QUERY = """
SELECT d.id::text, d.id_materia, d.art_type_raw, char_length(d.body_plain) AS body_len
FROM dou.document d
JOIN dou.edition e ON e.id = d.edition_id
WHERE e.publication_date BETWEEN '2002-01-01' AND '2002-12-31'
  AND (
    d.art_type_raw IN ('MINISTÉRIO', 'Índice de Normas')
    OR char_length(d.body_plain) > 20000
  )
ORDER BY e.publication_date, d.id_materia
"""

# Bug 3: page fragments — query for ALL 2002 records (fragments + parents)
ALL_2002_QUERY = """
SELECT d.id::text, d.id_materia, d.art_type_raw, char_length(d.body_plain) AS body_len
FROM dou.document d
JOIN dou.edition e ON e.id = d.edition_id
WHERE e.publication_date BETWEEN '2002-01-01' AND '2002-12-31'
ORDER BY e.publication_date, d.id_materia
"""

FRAGMENT_COUNT_QUERY = """
SELECT count(*) AS cnt
FROM dou.document d
JOIN dou.edition e ON e.id = d.edition_id
WHERE e.publication_date BETWEEN '2002-01-01' AND '2002-12-31'
  AND (
    d.identifica ~ '^[a-záàâãéêíóôõúüç]'
    OR d.art_type_raw ~ '^[_\\-]{2,}'
    OR length(trim(d.art_type_raw)) <= 1
    OR d.art_type_raw ~ '^\\('
    OR d.art_type_raw ~ '^\\d'
    OR d.art_type_raw ~ '^\\*'
    OR (d.identifica ~ '\\w-$' AND d.art_type_raw NOT IN (
      'PORTARIA', 'DECRETO', 'RESOLUÇÃO', 'EXTRATO', 'AVISO', 'ATO', 'EDITAL',
      'RETIFICAÇÃO', 'DESPACHO', 'DESPACHOS', 'PORTARIAS', 'EXTRATOS', 'AVISOS',
      'RESULTADO', 'RESULTADOS', 'PREGÃO', 'TOMADA', 'CONCORRÊNCIA', 'CONVITE',
      'ATA', 'ATOS', 'EDITAIS', 'COMUNICADO', 'CIRCULAR', 'LEI', 'DECRETOS',
      'ANEXO', 'INSTRUÇÃO', 'INSTRUÇÃO NORMATIVA', 'DELIBERAÇÃO', 'DECISÃO',
      'DECISÕES', 'ACÓRDÃO', 'ACÓRDÃOS', 'SÚMULA', 'PARECER', 'PARECERES',
      'MEDIDA', 'RESOLUÇÃO-RE', 'RESOLUÇÃO-RDC', 'RESOLUÇÕES',
      'RETIFICAÇÕES', 'CONCORRÊNCIAS', 'CARTA-CONVITE', 'CARTA-CIRCULAR',
      'LEILÃO', 'DISPENSA', 'INEXIGIBILIDADE', 'SOLUÇÃO', 'SOLUÇÕES',
      'PAUTA', 'RELATÓRIO', 'AUTORIZAÇÃO', 'ADITAMENTO', 'PROPOSTA',
      'CONVÊNIO', 'PROTOCOLO', 'CONTRATO', 'DECLARAÇÃO', 'APOSENTADORIA',
      'PENSÃO', 'DEMONSTRATIVO', 'DEMONSTRAÇÃO', 'BALANÇO', 'BALANCETE',
      'CONSULTA', 'EMENTÁRIO', 'PROCESSO', 'TOMADAS', 'JUSTIFICATIVA',
      'PRESTAÇÃO', 'NOTA', 'NOTAS', 'RESUMO', 'JULGAMENTO', 'SESSÃO',
      'ALTERAÇÃO', 'ORDEM', 'QUADRO', 'ARTIGO', 'SEÇÃO', 'CAPÍTULO',
      'CONJUNTO', 'RELAÇÃO', 'PROGRAMA', 'TERMO'
    ))
  )
"""

# Find source ZIPs that contributed 2002 documents
SOURCE_ZIPS_QUERY = """
SELECT DISTINCT sz.id::text, sz.filename
FROM dou.source_zip sz
JOIN dou.edition e ON e.source_zip_id = sz.id
WHERE e.publication_date BETWEEN '2002-01-01' AND '2002-12-31'
ORDER BY sz.filename
"""


def find_affected(conn) -> list[dict]:
    cur = conn.cursor()
    cur.execute(AFFECTED_QUERY)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.close()
    return rows


def find_source_zips(conn) -> list[dict]:
    cur = conn.cursor()
    cur.execute(SOURCE_ZIPS_QUERY)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.close()
    return rows


def delete_affected(conn, doc_ids: list[str]) -> int:
    """Delete affected documents by ID. CASCADE handles child tables."""
    if not doc_ids:
        return 0
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM dou.document WHERE id = ANY(%s::uuid[])",
        (doc_ids,),
    )
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    return deleted


def resync_es(old_ids: list[str], dsn: str) -> tuple[int, int]:
    """Delete old IDs from ES, then sync new docs from PG."""
    es = ESClient()

    # Delete old docs from ES
    deleted = 0
    if old_ids:
        batch_size = 500
        for i in range(0, len(old_ids), batch_size):
            batch = old_ids[i:i + batch_size]
            body = {"query": {"ids": {"values": batch}}}
            try:
                resp = es.request("POST", f"/{es.index}/_delete_by_query", body)
                deleted += resp.get("deleted", 0)
            except Exception as ex:
                _log(f"  ES delete batch error: {ex}")

    # Re-index all 2002 docs from PG
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("""
        SELECT
            d.id::text AS doc_id,
            d.id_materia,
            d.identifica,
            d.ementa,
            d.titulo,
            d.sub_titulo,
            d.body_plain,
            d.art_type,
            d.issuing_organ,
            e.section AS edition_section,
            e.publication_date::text AS pub_date,
            d.document_number,
            d.document_year,
            d.page_number,
            e.is_extra,
            to_char(d.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS created_at
        FROM dou.document d
        JOIN dou.edition e ON e.id = d.edition_id
        WHERE e.publication_date BETWEEN '2002-01-01' AND '2002-12-31'
        ORDER BY d.created_at, d.id
    """)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.close()
    conn.close()

    indexed = 0
    if rows:
        batch_size = 2000
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            ok, failed = es.bulk(batch)
            indexed += ok
            _log(f"  ES indexed batch {i // batch_size + 1}: ok={ok} failed={failed}")

    return deleted, indexed


def find_all_2002(conn) -> list[dict]:
    """Find all 2002 records (for full reprocessing)."""
    cur = conn.cursor()
    cur.execute(ALL_2002_QUERY)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.close()
    return rows


def count_fragments(conn) -> int:
    """Count page-fragment documents in 2002."""
    cur = conn.cursor()
    cur.execute(FRAGMENT_COUNT_QUERY)
    cnt = cur.fetchone()[0]
    cur.close()
    return cnt


def main() -> int:
    p = argparse.ArgumentParser(description="Reprocess affected 2002 DOU records")
    p.add_argument("--dry-run", action="store_true", help="Show affected records without modifying anything")
    p.add_argument("--skip-es", action="store_true", help="Skip Elasticsearch resync")
    p.add_argument("--fragments", action="store_true",
                   help="Bug 3: delete ALL 2002 records and re-ingest to merge page fragments")
    p.add_argument("--data-dir", type=Path, default=Path("data/inlabs/zips"),
                   help="Directory containing source ZIP files for re-ingestion")
    p.add_argument("--dsn", default=_build_dsn(), help="PostgreSQL DSN")
    args = p.parse_args()

    conn = psycopg2.connect(args.dsn)
    conn.autocommit = True

    if args.fragments:
        return _run_fragments(conn, args)
    else:
        return _run_bugs_1_2(conn, args)


def _run_fragments(conn, args) -> int:
    """Bug 3: full 2002 reprocessing to merge page fragments."""
    _log("Counting page fragments in 2002 data...")
    frag_count = count_fragments(conn)
    _log(f"Found {frag_count} page-fragment documents")

    _log("Querying all 2002 records...")
    all_docs = find_all_2002(conn)
    _log(f"Total 2002 records: {len(all_docs)}")

    if args.dry_run:
        _log(f"\nWould delete {len(all_docs)} records and re-ingest from ZIPs.")
        _log(f"Expected reduction: ~{frag_count} fragments merged into parents.")
        conn.close()
        return 0

    if not all_docs:
        _log("No 2002 records found. Nothing to do.")
        conn.close()
        return 0

    old_ids = [r["id"] for r in all_docs]

    # Delete all 2002 records
    _log(f"Deleting {len(old_ids)} records from PostgreSQL...")
    batch_size = 5000
    total_deleted = 0
    for i in range(0, len(old_ids), batch_size):
        batch = old_ids[i:i + batch_size]
        total_deleted += delete_affected(conn, batch)
        _log(f"  Deleted batch {i // batch_size + 1}: {total_deleted} total")
    _log(f"  Deleted {total_deleted} rows (CASCADE cleaned child tables)")

    # Re-ingest source ZIPs
    source_zips = find_source_zips(conn)
    conn.close()

    _log(f"Found {len(source_zips)} source ZIPs for 2002")

    zip_paths: list[Path] = []
    for sz in source_zips:
        candidate = args.data_dir / sz["filename"]
        if candidate.exists():
            zip_paths.append(candidate)
        else:
            _log(f"  WARNING: ZIP not found on disk: {candidate}")

    if zip_paths:
        _log(f"Re-ingesting {len(zip_paths)} ZIPs (with fragment merging)...")
        ingestor = DOUIngestor(args.dsn)
        result = ingestor.ingest_batch(zip_paths)
        _log(f"  Re-ingest: docs={result.total_documents} "
             f"media={result.total_media} sigs={result.total_signatures} "
             f"errors={len(result.errors)}")
    else:
        _log("No source ZIPs found on disk. Skipping re-ingestion.")

    # Resync ES
    if not args.skip_es:
        _log("Resyncing Elasticsearch...")
        try:
            es_deleted, es_indexed = resync_es(old_ids, args.dsn)
            _log(f"  ES: deleted={es_deleted} indexed={es_indexed}")
        except Exception as ex:
            _log(f"  ES resync failed: {ex}")
            _log("  Run 'python -m ingest.es_indexer sync' manually to fix.")
    else:
        _log("Skipping ES resync (--skip-es)")

    _log("Done.")
    return 0


def _run_bugs_1_2(conn, args) -> int:
    """Original Bug 1 + Bug 2 reprocessing."""
    _log("Querying affected 2002 records...")
    affected = find_affected(conn)
    index_docs = [r for r in affected if r["art_type_raw"] in ("MINISTÉRIO", "Índice de Normas")]
    blob_docs = [r for r in affected if r["body_len"] and r["body_len"] > 20000]

    _log(f"Found {len(affected)} affected records:")
    _log(f"  Index docs (Bug 1): {len(index_docs)}")
    _log(f"  Blob docs (Bug 2):  {len(blob_docs)}")

    if args.dry_run:
        _log("\n--- Index documents ---")
        for r in index_docs[:20]:
            _log(f"  {r['id_materia']:>20s}  art_type_raw={r['art_type_raw']}")
        if len(index_docs) > 20:
            _log(f"  ... and {len(index_docs) - 20} more")
        _log("\n--- Blob documents ---")
        for r in blob_docs[:20]:
            _log(f"  {r['id_materia']:>20s}  body_len={r['body_len']}")
        if len(blob_docs) > 20:
            _log(f"  ... and {len(blob_docs) - 20} more")
        conn.close()
        return 0

    if not affected:
        _log("No affected records found. Nothing to do.")
        conn.close()
        return 0

    old_ids = [r["id"] for r in affected]

    # Step 2: Delete affected records from PG
    _log(f"Deleting {len(old_ids)} affected records from PostgreSQL...")
    deleted = delete_affected(conn, old_ids)
    _log(f"  Deleted {deleted} rows (CASCADE cleaned child tables)")

    # Step 3: Find and re-ingest source ZIPs
    source_zips = find_source_zips(conn)
    conn.close()

    _log(f"Found {len(source_zips)} source ZIPs for 2002")

    # Look for ZIP files on disk
    zip_paths: list[Path] = []
    for sz in source_zips:
        candidate = args.data_dir / sz["filename"]
        if candidate.exists():
            zip_paths.append(candidate)
        else:
            _log(f"  WARNING: ZIP not found on disk: {candidate}")

    if zip_paths:
        _log(f"Re-ingesting {len(zip_paths)} ZIPs...")
        ingestor = DOUIngestor(args.dsn)
        result = ingestor.ingest_batch(zip_paths)
        _log(f"  Re-ingest: docs={result.total_documents} "
             f"media={result.total_media} sigs={result.total_signatures} "
             f"errors={len(result.errors)}")
    else:
        _log("No source ZIPs found on disk. Skipping re-ingestion.")
        _log("(Affected records were deleted. Re-run ingest manually if needed.)")

    # Step 4: Resync Elasticsearch
    if not args.skip_es:
        _log("Resyncing Elasticsearch...")
        try:
            es_deleted, es_indexed = resync_es(old_ids, args.dsn)
            _log(f"  ES: deleted={es_deleted} indexed={es_indexed}")
        except Exception as ex:
            _log(f"  ES resync failed: {ex}")
            _log("  Run 'python -m ingest.es_indexer sync' manually to fix.")
    else:
        _log("Skipping ES resync (--skip-es)")

    _log("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
