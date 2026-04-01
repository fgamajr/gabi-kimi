from __future__ import annotations

import json
import ssl
import urllib.request
from functools import lru_cache
from typing import Protocol

from src.backend.repo_index.config import settings


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAICompatibleEmbeddingProvider:
    def __init__(self) -> None:
        self.api_key = settings.embedding_api_key or ""
        if not self.api_key:
            raise RuntimeError(
                "EMBED_API_KEY or OPENAI_API_KEY is required for embeddings"
            )

    def embed(self, texts: list[str]) -> list[list[float]]:
        payload: dict = {"input": texts, "model": settings.embedding_model}
        if settings.embedding_dims:
            payload["dimensions"] = settings.embedding_dims
        body = json.dumps(payload).encode("utf-8")
        url = f"{settings.embedding_base_url.rstrip('/')}/embeddings"
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        context = None
        if not settings.embedding_verify_tls:
            context = ssl._create_unverified_context()
        with urllib.request.urlopen(
            request, timeout=settings.embedding_timeout_sec, context=context
        ) as response:
            data = json.loads(response.read().decode("utf-8"))
        return [item["embedding"] for item in data["data"]]


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    return OpenAICompatibleEmbeddingProvider()
