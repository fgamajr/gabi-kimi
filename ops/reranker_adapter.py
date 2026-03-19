"""HTTP adapter that exposes /v1/rerank and proxies to Docker Model Runner."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="[reranker-adapter] %(message)s")
logger = logging.getLogger(__name__)

MODEL_NAME = os.getenv("RERANKER_MODEL", "ai/qwen3-reranker-vllm:0.6B")
UPSTREAM_URL = os.getenv(
    "RERANKER_UPSTREAM_URL",
    "http://host.docker.internal:8080/engines/vllm/rerank",
)
UPSTREAM_TIMEOUT = float(os.getenv("RERANKER_UPSTREAM_TIMEOUT", "1.5"))
MAX_DOCS = int(os.getenv("RERANKER_MAX_DOCS", "50"))
MAX_DOC_CHARS = int(os.getenv("RERANKER_MAX_DOC_CHARS", "2200"))
MAX_CONCURRENCY = int(os.getenv("RERANKER_MAX_CONCURRENCY", "2"))
HOST = os.getenv("RERANKER_BIND_HOST", "0.0.0.0")
PORT = int(os.getenv("RERANKER_PORT", "8902"))

_semaphore = asyncio.Semaphore(MAX_CONCURRENCY)


class RerankRequest(BaseModel):
    query: str
    documents: list[str]
    top_n: int | None = None


class RerankResponse(BaseModel):
    results: list[dict[str, Any]]
    elapsed_ms: float
    model: str


def _normalize_document(text: str) -> str:
    compact = " ".join(text.split())
    return compact[:MAX_DOC_CHARS]


def _parse_upstream_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = payload.get("results")
    if not isinstance(raw_items, list):
        raw_items = payload.get("data")
    if not isinstance(raw_items, list):
        return []

    results: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        score = item.get("relevance_score")
        if score is None:
            score = item.get("score")
        if not isinstance(idx, int) or score is None:
            continue
        results.append(
            {
                "index": idx,
                "relevance_score": float(score),
            }
        )
    return results


app = FastAPI(title="GABI Qwen Reranker Adapter")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "upstream_url": UPSTREAM_URL,
        "max_docs": MAX_DOCS,
        "max_doc_chars": MAX_DOC_CHARS,
        "max_concurrency": MAX_CONCURRENCY,
    }


@app.post("/v1/rerank", response_model=RerankResponse)
async def rerank(req: RerankRequest) -> RerankResponse:
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")
    if not req.documents:
        raise HTTPException(status_code=400, detail="documents must not be empty")

    limited_docs = [_normalize_document(doc) for doc in req.documents[:MAX_DOCS]]
    top_n = min(req.top_n or len(limited_docs), len(limited_docs))
    payload = {
        "model": MODEL_NAME,
        "query": req.query.strip(),
        "documents": limited_docs,
    }

    started = time.perf_counter()
    async with _semaphore:
        try:
            async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT) as client:
                response = await client.post(UPSTREAM_URL, json=payload)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise HTTPException(status_code=504, detail="reranker upstream timeout") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"reranker upstream error: {exc}") from exc

    upstream_payload = response.json()
    results = _parse_upstream_results(upstream_payload)
    if not results:
        raise HTTPException(status_code=502, detail="reranker upstream returned no usable scores")

    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    logger.info("rerank docs=%d top_n=%d elapsed_ms=%s", len(limited_docs), top_n, elapsed_ms)

    return RerankResponse(
        results=results[:top_n],
        elapsed_ms=elapsed_ms,
        model=MODEL_NAME,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
