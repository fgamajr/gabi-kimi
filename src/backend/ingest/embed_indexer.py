"""Embedding indexer for DOU documents (backfill, sync, stats).

Reads documents from MongoDB, calls Qwen3-Embedding server on Mac,
writes embeddings to Elasticsearch and status to MongoDB.

Usage:
  python3 -m src.backend.ingest.embed_indexer init-status
  python3 -m src.backend.ingest.embed_indexer backfill
  python3 -m src.backend.ingest.embed_indexer stats
  python3 -m src.backend.ingest.embed_indexer reset-failed
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import time
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any

import httpx
import pymongo
from pymongo import ReturnDocument


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

EMBED_SERVER_URL = os.getenv("EMBED_SERVER_URL", "http://192.168.15.20:8900")
EMBED_DIMS = int(os.getenv("EMBED_DIMS", "384"))
EMBED_MODEL = "qwen3-embedding-0.6b"
EMBED_BATCH_SIZE = 64
MAX_ATTEMPTS = 3
STALE_PROCESSING_MINUTES = 120
CHAR_LIMIT = 2_000  # ~512 tokens for Portuguese text — server truncates at 512

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    print(f"[embed-indexer] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Mongo helpers
# ---------------------------------------------------------------------------


def _mongo_client():
    uri = os.getenv("MONGO_STRING", "mongodb://localhost:27017/gabi_dou")
    db_name = os.getenv("DB_NAME", "gabi_dou")
    client = pymongo.MongoClient(uri)
    return client, client[db_name]


# ---------------------------------------------------------------------------
# ES helpers (reuse pattern from es_indexer)
# ---------------------------------------------------------------------------


class ESClient:
    def __init__(self) -> None:
        self.url = os.getenv("ES_URL", "http://localhost:9200").rstrip("/")
        self.index = os.getenv("ES_INDEX", "gabi_documents_v2")
        self.client = httpx.Client(timeout=30)

    def bulk_update_embeddings(
        self, updates: list[dict[str, Any]], retries: int = 3
    ) -> tuple[int, int]:
        """Partial update: write embedding vector to existing ES docs."""
        lines: list[str] = []
        for u in updates:
            action = {"update": {"_index": self.index, "_id": u["doc_id"], "retry_on_conflict": 3}}
            doc = {
                "embedding": u["embedding"],
                "embedding_status": "done",
                "embedding_model": EMBED_MODEL,
            }
            lines.append(json.dumps(action, ensure_ascii=False))
            lines.append(json.dumps({"doc": doc}, ensure_ascii=False))
        body = "\n".join(lines) + "\n"

        last_error: str | None = None
        for attempt in range(1, retries + 1):
            resp = self.client.post(
                f"{self.url}/_bulk",
                content=body.encode("utf-8"),
                headers={"Content-Type": "application/x-ndjson"},
            )
            if resp.status_code in (429, 502, 503, 504):
                last_error = f"http {resp.status_code}"
                time.sleep(1.5 * attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            ok = sum(1 for it in items if 200 <= it.get("update", {}).get("status", 500) < 300)
            failed = len(items) - ok
            if failed:
                first_err = next(
                    (it["update"].get("error") for it in items if it.get("update", {}).get("status", 500) >= 300),
                    None,
                )
                _log(f"ES bulk partial failure: ok={ok} failed={failed} first_error={first_err}")
            return ok, failed
        raise RuntimeError(f"ES bulk update failed after retries: {last_error}")


# ---------------------------------------------------------------------------
# Text construction
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(
    r"<(?:/?(?:p|br|div|table|tr|td|th|span|a|b|i|em|strong|ul|ol|li|h[1-6])\b)[^>]*>",
    re.IGNORECASE,
)
_WHITESPACE_RE = re.compile(r"\s+")


def _clean_text(raw: str | None) -> str | None:
    if not raw or not isinstance(raw, str):
        return None
    text = raw.replace("\x00", "")
    text = unescape(text)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = _HTML_TAG_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text)
    text = text.strip()
    return text if len(text) >= 10 else None


def _build_embedding_text(doc: dict) -> str | None:
    """Build embedding input: identifica + ementa + texto, capped at CHAR_LIMIT."""
    parts = []
    chars_used = 0
    for field in ("identifica", "ementa", "texto"):
        raw = doc.get(field)
        # For very long texto, only clean the first slice
        if field == "texto" and raw and len(raw) > CHAR_LIMIT * 2:
            raw = raw[: CHAR_LIMIT * 2]
        value = _clean_text(raw)
        if not value:
            continue
        sep_len = 1 if parts else 0  # newline separator
        available = CHAR_LIMIT - chars_used - sep_len
        if available <= 20:
            break
        if len(value) > available:
            value = value[:available].strip()
        if len(value) >= 10:
            parts.append(value)
            chars_used += sep_len + len(value)
    text = "\n".join(parts).strip()
    return text if len(text) >= 10 else None


# ---------------------------------------------------------------------------
# Embedding server client
# ---------------------------------------------------------------------------


def _call_embed_server(
    texts: list[str], http: httpx.Client, max_retries: int = 5
) -> list[list[float]]:
    """Call Qwen3 embedding server with retry on 503 (memory pressure) and 500."""
    for attempt in range(max_retries):
        resp = http.post(
            f"{EMBED_SERVER_URL}/embed",
            json={"texts": texts, "dimensions": EMBED_DIMS},
            timeout=120,
        )
        if resp.status_code == 503:
            delay = 10.0 * (attempt + 1)
            _log(f"embed server memory pressure (503), waiting {delay:.0f}s...")
            time.sleep(delay)
            continue
        if resp.status_code == 500:
            delay = 5.0 * (attempt + 1)
            _log(f"embed server error (500), waiting {delay:.0f}s...")
            time.sleep(delay)
            continue
        resp.raise_for_status()
        data = resp.json()
        embeddings = data["embeddings"]
        if embeddings and len(embeddings[0]) != EMBED_DIMS:
            raise ValueError(f"Expected {EMBED_DIMS} dims, got {len(embeddings[0])}")
        return embeddings
    raise RuntimeError(f"embed server failed after {max_retries} retries (last status={resp.status_code})")


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    _shutdown = True
    _log(f"received signal {signum}, finishing current batch...")


def _fetch_and_claim_batch(collection, batch_size: int) -> list[dict]:
    """Atomically fetch and claim docs using findOneAndUpdate."""
    now = datetime.now(timezone.utc)
    base_query = {
        "embedding_status": "pending",
        "embedding_attempts": {"$not": {"$gte": MAX_ATTEMPTS}},
    }
    docs = []
    last_id = None

    for _ in range(batch_size):
        query = {**base_query}
        if last_id is not None:
            query["_id"] = {"$gt": last_id}

        doc = collection.find_one_and_update(
            query,
            {
                "$set": {
                    "embedding_status": "processing",
                    "embedding_queued_at": now,
                },
                "$inc": {"embedding_attempts": 1},
            },
            sort=[("_id", 1)],
            return_document=ReturnDocument.AFTER,
            projection={
                "_id": 1,
                "identifica": 1,
                "ementa": 1,
                "texto": 1,
            },
        )
        if doc is None:
            break
        docs.append(doc)
        last_id = doc["_id"]

    return docs


def _recover_stale_processing(collection) -> int:
    """Reset stale 'processing' docs from crashed runs."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_PROCESSING_MINUTES)
    result = collection.update_many(
        {
            "embedding_status": "processing",
            "embedding_queued_at": {"$lt": cutoff},
            "embedding_attempts": {"$not": {"$gte": MAX_ATTEMPTS}},
        },
        {"$set": {"embedding_status": "pending"}},
    )
    if result.modified_count > 0:
        _log(f"recovery: reset {result.modified_count} stale 'processing' docs to 'pending'")
    return result.modified_count


def _prepare_batch(docs: list[dict]) -> tuple[list[str], list[str], list[str]]:
    """Build texts for embedding. Returns (texts, text_doc_ids, skipped_ids)."""
    texts = []
    text_doc_ids = []
    skipped_ids = []
    for doc in docs:
        doc_id = str(doc["_id"])
        text = _build_embedding_text(doc)
        if text is None:
            skipped_ids.append(doc_id)
        else:
            texts.append(text)
            text_doc_ids.append(doc_id)
    return texts, text_doc_ids, skipped_ids


def _write_results(
    text_doc_ids: list[str],
    embeddings: list[list[float]],
    skipped_ids: list[str],
    collection,
    es: ESClient,
) -> tuple[int, int, int]:
    """Write embeddings to ES + update MongoDB status. Returns (ok, failed, skipped)."""
    # Mark skipped in MongoDB
    if skipped_ids:
        collection.update_many(
            {"_id": {"$in": skipped_ids}},
            {
                "$set": {
                    "embedding_status": "skipped",
                    "embedding_error": "no_text_content",
                    "embedding_updated_at": datetime.now(timezone.utc),
                }
            },
        )

    if not text_doc_ids:
        return 0, 0, len(skipped_ids)

    # Write to ES first (ES-before-Mongo ordering)
    es_updates = [
        {"doc_id": did, "embedding": emb}
        for did, emb in zip(text_doc_ids, embeddings)
    ]
    es_ok, es_failed = es.bulk_update_embeddings(es_updates)

    # Update MongoDB status
    now = datetime.now(timezone.utc)
    bulk_ops = [
        pymongo.UpdateOne(
            {"_id": did},
            {"$set": {"embedding_status": "done", "embedding_model": EMBED_MODEL, "embedding_updated_at": now}},
        )
        for did in text_doc_ids
    ]
    if bulk_ops:
        collection.bulk_write(bulk_ops, ordered=False)

    return es_ok, es_failed, len(skipped_ids)


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


def cmd_init_status(args: argparse.Namespace) -> None:
    """One-time migration: set embedding_status='pending' on all docs."""
    client, db = _mongo_client()
    collection = db["documents"]
    try:
        # Create compound index for efficient cursor queries
        collection.create_index(
            [("embedding_status", 1), ("_id", 1)],
            name="idx_embedding_status_id",
        )
        _log("ensured index idx_embedding_status_id")

        result = collection.update_many(
            {"embedding_status": {"$exists": False}},
            {"$set": {"embedding_status": "pending", "embedding_attempts": 0}},
        )
        _log(f"initialized {result.modified_count} documents to 'pending'")
    finally:
        client.close()


def cmd_backfill(args: argparse.Namespace) -> None:
    """Full embedding backfill."""
    # Init status if needed, then run
    cmd_init_status(args)
    _run_embed_loop(args)


def cmd_sync(args: argparse.Namespace) -> None:
    """Process only pending documents (incremental)."""
    _run_embed_loop(args)


MEM_BACKOFF_PCT = float(os.getenv("MEM_BACKOFF_PCT", "84"))
MEM_BACKOFF_MAX_WAIT = 120  # max seconds to wait for memory to drop


def _wait_for_memory(http: httpx.Client) -> bool:
    """Check embed server memory and back off if too high. Returns False if server is down."""
    try:
        resp = http.get(f"{EMBED_SERVER_URL}/health", timeout=10)
        resp.raise_for_status()
        mem_pct = resp.json().get("system_mem_pct", 0)
    except Exception:
        return False

    if mem_pct <= MEM_BACKOFF_PCT:
        return True

    waited = 0
    while mem_pct > MEM_BACKOFF_PCT and waited < MEM_BACKOFF_MAX_WAIT:
        wait = 10
        _log(f"memory backoff: {mem_pct:.1f}% > {MEM_BACKOFF_PCT}%, waiting {wait}s...")
        time.sleep(wait)
        waited += wait
        try:
            resp = http.get(f"{EMBED_SERVER_URL}/health", timeout=10)
            mem_pct = resp.json().get("system_mem_pct", 0)
        except Exception:
            return False

    if mem_pct > MEM_BACKOFF_PCT:
        _log(f"memory still high after {waited}s ({mem_pct:.1f}%), proceeding cautiously")
    else:
        _log(f"memory OK: {mem_pct:.1f}% after {waited}s backoff")
    return True


def _run_embed_loop(args: argparse.Namespace) -> None:
    """Pipelined embed loop: overlap GPU work with DB reads/writes via threads."""
    from concurrent.futures import ThreadPoolExecutor, Future

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    global _shutdown
    batch_size = args.batch_size
    delay = args.delay
    es = ESClient()
    http = httpx.Client(timeout=120)

    # Pre-flight: check embedding server
    try:
        resp = http.get(f"{EMBED_SERVER_URL}/health", timeout=10)
        resp.raise_for_status()
        health = resp.json()
        _log(f"embedding server OK: {health}")
        _log(f"memory backoff threshold: {MEM_BACKOFF_PCT}% (current: {health.get('system_mem_pct', '?')}%)")
    except Exception as e:
        _log(f"ERROR: embedding server unreachable at {EMBED_SERVER_URL}: {e}")
        return

    client, db = _mongo_client()
    collection = db["documents"]
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        # Recovery sweep
        _recover_stale_processing(collection)

        total_ok = 0
        total_failed = 0
        total_skipped = 0
        batch_num = 0
        start_time = time.time()
        consecutive_errors = 0

        # Pipeline state: previous batch's write future
        pending_write: Future | None = None

        while not _shutdown:
            # Memory guard: wait if server is under pressure
            if not _wait_for_memory(http):
                consecutive_errors += 1
                _log(f"embed server unreachable during memory check (error {consecutive_errors}/10)")
                if consecutive_errors >= 10:
                    _log("ABORT: 10 consecutive errors")
                    break
                time.sleep(min(10.0 * consecutive_errors, 60.0))
                continue

            batch_num += 1
            docs = _fetch_and_claim_batch(collection, batch_size)
            if not docs:
                _log("no more pending documents")
                break

            try:
                # Prepare texts (fast, CPU-only)
                texts, text_doc_ids, skipped_ids = _prepare_batch(docs)

                if not texts:
                    total_skipped += len(skipped_ids)
                    # Still need to mark skipped
                    _write_results([], [], skipped_ids, collection, es)
                    continue

                # Call embedding server (the slow part — GPU)
                embeddings = _call_embed_server(texts, http)

                # Wait for previous write to finish before starting new one
                if pending_write is not None:
                    w_ok, w_failed, w_skipped = pending_write.result()
                    total_ok += w_ok
                    total_failed += w_failed
                    total_skipped += w_skipped

                # Fire off write for THIS batch in background thread
                pending_write = pool.submit(
                    _write_results, text_doc_ids, embeddings, skipped_ids, collection, es,
                )
                consecutive_errors = 0
                elapsed = time.time() - start_time
                rate = (total_ok + len(text_doc_ids)) / elapsed if elapsed > 0 else 0
                _log(
                    f"batch={batch_num} embedded={len(text_doc_ids)} skipped={len(skipped_ids)} "
                    f"total≈{total_ok + len(text_doc_ids)} rate={rate:.0f} docs/sec"
                )
            except Exception as e:
                consecutive_errors += 1
                _log(f"ERROR batch={batch_num}: {e}")

                # Reset claimed docs back to pending on error
                doc_ids = [doc["_id"] for doc in docs]
                collection.update_many(
                    {"_id": {"$in": doc_ids}, "embedding_status": "processing"},
                    {"$set": {"embedding_status": "pending"}},
                )

                if consecutive_errors >= 10:
                    _log("ABORT: 10 consecutive batch errors")
                    break
                time.sleep(min(5.0 * consecutive_errors, 60.0))
                continue

            if delay > 0:
                time.sleep(delay)

        # Drain last pending write
        if pending_write is not None:
            try:
                w_ok, w_failed, w_skipped = pending_write.result(timeout=30)
                total_ok += w_ok
                total_failed += w_failed
                total_skipped += w_skipped
            except Exception as e:
                _log(f"ERROR draining last write: {e}")

    finally:
        pool.shutdown(wait=False)
        client.close()
        http.close()

    elapsed = time.time() - start_time
    _log(
        f"done total_ok={total_ok} total_failed={total_failed} "
        f"total_skipped={total_skipped} elapsed={elapsed:.0f}s"
    )


def cmd_stats(args: argparse.Namespace) -> None:
    """Show embedding progress statistics."""
    client, db = _mongo_client()
    collection = db["documents"]
    try:
        pipeline = [
            {"$group": {"_id": "$embedding_status", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ]
        status_counts = {doc["_id"]: doc["count"] for doc in collection.aggregate(pipeline)}
        total = sum(status_counts.values())

        done = status_counts.get("done", 0)
        pending = status_counts.get("pending", 0)
        processing = status_counts.get("processing", 0)
        failed = status_counts.get("failed", 0)
        skipped = status_counts.get("skipped", 0)
        no_status = status_counts.get(None, 0)

        pct = (done / total * 100) if total > 0 else 0

        print(
            json.dumps(
                {
                    "total": total,
                    "done": done,
                    "pending": pending,
                    "processing": processing,
                    "failed": failed,
                    "skipped": skipped,
                    "no_status": no_status,
                    "progress_pct": round(pct, 2),
                    "embed_server": EMBED_SERVER_URL,
                    "embed_model": EMBED_MODEL,
                    "embed_dims": EMBED_DIMS,
                },
                indent=2,
            )
        )
    finally:
        client.close()


def cmd_reset_failed(args: argparse.Namespace) -> None:
    """Reset failed documents back to pending for retry."""
    client, db = _mongo_client()
    collection = db["documents"]
    try:
        result = collection.update_many(
            {"embedding_status": "failed"},
            {"$set": {"embedding_status": "pending", "embedding_attempts": 0}},
        )
        _log(f"reset {result.modified_count} failed docs to 'pending'")
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Embedding indexer for GABI DOU (MongoDB → Qwen3 → ES)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init-status", help="Initialize embedding_status on all documents")
    sp.set_defaults(func=cmd_init_status)

    sp = sub.add_parser("backfill", help="Full embedding backfill (runs init-status first)")
    sp.add_argument("--batch-size", type=int, default=EMBED_BATCH_SIZE)
    sp.add_argument("--delay", type=float, default=0.1, help="Seconds between batches")
    sp.set_defaults(func=cmd_backfill)

    sp = sub.add_parser("sync", help="Process only pending documents")
    sp.add_argument("--batch-size", type=int, default=EMBED_BATCH_SIZE)
    sp.add_argument("--delay", type=float, default=0.1, help="Seconds between batches")
    sp.set_defaults(func=cmd_sync)

    sp = sub.add_parser("stats", help="Embedding progress statistics")
    sp.set_defaults(func=cmd_stats)

    sp = sub.add_parser("reset-failed", help="Reset failed docs to pending")
    sp.set_defaults(func=cmd_reset_failed)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
