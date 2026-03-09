"""Embedding pipeline stage for worker-indexed DOU documents."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

import httpx

from src.backend.ingest.embedding_pipeline import _create_embedder, _load_embed_config
from src.backend.worker.registry import FileStatus, Registry

logger = logging.getLogger(__name__)

ES_INDEX = "gabi_documents_v1"
SEARCH_BATCH_SIZE = 200
EMBED_BATCH_SIZE = 100


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_embed_config():
    cfg = _load_embed_config()
    if "EMBED_DIM" not in os.environ and cfg.provider not in {"hash", "fake", "dev"}:
        cfg = replace(cfg, dim=1536)
    return cfg


def _build_embedding_text(source: dict[str, Any]) -> str:
    title = source.get("title") or source.get("identifica") or source.get("ementa") or ""
    body = source.get("body") or source.get("body_plain") or ""
    return f"{title}\n\n{body[:6000]}".strip()


async def _ensure_embedding_mapping(client: httpx.AsyncClient, es_url: str, dims: int) -> None:
    resp = await client.put(
        f"{es_url}/{ES_INDEX}/_mapping",
        json={
            "properties": {
                "embedding": {
                    "type": "dense_vector",
                    "dims": dims,
                    "index": True,
                    "similarity": "cosine",
                },
                "embedded_at": {"type": "date"},
            }
        },
    )
    resp.raise_for_status()


async def _fetch_file_documents(
    client: httpx.AsyncClient,
    es_url: str,
    filename: str,
) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    search_after: list[Any] | None = None

    while True:
        payload: dict[str, Any] = {
            "size": SEARCH_BATCH_SIZE,
            "sort": [{"_id": "asc"}],
            "_source": ["title", "body", "identifica", "ementa", "body_plain", "source_zip"],
            "query": {
                "bool": {
                    "should": [
                        {"term": {"source_zip.keyword": filename}},
                        {"term": {"source_zip": filename}},
                    ],
                    "minimum_should_match": 1,
                }
            },
        }
        if search_after:
            payload["search_after"] = search_after

        resp = await client.post(f"{es_url}/{ES_INDEX}/_search", json=payload)
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
        if not hits:
            break

        docs.extend(hits)
        search_after = hits[-1].get("sort")
        if len(hits) < SEARCH_BATCH_SIZE:
            break

    return docs


async def _bulk_update_embeddings(
    client: httpx.AsyncClient,
    es_url: str,
    updates: list[tuple[str, list[float], str]],
) -> tuple[int, int]:
    lines: list[str] = []
    for doc_id, embedding, embedded_at in updates:
        lines.append(json.dumps({"update": {"_index": ES_INDEX, "_id": doc_id}}, ensure_ascii=False))
        lines.append(
            json.dumps(
                {"doc": {"embedding": embedding, "embedded_at": embedded_at}},
                ensure_ascii=False,
            )
        )

    resp = await client.post(
        f"{es_url}/_bulk",
        content=("\n".join(lines) + "\n").encode("utf-8"),
        headers={"Content-Type": "application/x-ndjson"},
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    ok = 0
    failed = 0
    for item in items:
        row = item.get("update", {})
        status = int(row.get("status", 500))
        if 200 <= status < 300:
            ok += 1
        else:
            failed += 1
    return ok, failed


async def run_embed(
    registry: Registry,
    run_id: str,
    es_url: str,
) -> dict[str, Any]:
    """Fetch BM25-indexed docs from ES, generate embeddings, and update them in-place."""
    files = list(await registry.get_files_by_status(FileStatus.BM25_INDEXED))
    verified_backfill = [
        file_rec
        for file_rec in await registry.get_files_by_status(FileStatus.VERIFIED, limit=5000)
        if not file_rec.get("embedded_at")
    ]
    files.extend(verified_backfill)
    if not files:
        return {"embedded_files": 0, "embedded_docs": 0, "failed_files": 0}

    cfg = _resolve_embed_config()
    embedder = _create_embedder(cfg)
    embedded_files = 0
    embedded_docs = 0
    failed_files = 0

    async with httpx.AsyncClient(timeout=60) as client:
        await _ensure_embedding_mapping(client, es_url, cfg.dim)

        for file_rec in files:
            file_id = file_rec["id"]
            filename = file_rec["filename"]

            await registry.update_status(file_id, FileStatus.EMBEDDING)

            try:
                hits = await _fetch_file_documents(client, es_url, filename)
                if not hits:
                    raise ValueError(f"No BM25-indexed documents found in ES for {filename}")

                total_ok = 0
                total_failed = 0

                for start in range(0, len(hits), EMBED_BATCH_SIZE):
                    batch_hits = hits[start:start + EMBED_BATCH_SIZE]
                    texts = [_build_embedding_text(hit.get("_source", {})) for hit in batch_hits]
                    vectors = await asyncio.to_thread(embedder.embed_batch, texts)
                    if len(vectors) != len(batch_hits):
                        raise RuntimeError("Embedding provider returned wrong number of vectors")

                    embedded_at = _utcnow()
                    updates = [
                        (str(hit.get("_id")), vector, embedded_at)
                        for hit, vector in zip(batch_hits, vectors, strict=True)
                    ]
                    ok, failed = await _bulk_update_embeddings(client, es_url, updates)
                    total_ok += ok
                    total_failed += failed

                if total_failed:
                    raise RuntimeError(f"Embedding bulk update failed for {total_failed} docs")

                await registry.update_status(file_id, FileStatus.EMBEDDED)
                await registry.add_log_entry(
                    run_id,
                    file_id,
                    "INFO",
                    f"Embedded {total_ok} docs for {filename}",
                )
                embedded_files += 1
                embedded_docs += total_ok
            except Exception as exc:
                error_msg = str(exc)
                logger.error("Embedding failed for %s: %s", filename, error_msg)
                await registry.update_status(file_id, FileStatus.EMBEDDING_FAILED)
                await registry.update_file_fields(file_id, error_message=error_msg)
                await registry.add_log_entry(
                    run_id,
                    file_id,
                    "ERROR",
                    f"Embedding failed for {filename}: {error_msg}",
                )
                failed_files += 1

    return {
        "embedded_files": embedded_files,
        "embedded_docs": embedded_docs,
        "failed_files": failed_files,
    }
