"""MLX-based embedding server for Qwen3-Embedding-0.6B on Apple Silicon.

Runs on the Mac host, serves embeddings over HTTP to the VM.
Uses MLX (Metal-accelerated) for maximum throughput.

Usage:
    pip install mlx mlx-lm transformers fastapi uvicorn psutil numpy
    python server.py

Endpoint:
    POST /embed  {"texts": ["text1", "text2", ...], "dimensions": 384}
    GET  /health
"""

from __future__ import annotations

import asyncio
import gc
import importlib
import os
import time
import logging
from contextlib import asynccontextmanager
from typing import List, Optional, Tuple, Type

import numpy as np
import psutil
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="[embed-server] %(message)s")
logger = logging.getLogger(__name__)

# --- Config ---

MODEL_NAME = os.getenv("EMBED_MODEL", "mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ")
MAX_TOKEN_LENGTH = int(os.getenv("MAX_TOKEN_LENGTH", "512"))
MEM_LIMIT_PCT = float(os.getenv("MEM_LIMIT_PCT", "85"))
EMBED_DIM = int(os.getenv("EMBED_DIM", "384"))
GC_EVERY_N = int(os.getenv("GC_EVERY_N", "1"))  # force GC + metal cache clear every N requests
_model = None
_tokenizer = None
_requests_total = 0
_texts_total = 0
_errors_total = 0


# --- Memory monitoring ---


def _mem_info() -> dict:
    vm = psutil.virtual_memory()
    proc = psutil.Process()
    return {
        "system_mem_pct": round(vm.percent, 1),
        "system_mem_avail_gb": round(vm.available / (1024**3), 1),
        "system_mem_total_gb": round(vm.total / (1024**3), 1),
        "process_mem_gb": round(proc.memory_info().rss / (1024**3), 2),
    }


# --- MLX Model loading ---


def _get_embedding_classes(config: dict):
    """Subclass Qwen3 to return hidden states instead of logits."""
    import mlx.core as mx
    import mlx.nn as nn

    model_type = config.get("model_type", "").lower()
    qwen_module = importlib.import_module(f"mlx_lm.models.{model_type}")

    class Qwen3EmbeddingModel(qwen_module.Model):
        def __init__(self, args):
            super().__init__(args)
            if hasattr(self, "lm_head"):
                delattr(self, "lm_head")

        def __call__(
            self,
            inputs: mx.array,
            mask: Optional[mx.array] = None,
            cache=None,
        ) -> mx.array:
            return self.model(inputs, mask, cache)

    return Qwen3EmbeddingModel, qwen_module.ModelArgs


def load_model():
    """Load Qwen3-Embedding via MLX."""
    global _model, _tokenizer
    from mlx_lm.utils import _download, load_model as mlx_load_model
    from transformers import AutoTokenizer

    logger.info(f"Loading {MODEL_NAME} via MLX...")
    start = time.time()

    model_path = _download(MODEL_NAME)
    _model, _ = mlx_load_model(
        model_path=model_path,
        get_model_classes=_get_embedding_classes,
    )
    _tokenizer = AutoTokenizer.from_pretrained(str(model_path), trust_remote_code=True)

    elapsed = time.time() - start
    mem = _mem_info()
    logger.info(
        f"Model loaded in {elapsed:.1f}s | max_tokens={MAX_TOKEN_LENGTH} dim={EMBED_DIM} | "
        f"mem: {mem['process_mem_gb']}GB process, {mem['system_mem_pct']}% system"
    )


# --- Embedding ---


def embed_texts_sync(texts: list[str], dimensions: int = 384) -> list[list[float]]:
    """Embed texts using MLX. Runs synchronously."""
    import mlx.core as mx

    batch = _tokenizer(
        texts,
        max_length=MAX_TOKEN_LENGTH,
        padding=True,
        truncation=True,
        return_tensors="np",
    )
    input_ids = mx.array(batch["input_ids"])
    attention_mask = mx.array(batch["attention_mask"])

    # Forward pass → hidden states (batch, seq_len, hidden_dim)
    hidden_states = _model(input_ids)

    # Last-token pooling
    sequence_lengths = mx.sum(attention_mask, axis=1) - 1
    batch_size = hidden_states.shape[0]
    pooled = hidden_states[mx.arange(batch_size), sequence_lengths]

    # Matryoshka truncation
    pooled = pooled[:, :dimensions]

    # L2 normalization
    norm = mx.linalg.norm(pooled, ord=2, axis=-1, keepdims=True)
    normalized = pooled / mx.maximum(norm, mx.array(1e-9))

    mx.eval(normalized)
    result = np.array(normalized).tolist()

    # Aggressive cleanup: delete intermediate tensors, clear Metal cache
    del input_ids, attention_mask, hidden_states, pooled, norm, normalized, sequence_lengths
    if _requests_total % GC_EVERY_N == 0:
        try:
            mx.metal.clear_cache()
        except Exception:
            pass
        gc.collect()

    return result


# --- FastAPI app ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    yield

app = FastAPI(title="Qwen3 Embedding Server (MLX)", lifespan=lifespan)


class EmbedRequest(BaseModel):
    texts: list[str]
    dimensions: int = EMBED_DIM


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]
    count: int
    dimensions: int
    elapsed_ms: float
    mem_pct: float


@app.post("/embed", response_model=EmbedResponse)
async def embed(req: EmbedRequest):
    global _requests_total, _texts_total, _errors_total

    if not req.texts:
        raise HTTPException(400, "texts must not be empty")
    if len(req.texts) > 256:
        raise HTTPException(400, "max 256 texts per request")

    mem = _mem_info()
    if mem["system_mem_pct"] > MEM_LIMIT_PCT:
        _errors_total += 1
        gc.collect()
        logger.warning(f"MEMORY GUARD: {mem['system_mem_pct']}% > {MEM_LIMIT_PCT}% limit")
        raise HTTPException(503, f"Memory pressure: {mem['system_mem_pct']}%")

    start = time.time()
    embeddings = await asyncio.to_thread(embed_texts_sync, req.texts, req.dimensions)
    elapsed = (time.time() - start) * 1000

    _requests_total += 1
    _texts_total += len(req.texts)
    mem_after = _mem_info()

    logger.info(
        f"batch={len(req.texts)} dims={req.dimensions} "
        f"{elapsed:.0f}ms ({len(req.texts) / (elapsed / 1000):.0f} docs/sec) | "
        f"mem: {mem_after['system_mem_pct']}% sys, {mem_after['process_mem_gb']}GB proc"
    )

    return EmbedResponse(
        embeddings=embeddings,
        count=len(embeddings),
        dimensions=req.dimensions,
        elapsed_ms=round(elapsed, 1),
        mem_pct=mem_after["system_mem_pct"],
    )


@app.get("/health")
async def health():
    mem = _mem_info()
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "backend": "mlx",
        "loaded": _model is not None,
        "max_token_length": MAX_TOKEN_LENGTH,
        "embed_dim": EMBED_DIM,
        "mem_limit_pct": MEM_LIMIT_PCT,
        **mem,
        "stats": {
            "requests_total": _requests_total,
            "texts_total": _texts_total,
            "errors_total": _errors_total,
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8900)
