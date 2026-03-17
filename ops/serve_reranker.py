"""MLX-based reranker server for Qwen3-Reranker-0.6B on Apple Silicon.

Runs on the Mac host, serves reranking over HTTP to Docker containers.
Uses sentence-transformers CrossEncoder with MPS acceleration.

Usage:
    pip install -r requirements-reranker.txt
    python serve_reranker.py

Endpoints:
    POST /v1/rerank  {"query": "...", "documents": ["..."], "top_n": 10}
    GET  /health
"""

from __future__ import annotations

import asyncio
import gc
import os
import time
import logging
from contextlib import asynccontextmanager
from typing import Optional

import psutil
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sentence_transformers import CrossEncoder

logging.basicConfig(level=logging.INFO, format="[reranker] %(message)s")
logger = logging.getLogger(__name__)

# --- Config ---

MODEL_NAME = os.getenv("RERANKER_MODEL", "Qwen/Qwen3-Reranker-0.6B")
DEVICE = os.getenv("RERANKER_DEVICE", "mps" if torch.backends.mps.is_available() else "cpu")
MAX_LENGTH = int(os.getenv("RERANKER_MAX_LENGTH", "512"))

_model: CrossEncoder | None = None
_requests_total = 0
_docs_total = 0


# --- Memory monitoring ---

def _mem_info() -> dict:
    vm = psutil.virtual_memory()
    proc = psutil.Process()
    return {
        "system_mem_pct": round(vm.percent, 1),
        "system_mem_avail_gb": round(vm.available / (1024**3), 1),
        "process_mem_gb": round(proc.memory_info().rss / (1024**3), 2),
    }


# --- Model loading ---

def load_model():
    global _model
    logger.info(f"Loading {MODEL_NAME} on {DEVICE}...")
    start = time.time()

    _model = CrossEncoder(
        MODEL_NAME,
        device=DEVICE,
        max_length=MAX_LENGTH,
        trust_remote_code=True,
    )

    elapsed = time.time() - start
    mem = _mem_info()
    logger.info(
        f"Model loaded in {elapsed:.1f}s | device={DEVICE} max_length={MAX_LENGTH} | "
        f"mem: {mem['process_mem_gb']}GB process, {mem['system_mem_pct']}% system"
    )


# --- Reranking ---

def rerank_sync(query: str, documents: list[str], top_n: int | None = None) -> list[dict]:
    """Score query-document pairs and return sorted results."""
    if not documents:
        return []

    pairs = [[query, doc] for doc in documents]
    scores = _model.predict(pairs)

    results = []
    for i, score in enumerate(scores):
        results.append({
            "index": i,
            "relevance_score": float(score),
            "document": {"text": documents[i]},
        })

    results.sort(key=lambda x: x["relevance_score"], reverse=True)

    if top_n is not None and top_n > 0:
        results = results[:top_n]

    return results


# --- FastAPI app ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    yield


app = FastAPI(title="Qwen3 Reranker Server", lifespan=lifespan)


class RerankRequest(BaseModel):
    query: str
    documents: list[str]
    top_n: Optional[int] = None


class RerankResult(BaseModel):
    index: int
    relevance_score: float
    document: dict


class RerankResponse(BaseModel):
    results: list[RerankResult]
    elapsed_ms: float


@app.post("/v1/rerank", response_model=RerankResponse)
async def rerank(req: RerankRequest):
    global _requests_total, _docs_total

    if not req.query:
        raise HTTPException(400, "query must not be empty")
    if not req.documents:
        raise HTTPException(400, "documents must not be empty")
    if len(req.documents) > 500:
        raise HTTPException(400, "max 500 documents per request")

    start = time.time()
    results = await asyncio.to_thread(rerank_sync, req.query, req.documents, req.top_n)
    elapsed = (time.time() - start) * 1000

    _requests_total += 1
    _docs_total += len(req.documents)

    logger.info(
        f"rerank docs={len(req.documents)} top_n={req.top_n} "
        f"{elapsed:.0f}ms | mem: {_mem_info()['system_mem_pct']}%"
    )

    return RerankResponse(results=results, elapsed_ms=round(elapsed, 1))


@app.get("/health")
async def health():
    mem = _mem_info()
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "device": DEVICE,
        "loaded": _model is not None,
        "max_length": MAX_LENGTH,
        **mem,
        "stats": {
            "requests_total": _requests_total,
            "docs_total": _docs_total,
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8902)
