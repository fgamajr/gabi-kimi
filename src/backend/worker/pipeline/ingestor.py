"""Ingestor pipeline module — parses XML and bulk-indexes to Elasticsearch.

Reuses INLabsXMLParser from existing codebase. Indexes directly to ES
without PostgreSQL dependency. Uses httpx for async bulk requests.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from src.backend.ingest.normalizer import (
    _compute_natural_key_hash,
    normalize_pub_date,
    normalize_section,
    strip_html,
)
from src.backend.ingest.xml_parser import INLabsXMLParser, DOUArticle
from src.backend.worker.registry import FileStatus, Registry

logger = logging.getLogger(__name__)

BULK_BATCH_SIZE = 300
ES_INDEX = "gabi_documents_v1"
DEFAULT_EXTRACT_DIR = "/data/tmp/extract"


def _compute_doc_id(article: DOUArticle) -> str:
    """Compute deterministic document ID from natural key hash.

    Uses SHA-256 of pub_date + section + name + id_materia.
    """
    natural_key_hash, _ = _compute_natural_key_hash(article)
    return natural_key_hash


def _article_to_es_doc(article: DOUArticle, source_zip: str) -> dict[str, Any]:
    """Convert parsed DOUArticle to ES document body."""
    pub_date = normalize_pub_date(article.pub_date)
    pub_date_iso = pub_date.isoformat() if pub_date else None

    natural_key_hash, _ = _compute_natural_key_hash(article)

    return {
        "pub_date": pub_date_iso,
        "section": article.pub_name,
        "title": article.name,
        "body": strip_html(article.texto),
        "act_type": article.art_type,
        "act_number": article.edition_number,
        "orgao": "/".join(article.organization_path) if article.organization_path else "",
        "signatario": "",
        "dou_page": article.number_page,
        "source_zip": source_zip,
        "natural_key_hash": natural_key_hash,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
    }


async def _bulk_index(
    client: httpx.AsyncClient,
    es_url: str,
    docs: list[tuple[str, dict[str, Any]]],
) -> tuple[int, int]:
    """Send a bulk index request to ES.

    Args:
        client: httpx async client
        es_url: ES base URL
        docs: list of (doc_id, doc_body) tuples

    Returns:
        (ok_count, failed_count)
    """
    lines: list[str] = []
    for doc_id, body in docs:
        action = {"index": {"_index": ES_INDEX, "_id": doc_id}}
        lines.append(json.dumps(action, ensure_ascii=False))
        lines.append(json.dumps(body, ensure_ascii=False))

    payload = "\n".join(lines) + "\n"

    resp = await client.post(
        f"{es_url}/_bulk",
        content=payload.encode("utf-8"),
        headers={"Content-Type": "application/x-ndjson"},
    )
    resp.raise_for_status()
    result = resp.json()

    ok = 0
    failed = 0
    for item in result.get("items", []):
        row = item.get("index", {})
        status = row.get("status", 500)
        if 200 <= status < 300:
            ok += 1
        else:
            failed += 1

    return ok, failed


async def run_ingest(
    registry: Registry,
    run_id: str,
    es_url: str,
    extract_dir: str = DEFAULT_EXTRACT_DIR,
) -> dict[str, Any]:
    """Parse extracted XMLs and bulk-index to Elasticsearch.

    Args:
        registry: SQLite registry instance
        run_id: Pipeline run identifier for logging
        es_url: Elasticsearch base URL
        extract_dir: Base directory containing extracted XML subdirectories

    Returns:
        Stats dict: {"ingested_files": N, "ingested_docs": M, "failed_files": K}
    """
    extract_base = Path(extract_dir)
    extracted_files = await registry.get_files_by_status(FileStatus.EXTRACTED)
    parser = INLabsXMLParser()

    ingested_files = 0
    ingested_docs = 0
    failed_files = 0

    async with httpx.AsyncClient(timeout=60) as client:
        for file_rec in extracted_files:
            file_id = file_rec["id"]
            filename = file_rec["filename"]
            stem = Path(filename).stem
            file_extract_dir = extract_base / stem

            # Transition to INGESTING
            await registry.update_status(file_id, FileStatus.INGESTING)

            try:
                if not file_extract_dir.exists():
                    raise FileNotFoundError(f"Extract dir not found: {file_extract_dir}")

                xml_files = sorted(file_extract_dir.glob("*.xml"))
                if not xml_files:
                    raise ValueError(f"No XML files found in {file_extract_dir}")

                # Parse all XMLs and build bulk docs
                bulk_docs: list[tuple[str, dict[str, Any]]] = []
                parse_errors = 0

                for xml_path in xml_files:
                    try:
                        article = parser.parse_file(xml_path)
                        doc_id = _compute_doc_id(article)
                        es_doc = _article_to_es_doc(article, source_zip=filename)
                        bulk_docs.append((doc_id, es_doc))
                    except Exception as e:
                        parse_errors += 1
                        logger.warning("Parse error in %s/%s: %s", filename, xml_path.name, e)

                if not bulk_docs:
                    raise ValueError(f"All {len(xml_files)} XMLs failed to parse")

                # Bulk index in batches
                total_ok = 0
                total_failed = 0

                for i in range(0, len(bulk_docs), BULK_BATCH_SIZE):
                    batch = bulk_docs[i:i + BULK_BATCH_SIZE]
                    ok, fail = await _bulk_index(client, es_url, batch)
                    total_ok += ok
                    total_failed += fail

                # Update registry
                await registry.update_file_fields(file_id, doc_count=total_ok)
                await registry.update_status(file_id, FileStatus.INGESTED)
                await registry.add_log_entry(
                    run_id, file_id, "INFO",
                    f"Ingested {total_ok} docs from {filename} (parse_errors={parse_errors})"
                )
                ingested_files += 1
                ingested_docs += total_ok

            except Exception as e:
                error_msg = str(e)
                logger.error("Ingest failed for %s: %s", filename, error_msg)
                await registry.update_status(file_id, FileStatus.INGEST_FAILED)
                await registry.update_file_fields(file_id, error_message=error_msg)
                await registry.add_log_entry(
                    run_id, file_id, "ERROR",
                    f"Ingest failed for {filename}: {error_msg}"
                )
                failed_files += 1

    return {
        "ingested_files": ingested_files,
        "ingested_docs": ingested_docs,
        "failed_files": failed_files,
    }
