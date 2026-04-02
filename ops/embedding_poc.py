#!/usr/bin/env python3
"""Embedding PoC — compare Qwen3-Embedding vs Gemini text-embedding.

Usage:
  python3 ops/embedding_poc.py --sample-size 500 --runs 3
  python3 ops/embedding_poc.py --output ops/baselines/embedding_poc_20260401.json

Outputs: ops/baselines/embedding_poc_YYYYMMDD_<commit>.json
Feeds: ADR-001 (S0-2 gate).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


# ---------------------------------------------------------------------------
# Config — read from env / .env
# ---------------------------------------------------------------------------

_DOTENV_PATH = Path(__file__).resolve().parents[1] / ".env"
if _DOTENV_PATH.exists():
    with open(_DOTENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if "=" in _line and not _line.startswith("#"):
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())


@dataclass
class EmbedConfig:
    # Qwen3 — local ONNX server (Mac dev / Linux prod)
    qwen_url: str = os.getenv("EMBED_SERVER_URL", "http://192.168.15.20:8900").rstrip(
        "/"
    )
    qwen_dims: int = int(os.getenv("EMBED_DIMS", "384"))

    # Gemini API
    gemini_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = (
        os.getenv("GEMINI_API_MODELS", "gemini-2.0-flash").split(";")[0].strip()
    )
    gemini_base: str = os.getenv(
        "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
    ).rstrip("/")

    # ES
    es_url: str = os.getenv("ES_URL", "http://localhost:9200").rstrip("/")
    es_dou_index: str = os.getenv("ES_INDEX", "gabi_documents_v3")
    es_tcu_index: str = os.getenv("TCU_ES_INDEX", "gabi_tcu_acordaos_v1")

    # Sample
    sample_size: int = 500  # per corpus (DOU + TCU)
    char_limit: int = 2000  # chars per doc (matches embed_indexer.py CHAR_LIMIT)

    # PoC query set (representative Brazilian legal queries)
    queries: list[str] = field(
        default_factory=lambda: [
            "licitação obras públicas",
            "portaria Ministério da Fazenda",
            "decreto presidenciais",
            "acórdão Tribunal de Contas",
            "instrução normativa Receita Federal",
            "Fernando Gama",
            "contrato gestão",
            "CNPJ empresa",
            "portaria，海关",
            "artigo Lei 13709",
            "养恤金",
            "aditivo contrato administrativo",
            "pregão eletrônico",
            "relatório gestão",
            "TCU decisão",
        ]
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_short_commit() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
            or "nogit"
        )
    except Exception:
        return "nogit"


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 3)
    return round(
        float(
            statistics.quantiles(values, n=100, method="inclusive")[int(q * 100) - 1]
        ),
        3,
    )


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    import math

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _clean_text(raw: str | None) -> str | None:
    """Minimal text cleaner matching embed_indexer._build_embedding_text."""
    if not raw or not isinstance(raw, str):
        return None
    import re

    text = (
        raw.replace("\x00", "")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) >= 10 else None


def _build_doc_text(doc: dict[str, Any], char_limit: int) -> str | None:
    """Build embedding input from DOU/TCU fields, capped."""
    parts: list[str] = []
    chars_used = 0
    for field_name in (
        # DOU
        "identifica",
        "ementa",
        "texto",
        "body_plain",
        # TCU
        "titulo",
        "sumario",
        "acordao_texto",
        "enunciado",
        "excerto",
        "assunto",
        "texto_completo",
        "description",
        "title",
    ):
        raw = doc.get(field_name)
        if not raw:
            continue
        value = _clean_text(raw)
        if not value:
            continue
        sep_len = 1 if parts else 0
        available = char_limit - chars_used - sep_len
        if available <= 20:
            break
        if len(value) > available:
            value = value[:available].strip()
        if len(value) >= 10:
            parts.append(value)
            chars_used += sep_len + len(value)
    return "\n".join(parts).strip() if parts else None


# ---------------------------------------------------------------------------
# Document fetching from ES
# ---------------------------------------------------------------------------


def _fetch_es_sample(
    client: httpx.Client, es_url: str, index: str, size: int, query: str | None = None
) -> list[dict[str, Any]]:
    """Fetch sample documents from ES using _msearch or _search."""
    body: dict[str, Any] = {
        "query": {"match_all": {}}
        if not query
        else {
            "multi_match": {
                "query": query,
                "fields": ["identifica", "ementa", "body_plain"],
            }
        }
    }
    try:
        resp = client.post(
            f"{es_url}/{index}/_search",
            json={
                "size": size,
                "query": body["query"],
                "_source": [
                    "identifica",
                    "ementa",
                    "texto",
                    "body_plain",
                    "titulo",
                    "sumario",
                    "acordao_texto",
                    "enunciado",
                    "excerto",
                    "assunto",
                    "texto_completo",
                    "description",
                    "title",
                    "pub_date",
                    "issuing_organ",
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
        docs: list[dict[str, Any]] = []
        for hit in hits:
            src = hit.get("_source") or {}
            docs.append({"__doc_id": str(hit.get("_id") or ""), **src})
        return docs
    except Exception as exc:
        print(f"[embedding_poc] ES fetch error ({index}): {exc}", file=sys.stderr)
        return []


# ---------------------------------------------------------------------------
# Embedding providers
# ---------------------------------------------------------------------------


def _call_qwen_embed(
    client: httpx.Client, url: str, texts: list[str], dims: int
) -> tuple[list[list[float]], float]:
    """Call Qwen3-Embedding via infinity-emb (OpenAI-compatible). Returns (embeddings, latency_ms)."""
    t0 = time.perf_counter()
    resp = client.post(
        f"{url}/v1/embeddings",
        json={"input": texts, "model": "qwen3-embedding", "dimensions": dims},
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    latency_ms = (time.perf_counter() - t0) * 1000
    embeddings = [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
    return embeddings, latency_ms


def _call_gemini_embed(
    client: httpx.Client, base_url: str, api_key: str, model: str, texts: list[str]
) -> tuple[list[list[float]], float]:
    """Call Gemini text-embedding API. Returns (embeddings, latency_ms)."""
    t0 = time.perf_counter()
    embeddings: list[list[float]] = []
    for text in texts:
        payload = {"content": {"role": "user", "parts": [{"text": text}]}}
        emb: list[float] = []
        for attempt in range(1, 6):
            resp = client.post(
                f"{base_url}/models/{model}:embedContent?key={api_key}",
                json=payload,
                timeout=60,
            )
            if resp.status_code in {429, 500, 502, 503, 504} and attempt < 5:
                time.sleep(min(20, 2**attempt))
                continue
            resp.raise_for_status()
            data = resp.json()
            emb = data.get("embedding", {}).get("values", [])
            break
        embeddings.append(emb)
    latency_ms = (time.perf_counter() - t0) * 1000
    return embeddings, latency_ms


# ---------------------------------------------------------------------------
# Recall computation — BM25 ground truth vs embedding similarity
# ---------------------------------------------------------------------------


def _bm25_topk(
    client: httpx.Client,
    es_url: str,
    index: str,
    query: str,
    k: int = 10,
    allowed_ids: list[str] | None = None,
) -> list[str]:
    """Return top-K doc_ids by BM25 for a given query."""
    try:
        bool_query: dict[str, Any] = {
            "must": [
                {
                    "multi_match": {
                        "query": query,
                        "fields": ["identifica^3", "ementa^2", "body_plain"],
                    }
                }
            ]
        }
        if allowed_ids:
            bool_query["filter"] = [{"ids": {"values": allowed_ids}}]
        resp = client.post(
            f"{es_url}/{index}/_search",
            json={
                "size": k,
                "query": {"bool": bool_query},
                "_source": False,
            },
            timeout=30,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
        return [hit["_id"] for hit in hits]
    except Exception:
        return []


def _embedding_topk(
    query_emb: list[float], doc_embs: list[tuple[str, list[float]]]
) -> list[str]:
    """Return top-K doc_ids ranked by cosine similarity to query_emb."""
    scored = [(doc_id, _cosine_sim(query_emb, doc_emb)) for doc_id, doc_emb in doc_embs]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [doc_id for doc_id, _ in scored[:10]]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _recall_at_k(gt: list[str], pred: list[str], k: int) -> float:
    gt_set = set(gt[:k])
    pred_set = set(pred[:k])
    if not gt_set:
        return 0.0
    return len(gt_set & pred_set) / min(k, len(gt_set))


@dataclass
class QueryResult:
    query: str
    provider: str
    latency_ms: float
    recall_at_10: float
    error: str | None


def main() -> int:
    parser = argparse.ArgumentParser(description="Embedding PoC — Qwen3 vs Gemini")
    parser.add_argument(
        "--sample-size", type=int, default=500, help="Docs per corpus (default: 500)"
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Query repetitions per provider (default: 3)",
    )
    parser.add_argument("--output", default=None, help="Output JSON path")
    parser.add_argument(
        "--timeout", type=float, default=60.0, help="Request timeout in seconds"
    )
    args = parser.parse_args()

    cfg = EmbedConfig(sample_size=args.sample_size)
    commit = _git_short_commit()
    output_path = (
        Path(args.output)
        if args.output
        else (
            Path("ops/baselines")
            / f"embedding_poc_{datetime.now(UTC).strftime('%Y%m%d')}_{commit}.json"
        )
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(
        f"[embedding_poc] Fetching {args.sample_size} DOU + {args.sample_size} TCU docs from ES..."
    )

    with httpx.Client(timeout=args.timeout) as client:
        # Fetch samples
        dou_docs = _fetch_es_sample(
            client, cfg.es_url, cfg.es_dou_index, args.sample_size
        )
        tcu_docs = _fetch_es_sample(
            client, cfg.es_url, cfg.es_tcu_index, args.sample_size
        )

        if not dou_docs and not tcu_docs:
            print(
                "[embedding_poc] ERROR: no documents fetched from ES. Check ES_URL and index names.",
                file=sys.stderr,
            )
            return 1

        print(f"[embedding_poc] Got {len(dou_docs)} DOU docs, {len(tcu_docs)} TCU docs")

        # Build text list
        all_texts: list[tuple[str, str]] = []  # (doc_id, text)
        sampled_dou_ids: list[str] = []
        sampled_tcu_ids: list[str] = []
        for doc in dou_docs:
            text = _build_doc_text(doc, cfg.char_limit)
            if text:
                doc_id = str(doc.get("__doc_id") or "").strip()
                if doc_id:
                    sampled_dou_ids.append(doc_id)
                    all_texts.append((f"dou:{doc_id}", text))
        for doc in tcu_docs:
            text = _build_doc_text(doc, cfg.char_limit)
            if text:
                doc_id = str(doc.get("__doc_id") or "").strip()
                if doc_id:
                    sampled_tcu_ids.append(doc_id)
                    all_texts.append((f"tcu:{doc_id}", text))

        if len(all_texts) < 10:
            print(
                "[embedding_poc] ERROR: too few valid documents after cleaning",
                file=sys.stderr,
            )
            return 1

        print(f"[embedding_poc] {len(all_texts)} documents with clean text")

        # Build embedding corpus (doc_id -> embedding)
        qwen_embs: dict[str, list[float]] = {}
        gemini_embs: dict[str, list[float]] = {}

        # Batch embed all docs
        texts_only = [t for _, t in all_texts]
        doc_ids = [d for d, _ in all_texts]

        # Qwen3 embedding
        print("[embedding_poc] Calling Qwen3-Embedding...")
        try:
            qwen_results, qwen_total_ms = _call_qwen_embed(
                client, cfg.qwen_url, texts_only, cfg.qwen_dims
            )
            qwen_embs = dict(zip(doc_ids, qwen_results))
            print(
                f"[embedding_poc] Qwen3 done: {len(qwen_embs)} embeddings in {qwen_total_ms:.1f}ms"
            )
        except Exception as exc:
            print(f"[embedding_poc] Qwen3 ERROR: {exc}", file=sys.stderr)

        # Gemini embedding
        if cfg.gemini_key:
            print("[embedding_poc] Calling Gemini embedding...")
            try:
                gemini_results, gemini_total_ms = _call_gemini_embed(
                    client,
                    cfg.gemini_base,
                    cfg.gemini_key,
                    cfg.gemini_model,
                    texts_only,
                )
                gemini_embs = dict(zip(doc_ids, gemini_results))
                print(
                    f"[embedding_poc] Gemini done: {len(gemini_embs)} embeddings in {gemini_total_ms:.1f}ms"
                )
            except Exception as exc:
                print(f"[embedding_poc] Gemini ERROR: {exc}", file=sys.stderr)
        else:
            print("[embedding_poc] GEMINI_API_KEY not set — skipping Gemini")

        # Run recall evaluation for each query
        results: list[QueryResult] = []

        for query in cfg.queries:
            bm25_dou = _bm25_topk(
                client,
                cfg.es_url,
                cfg.es_dou_index,
                query,
                k=10,
                allowed_ids=sampled_dou_ids,
            )
            bm25_tcu = _bm25_topk(
                client,
                cfg.es_url,
                cfg.es_tcu_index,
                query,
                k=10,
                allowed_ids=sampled_tcu_ids,
            )
            bm25_ids = [f"dou:{doc_id}" for doc_id in bm25_dou] + [
                f"tcu:{doc_id}" for doc_id in bm25_tcu
            ]

            # Qwen3 recall
            if qwen_embs and bm25_ids:
                qwen_latencies: list[float] = []
                qwen_recalls: list[float] = []
                for _ in range(args.runs):
                    t0 = time.perf_counter()
                    try:
                        q_emb, _ = _call_qwen_embed(
                            client, cfg.qwen_url, [query], cfg.qwen_dims
                        )
                        lat = (time.perf_counter() - t0) * 1000
                        qwen_latencies.append(lat)
                        doc_embs = [
                            (did, qwen_embs[did]) for did in doc_ids if did in qwen_embs
                        ]
                        topk = _embedding_topk(q_emb[0], doc_embs)
                        qwen_recalls.append(_recall_at_k(bm25_ids, topk, 10))
                    except Exception:
                        pass
                if qwen_latencies:
                    results.append(
                        QueryResult(
                            query=query,
                            provider="qwen3-embedding-0.6b",
                            latency_ms=round(statistics.mean(qwen_latencies), 3),
                            recall_at_10=round(statistics.mean(qwen_recalls), 4)
                            if qwen_recalls
                            else 0.0,
                            error=None,
                        )
                    )

            # Gemini recall
            if gemini_embs and cfg.gemini_key and bm25_ids:
                gemini_latencies: list[float] = []
                gemini_recalls: list[float] = []
                for _ in range(args.runs):
                    t0 = time.perf_counter()
                    try:
                        g_emb, _ = _call_gemini_embed(
                            client,
                            cfg.gemini_base,
                            cfg.gemini_key,
                            cfg.gemini_model,
                            [query],
                        )
                        lat = (time.perf_counter() - t0) * 1000
                        gemini_latencies.append(lat)
                        doc_embs = [
                            (did, gemini_embs[did])
                            for did in doc_ids
                            if did in gemini_embs
                        ]
                        topk = _embedding_topk(g_emb[0], doc_embs)
                        gemini_recalls.append(_recall_at_k(bm25_ids, topk, 10))
                    except Exception:
                        pass
                if gemini_latencies:
                    results.append(
                        QueryResult(
                            query=query,
                            provider="gemini-text-embedding",
                            latency_ms=round(statistics.mean(gemini_latencies), 3),
                            recall_at_10=round(statistics.mean(gemini_recalls), 4)
                            if gemini_recalls
                            else 0.0,
                            error=None,
                        )
                    )

    # Aggregate
    providers = ["qwen3-embedding-0.6b", "gemini-text-embedding"]
    summary: dict[str, Any] = {}
    sample_avg_chars = (
        (sum(len(text) for _, text in all_texts) / len(all_texts)) if all_texts else 0.0
    )
    sample_avg_tokens = sample_avg_chars / 4.0 if sample_avg_chars else 0.0
    gemini_price_per_1k_tokens = float(
        os.getenv("GEMINI_EMBED_PRICE_PER_1K_TOKENS", "0.0001")
    )
    for prov in providers:
        prov_results = [r for r in results if r.provider == prov and r.error is None]
        if not prov_results:
            continue
        recalls = [r.recall_at_10 for r in prov_results]
        lats = [r.latency_ms for r in prov_results]
        dims = (
            cfg.qwen_dims
            if prov == "qwen3-embedding-0.6b"
            else (len(list(gemini_embs.values())[0]) if gemini_embs else 0)
        )
        summary[prov] = {
            "dims": dims,
            "recall@10_p50": _quantile(recalls, 0.50),
            "recall@10_p95": _quantile(recalls, 0.95),
            "recall@10_avg": round(sum(recalls) / len(recalls), 4),
            "latency_ms_p50": _quantile(lats, 0.50),
            "latency_ms_p95": _quantile(lats, 0.95),
            "sample_docs": len(all_texts),
            "sample_dou": len(dou_docs),
            "sample_tcu": len(tcu_docs),
            "queries_evaluated": len(prov_results),
            # Cost estimate based on sample avg tokens/doc and configurable $/1K tokens.
            "cost_estimate_per_1m_docs_usd": (
                round(
                    1_000_000 * sample_avg_tokens / 1000.0 * gemini_price_per_1k_tokens,
                    2,
                )
                if prov == "gemini-text-embedding"
                else 0.0
            ),
        }

    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "commit": commit,
        "query_set_id": "poc_queries_v1",
        "runs": args.runs,
        "summary": summary,
        "per_query": [
            {
                "query": r.query,
                "provider": r.provider,
                "latency_ms": r.latency_ms,
                "recall_at_10": r.recall_at_10,
                "error": r.error,
            }
            for r in results
        ],
        "config": {
            "qwen_url": cfg.qwen_url,
            "qwen_dims": cfg.qwen_dims,
            "gemini_model": cfg.gemini_model if cfg.gemini_key else None,
            "gemini_key_set": bool(cfg.gemini_key),
            "es_url": cfg.es_url,
            "es_dou_index": cfg.es_dou_index,
            "es_tcu_index": cfg.es_tcu_index,
            "char_limit": cfg.char_limit,
        },
    }

    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[embedding_poc] Wrote: {output_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
