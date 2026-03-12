"""MLX-based embedding server for Qwen3-Embedding-0.6B on Apple Silicon.

Runs on the Mac host, serves embeddings over HTTP to the VM.

Usage:
    pip install mlx mlx-lm fastapi uvicorn transformers torch numpy
    python server.py

Endpoint:
    POST /embed  {"texts": ["text1", "text2", ...], "dimensions": 384}
    GET  /health
"""

from __future__ import annotations

import time
import logging
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="[embed-server] %(message)s")
logger = logging.getLogger(__name__)

# --- Model loading ---

MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"
_model = None
_tokenizer = None


def load_model():
    """Load Qwen3-Embedding-0.6B using transformers + MLX backend."""
    global _model, _tokenizer
    import torch
    from transformers import AutoTokenizer, AutoModel

    logger.info(f"Loading {MODEL_NAME}...")
    start = time.time()

    _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, padding_side="left")
    _model = AutoModel.from_pretrained(MODEL_NAME, torch_dtype=torch.float16)
    _model.eval()

    elapsed = time.time() - start
    logger.info(f"Model loaded in {elapsed:.1f}s")


def last_token_pool(last_hidden_states, attention_mask):
    """Extract last token embedding (Qwen3-Embedding pattern)."""
    import torch
    left_padding = attention_mask[:, -1].sum() == attention_mask.shape[0]
    if left_padding:
        return last_hidden_states[:, -1]
    sequence_lengths = attention_mask.sum(dim=1) - 1
    batch_size = last_hidden_states.shape[0]
    return last_hidden_states[
        torch.arange(batch_size, device=last_hidden_states.device),
        sequence_lengths,
    ]


def embed_texts(texts: list[str], dimensions: int = 384) -> list[list[float]]:
    """Embed texts and return normalized vectors at requested dimensionality."""
    import torch
    import torch.nn.functional as F

    batch_dict = _tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=8192,
        return_tensors="pt",
    )
    batch_dict = {k: v.to(_model.device) for k, v in batch_dict.items()}

    with torch.no_grad():
        outputs = _model(**batch_dict)
        embeddings = last_token_pool(outputs.last_hidden_state, batch_dict["attention_mask"])

        # MRL: truncate to requested dimensions
        if dimensions < embeddings.shape[1]:
            embeddings = embeddings[:, :dimensions]

        # L2 normalize
        embeddings = F.normalize(embeddings, p=2, dim=1)

    return embeddings.cpu().float().numpy().tolist()


# --- FastAPI app ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    yield

app = FastAPI(title="Qwen3 Embedding Server", lifespan=lifespan)


class EmbedRequest(BaseModel):
    texts: list[str]
    dimensions: int = 384


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]
    count: int
    dimensions: int
    elapsed_ms: float


@app.post("/embed", response_model=EmbedResponse)
async def embed(req: EmbedRequest):
    if not req.texts:
        raise HTTPException(400, "texts must not be empty")
    if len(req.texts) > 256:
        raise HTTPException(400, "max 256 texts per request")

    start = time.time()
    embeddings = embed_texts(req.texts, req.dimensions)
    elapsed = (time.time() - start) * 1000

    logger.info(f"Embedded {len(req.texts)} texts in {elapsed:.0f}ms ({len(req.texts) / (elapsed / 1000):.0f} docs/sec)")

    return EmbedResponse(
        embeddings=embeddings,
        count=len(embeddings),
        dimensions=req.dimensions,
        elapsed_ms=round(elapsed, 1),
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "loaded": _model is not None,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8900)
