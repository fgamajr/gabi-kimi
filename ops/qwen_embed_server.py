#!/usr/bin/env python3
"""Minimal OpenAI-compatible embedding server for Qwen3-Embedding-0.6B.

POST /v1/embeddings  {"input": [...], "model": "qwen3-embedding", "dimensions": 384}
GET  /health         → {"status": "ok"}
"""

from __future__ import annotations

import os
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

MODEL_ID = os.getenv("QWEN_MODEL_ID", "Qwen/Qwen3-Embedding-0.6B")
SERVED_MODEL_NAME = os.getenv("QWEN_SERVED_MODEL_NAME", "qwen3-embedding")
PORT = int(os.getenv("QWEN_PORT", "8900"))
HF_HOME = os.getenv("HF_HOME", "/app/hf_cache")

os.environ["HF_HOME"] = HF_HOME

print(f"[qwen-embed] Loading {MODEL_ID} ...", flush=True)
_t0 = time.perf_counter()
_model = SentenceTransformer(MODEL_ID, trust_remote_code=True)
print(f"[qwen-embed] Model ready in {time.perf_counter() - _t0:.1f}s", flush=True)

app = FastAPI(title="qwen-embed")


class EmbedRequest(BaseModel):
    input: list[str] | str
    model: str = SERVED_MODEL_NAME
    dimensions: int | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/embeddings")
def embeddings(req: EmbedRequest) -> Any:
    texts = [req.input] if isinstance(req.input, str) else req.input
    if not texts:
        raise HTTPException(status_code=422, detail="input must be non-empty")

    vecs = _model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

    # Matryoshka truncation when dimensions requested
    if req.dimensions and req.dimensions < vecs.shape[1]:
        vecs = vecs[:, : req.dimensions]

    data = [
        {"object": "embedding", "index": i, "embedding": vecs[i].tolist()}
        for i in range(len(vecs))
    ]
    return JSONResponse(
        {
            "object": "list",
            "model": SERVED_MODEL_NAME,
            "data": data,
            "usage": {
                "prompt_tokens": sum(len(t.split()) for t in texts),
                "total_tokens": 0,
            },
        }
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
