"""Mock TEI (Text Embeddings Inference) server for local pipeline testing.

Returns deterministic 384-dim vectors so all pipeline phases can run
without the real HuggingFace TEI container.

Usage:
    python mock_tei.py          # Starts on port 8080
    MOCK_TEI_PORT=9090 python mock_tei.py  # Custom port
"""

import hashlib
import math
import os
import struct
from typing import List

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Mock TEI", version="0.1.0")

DIMENSIONS = 384


class EmbedRequest(BaseModel):
    inputs: str | list[str]
    truncate: bool = True


class HealthResponse(BaseModel):
    status: str = "ok"
    model_id: str = "mock/paraphrase-multilingual-MiniLM-L12-v2"


def _deterministic_vector(text: str) -> List[float]:
    """Generate a deterministic 384-dim unit vector from text hash."""
    digest = hashlib.sha512(text.encode("utf-8")).digest()
    # Expand hash to fill 384 floats
    raw = digest * (DIMENSIONS // len(digest) + 1)
    values = [b / 255.0 for b in raw[:DIMENSIONS]]
    # Normalize to unit vector
    norm = math.sqrt(sum(v * v for v in values))
    if norm > 0:
        values = [v / norm for v in values]
    return values


@app.get("/health")
async def health():
    return HealthResponse()


@app.post("/embed")
async def embed(request: EmbedRequest):
    """TEI-compatible /embed endpoint."""
    inputs = request.inputs if isinstance(request.inputs, list) else [request.inputs]
    embeddings = [_deterministic_vector(text) for text in inputs]
    return embeddings


@app.post("/v1/embeddings")
async def openai_embeddings(request: EmbedRequest):
    """OpenAI-compatible endpoint (fallback)."""
    inputs = request.inputs if isinstance(request.inputs, list) else [request.inputs]
    data = []
    for i, text in enumerate(inputs):
        data.append({
            "object": "embedding",
            "index": i,
            "embedding": _deterministic_vector(text),
        })
    return {
        "object": "list",
        "data": data,
        "model": "mock/paraphrase-multilingual-MiniLM-L12-v2",
        "usage": {"prompt_tokens": sum(len(t.split()) for t in inputs), "total_tokens": sum(len(t.split()) for t in inputs)},
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("MOCK_TEI_PORT", "8080"))
    print(f"🚀 Mock TEI server starting on port {port} (384-dim vectors)")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
