"""Tests for pipeline embedding stage."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.worker.pipeline.embedder import run_embed
from src.backend.worker.registry import FileStatus


pytestmark = pytest.mark.asyncio


async def _setup_bm25_indexed_file(registry, filename="S01012026.zip", doc_count=2):
    file_id = await registry.insert_file(filename, "do1", "2026-01")
    await registry.update_status(file_id, FileStatus.QUEUED)
    await registry.update_status(file_id, FileStatus.DOWNLOADING)
    await registry.update_status(file_id, FileStatus.DOWNLOADED)
    await registry.update_status(file_id, FileStatus.EXTRACTING)
    await registry.update_status(file_id, FileStatus.EXTRACTED)
    await registry.update_status(file_id, FileStatus.BM25_INDEXING)
    await registry.update_status(file_id, FileStatus.BM25_INDEXED)
    await registry.update_file_fields(file_id, doc_count=doc_count)
    return file_id


async def test_embedder_updates_docs_and_transitions_to_embedded(registry):
    file_id = await _setup_bm25_indexed_file(registry)

    mapping_response = MagicMock()
    mapping_response.raise_for_status = MagicMock()

    search_response = MagicMock()
    search_response.raise_for_status = MagicMock()
    search_response.json.return_value = {
        "hits": {
            "hits": [
                {"_id": "doc-1", "_source": {"title": "Doc 1", "body": "Alpha", "source_zip": "S01012026.zip"}},
                {"_id": "doc-2", "_source": {"title": "Doc 2", "body": "Beta", "source_zip": "S01012026.zip"}},
            ]
        }
    }

    bulk_response = MagicMock()
    bulk_response.raise_for_status = MagicMock()
    bulk_response.json.return_value = {
        "items": [
            {"update": {"_id": "doc-1", "status": 200}},
            {"update": {"_id": "doc-2", "status": 200}},
        ]
    }

    async def mock_post(url, **kwargs):
        if url.endswith("/_search"):
            return search_response
        if url.endswith("/_bulk"):
            return bulk_response
        raise AssertionError(f"Unexpected POST url {url}")

    fake_embedder = SimpleNamespace(embed_batch=lambda texts: [[0.1, 0.2], [0.3, 0.4]])
    fake_cfg = SimpleNamespace(dim=2)

    with patch("src.backend.worker.pipeline.embedder.httpx.AsyncClient") as mock_client_cls, \
         patch("src.backend.worker.pipeline.embedder._resolve_embed_config", return_value=fake_cfg), \
         patch("src.backend.worker.pipeline.embedder._create_embedder", return_value=fake_embedder):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.put = AsyncMock(return_value=mapping_response)
        mock_client.post = AsyncMock(side_effect=mock_post)
        mock_client_cls.return_value = mock_client

        run_id = await registry.create_pipeline_run("embed")
        result = await run_embed(registry, run_id, "http://localhost:9200")

    assert result == {"embedded_files": 1, "embedded_docs": 2, "failed_files": 0}
    record = await registry.get_file(file_id)
    assert record["status"] == FileStatus.EMBEDDED.value


async def test_embedder_failure_transitions_to_embedding_failed(registry):
    file_id = await _setup_bm25_indexed_file(registry)

    mapping_response = MagicMock()
    mapping_response.raise_for_status = MagicMock()

    search_response = MagicMock()
    search_response.raise_for_status = MagicMock()
    search_response.json.return_value = {
        "hits": {"hits": [{"_id": "doc-1", "_source": {"title": "Doc 1", "body": "Alpha"}}]}
    }

    fake_embedder = SimpleNamespace(embed_batch=lambda texts: (_ for _ in ()).throw(RuntimeError("embed outage")))
    fake_cfg = SimpleNamespace(dim=2)

    async def mock_post(url, **kwargs):
        if url.endswith("/_search"):
            return search_response
        raise AssertionError(f"Unexpected POST url {url}")

    with patch("src.backend.worker.pipeline.embedder.httpx.AsyncClient") as mock_client_cls, \
         patch("src.backend.worker.pipeline.embedder._resolve_embed_config", return_value=fake_cfg), \
         patch("src.backend.worker.pipeline.embedder._create_embedder", return_value=fake_embedder):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.put = AsyncMock(return_value=mapping_response)
        mock_client.post = AsyncMock(side_effect=mock_post)
        mock_client_cls.return_value = mock_client

        run_id = await registry.create_pipeline_run("embed")
        result = await run_embed(registry, run_id, "http://localhost:9200")

    assert result["failed_files"] == 1
    record = await registry.get_file(file_id)
    assert record["status"] == FileStatus.EMBEDDING_FAILED.value
    assert "embed outage" in (record["error_message"] or "")


async def test_embedder_backfills_verified_files_without_embedded_at(registry):
    file_id = await _setup_bm25_indexed_file(registry, filename="legacy.zip", doc_count=1)
    await registry.update_status(file_id, FileStatus.EMBEDDING)
    await registry.update_status(file_id, FileStatus.EMBEDDED)
    await registry.update_status(file_id, FileStatus.VERIFYING)
    await registry.update_status(file_id, FileStatus.VERIFIED)
    await registry.update_file_fields(file_id, embedded_at=None)

    mapping_response = MagicMock()
    mapping_response.raise_for_status = MagicMock()

    search_response = MagicMock()
    search_response.raise_for_status = MagicMock()
    search_response.json.return_value = {
        "hits": {"hits": [{"_id": "legacy-doc", "_source": {"title": "Legacy", "body": "Body"}}]}
    }

    bulk_response = MagicMock()
    bulk_response.raise_for_status = MagicMock()
    bulk_response.json.return_value = {"items": [{"update": {"_id": "legacy-doc", "status": 200}}]}

    async def mock_post(url, **kwargs):
        if url.endswith("/_search"):
            return search_response
        if url.endswith("/_bulk"):
            return bulk_response
        raise AssertionError(f"Unexpected POST url {url}")

    fake_embedder = SimpleNamespace(embed_batch=lambda texts: [[0.1, 0.2]])
    fake_cfg = SimpleNamespace(dim=2)

    with patch("src.backend.worker.pipeline.embedder.httpx.AsyncClient") as mock_client_cls, \
         patch("src.backend.worker.pipeline.embedder._resolve_embed_config", return_value=fake_cfg), \
         patch("src.backend.worker.pipeline.embedder._create_embedder", return_value=fake_embedder):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.put = AsyncMock(return_value=mapping_response)
        mock_client.post = AsyncMock(side_effect=mock_post)
        mock_client_cls.return_value = mock_client

        run_id = await registry.create_pipeline_run("embed")
        result = await run_embed(registry, run_id, "http://localhost:9200")

    assert result["embedded_files"] == 1
    record = await registry.get_file(file_id)
    assert record["status"] == FileStatus.EMBEDDED.value
    assert record["embedded_at"] is not None
