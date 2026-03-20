"""TCU embedding pipeline — OpenAI text-embedding-3-small → ES + Mongo.

Generates 384-dim embeddings for TCU acórdãos using the OpenAI API.
Reads from Mongo tcu_acordaos, writes vectors to ES gabi_tcu_acordaos_v1.

Usage:
  python -m src.backend.ingest.tcu_embed backfill   # Init all pending + embed
  python -m src.backend.ingest.tcu_embed sync        # Embed only pending docs
  python -m src.backend.ingest.tcu_embed stats       # Show progress
  python -m src.backend.ingest.tcu_embed reset-failed # Reset failed → pending
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import pymongo

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_MODEL = "text-embedding-3-small"
_DIMS = 384
_CHAR_LIMIT = 2000          # Max chars per doc for embedding (~500 tokens)
_BATCH_SIZE = 500            # Docs fetched from Mongo per loop
_API_BATCH_SIZE = 2048       # Max texts per OpenAI API call
_MAX_ATTEMPTS = 3
_MONGO_COLLECTION = "tcu_acordaos"
_ES_INDEX = "gabi_tcu_acordaos_v1"


def _log(msg: str) -> None:
    print(f"[tcu-embed] {msg}", flush=True)


def _openai_key() -> str:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set")
    return key


def _mongo_client():
    uri = os.getenv("MONGO_STRING", "mongodb://mongo:27017/gabi_dou")
    db_name = os.getenv("DB_NAME", "gabi_dou")
    client = pymongo.MongoClient(uri)
    return client, client[db_name]


def _es_url() -> str:
    return os.getenv("ES_URL", "http://elasticsearch:9200").rstrip("/")


def _es_index() -> str:
    return os.getenv("TCU_ES_INDEX", _ES_INDEX)


# ---------------------------------------------------------------------------
# Text builder
# ---------------------------------------------------------------------------

def _build_embedding_text(doc: dict) -> str:
    """Build text for embedding from TCU document fields."""
    parts = [
        doc.get("titulo") or "",
        doc.get("sumario") or "",
        doc.get("acordao_texto") or "",
    ]
    text = " ".join(p for p in parts if p).strip()
    return text[:_CHAR_LIMIT]


# ---------------------------------------------------------------------------
# OpenAI API
# ---------------------------------------------------------------------------

def _call_openai_embeddings(
    texts: list[str],
    api_key: str,
    client: httpx.Client,
) -> list[list[float]]:
    """Call OpenAI embeddings API. Returns list of vectors."""
    resp = client.post(
        "https://api.openai.com/v1/embeddings",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": _MODEL,
            "input": texts,
            "dimensions": _DIMS,
        },
        timeout=120,
    )

    if resp.status_code == 429:
        # Rate limited — extract retry-after
        retry_after = float(resp.headers.get("retry-after", "10"))
        _log(f"rate limited, waiting {retry_after}s")
        time.sleep(retry_after)
        raise RetryableError("rate limited")

    if resp.status_code >= 500:
        raise RetryableError(f"OpenAI server error: {resp.status_code}")

    resp.raise_for_status()
    data = resp.json()

    # Sort by index to maintain order
    embeddings_data = sorted(data["data"], key=lambda x: x["index"])
    vectors = [item["embedding"] for item in embeddings_data]

    # Validate dimensions
    for v in vectors:
        if len(v) != _DIMS:
            raise RuntimeError(f"Expected {_DIMS} dims, got {len(v)}")

    usage = data.get("usage", {})
    _log(f"API: {len(texts)} texts, {usage.get('total_tokens', '?')} tokens")
    return vectors


class RetryableError(Exception):
    pass


def _call_with_retry(
    texts: list[str],
    api_key: str,
    client: httpx.Client,
    max_retries: int = 3,
) -> list[list[float]]:
    """Call OpenAI with exponential backoff on retryable errors."""
    for attempt in range(1, max_retries + 1):
        try:
            return _call_openai_embeddings(texts, api_key, client)
        except RetryableError as exc:
            if attempt == max_retries:
                raise RuntimeError(f"Failed after {max_retries} retries: {exc}") from exc
            wait = 2 ** attempt
            _log(f"retry {attempt}/{max_retries}, waiting {wait}s: {exc}")
            time.sleep(wait)
    raise RuntimeError("unreachable")


# ---------------------------------------------------------------------------
# ES bulk update (partial doc — only embedding fields)
# ---------------------------------------------------------------------------

def _es_bulk_update_embeddings(
    doc_ids: list[str],
    vectors: list[list[float]],
    es_client: httpx.Client,
) -> int:
    """Bulk update ES docs with embedding vectors. Returns success count."""
    index = _es_index()
    url = f"{_es_url()}/_bulk"

    lines: list[str] = []
    for doc_id, vec in zip(doc_ids, vectors):
        lines.append(json.dumps({"update": {"_index": index, "_id": doc_id}}, ensure_ascii=False))
        lines.append(json.dumps({"doc": {
            "embedding": vec,
            "embedding_status": "done",
        }}, ensure_ascii=False))
    body = "\n".join(lines) + "\n"

    resp = es_client.post(url, data=body.encode("utf-8"), headers={"Content-Type": "application/x-ndjson"}, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("items", [])
    ok = sum(1 for i in items if 200 <= i.get("update", {}).get("status", 500) < 300)
    return ok


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def _process_batch(
    collection,
    api_key: str,
    openai_client: httpx.Client,
    es_client: httpx.Client,
) -> int:
    """Fetch a batch of pending docs, embed, write to ES + Mongo. Returns count processed."""
    # Fetch pending docs
    docs = list(
        collection.find(
            {"embedding_status": "pending"},
            {"_id": 1, "titulo": 1, "sumario": 1, "acordao_texto": 1},
        ).limit(_BATCH_SIZE)
    )
    if not docs:
        return 0

    # Claim docs
    doc_ids = [str(d["_id"]) for d in docs]
    collection.update_many(
        {"_id": {"$in": [d["_id"] for d in docs]}},
        {"$set": {"embedding_status": "processing", "embedding_queued_at": datetime.now(timezone.utc)}},
    )

    # Build texts
    texts: list[str] = []
    valid_ids: list[str] = []
    skip_ids: list[str] = []
    for doc in docs:
        text = _build_embedding_text(doc)
        if len(text) < 10:
            skip_ids.append(str(doc["_id"]))
            continue
        texts.append(text)
        valid_ids.append(str(doc["_id"]))

    # Mark skipped
    if skip_ids:
        collection.update_many(
            {"_id": {"$in": skip_ids}},
            {"$set": {"embedding_status": "skipped", "embedding_updated_at": datetime.now(timezone.utc)}},
        )

    if not texts:
        return len(skip_ids)

    # Call OpenAI in sub-batches
    all_vectors: list[list[float]] = []
    for i in range(0, len(texts), _API_BATCH_SIZE):
        batch_texts = texts[i:i + _API_BATCH_SIZE]
        vectors = _call_with_retry(batch_texts, api_key, openai_client)
        all_vectors.extend(vectors)

    # Write to ES
    es_ok = _es_bulk_update_embeddings(valid_ids, all_vectors, es_client)

    # Update Mongo
    now = datetime.now(timezone.utc)
    for doc_id in valid_ids:
        collection.update_one(
            {"_id": doc_id},
            {"$set": {
                "embedding_status": "done",
                "embedding_model": _MODEL,
                "embedding_updated_at": now,
            }},
        )

    _log(f"batch: embedded={len(valid_ids)} skipped={len(skip_ids)} es_ok={es_ok}")
    return len(valid_ids) + len(skip_ids)


def run_sync(*, init_pending: bool = False) -> None:
    """Main embedding loop."""
    api_key = _openai_key()
    mongo_client, db = _mongo_client()
    collection = db[_MONGO_COLLECTION]

    if init_pending:
        result = collection.update_many(
            {"embedding_status": {"$exists": False}},
            {"$set": {"embedding_status": "pending"}},
        )
        _log(f"init: set {result.modified_count} docs to pending")

        # Also reset any stuck "processing" docs
        stuck = collection.update_many(
            {"embedding_status": "processing"},
            {"$set": {"embedding_status": "pending"}},
        )
        if stuck.modified_count:
            _log(f"init: reset {stuck.modified_count} stuck processing → pending")

    openai_client = httpx.Client(timeout=120)
    es_client = httpx.Client(timeout=60)

    total_processed = 0
    t0 = time.time()
    loops = 0

    try:
        while True:
            loops += 1
            count = _process_batch(collection, api_key, openai_client, es_client)
            if count == 0:
                break
            total_processed += count
            elapsed = time.time() - t0
            rate = total_processed / elapsed * 3600 if elapsed > 0 else 0
            _log(f"progress: {total_processed} docs, {elapsed:.0f}s, {rate:.0f}/hr")
    finally:
        openai_client.close()
        es_client.close()
        mongo_client.close()

    elapsed = time.time() - t0
    _log(f"DONE: {total_processed} docs embedded in {elapsed:.0f}s")


def cmd_stats() -> None:
    """Show embedding progress stats."""
    mongo_client, db = _mongo_client()
    collection = db[_MONGO_COLLECTION]

    pipeline = [
        {"$group": {"_id": "$embedding_status", "count": {"$sum": 1}}},
    ]
    results = {r["_id"]: r["count"] for r in collection.aggregate(pipeline)}
    total = sum(results.values())

    done = results.get("done", 0)
    pending = results.get("pending", 0)
    processing = results.get("processing", 0)
    failed = results.get("failed", 0)
    skipped = results.get("skipped", 0)
    no_status = results.get(None, 0)

    pct = (done / total * 100) if total > 0 else 0

    # ES count with embeddings
    try:
        es_client = httpx.Client(timeout=10)
        resp = es_client.post(
            f"{_es_url()}/{_es_index()}/_count",
            json={"query": {"exists": {"field": "embedding"}}},
            headers={"Content-Type": "application/json"},
        )
        es_with_emb = resp.json().get("count", "?")
        es_client.close()
    except Exception:
        es_with_emb = "?"

    mongo_client.close()

    print(json.dumps({
        "total": total,
        "done": done,
        "pending": pending,
        "processing": processing,
        "failed": failed,
        "skipped": skipped,
        "no_status": no_status,
        "pct_done": round(pct, 1),
        "es_with_embedding": es_with_emb,
    }, indent=2))


def cmd_reset_failed() -> None:
    """Reset failed docs back to pending."""
    mongo_client, db = _mongo_client()
    collection = db[_MONGO_COLLECTION]
    result = collection.update_many(
        {"embedding_status": "failed"},
        {"$set": {"embedding_status": "pending"}},
    )
    _log(f"reset {result.modified_count} failed → pending")
    mongo_client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="TCU embedding pipeline (OpenAI)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("backfill", help="Init all pending + run full backfill")
    sub.add_parser("sync", help="Embed pending docs (incremental)")
    sub.add_parser("stats", help="Show embedding progress")
    sub.add_parser("reset-failed", help="Reset failed → pending")

    args = parser.parse_args()

    if args.cmd == "backfill":
        run_sync(init_pending=True)
    elif args.cmd == "sync":
        run_sync(init_pending=False)
    elif args.cmd == "stats":
        cmd_stats()
    elif args.cmd == "reset-failed":
        cmd_reset_failed()


if __name__ == "__main__":
    main()
