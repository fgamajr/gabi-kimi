"""Tests for pipeline ingestor module."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from src.backend.worker.registry import FileStatus, Registry
from src.backend.worker.pipeline.ingestor import run_ingest, BULK_BATCH_SIZE


pytestmark = pytest.mark.asyncio


SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<article id="1" idMateria="12345678" pubName="DO1" pubDate="15/01/2026"
         artType="PORTARIA" artCategory="Ministerio/Saude" name="Test"
         idOficio="" editionNumber="10" numberPage="5" pdfPage=""
         artClass="" artSize="" artNotes="" highlightType="" highlightPriority=""
         highlight="" highlightimage="" highlightimagename="">
  <body>
    <Identifica>PORTARIA No 123</Identifica>
    <Data></Data>
    <Ementa>Test ementa</Ementa>
    <Titulo></Titulo>
    <SubTitulo></SubTitulo>
    <Texto>Test body text</Texto>
  </body>
</article>
"""


async def _setup_extracted_file(registry, tmp_path, filename="S01012026.zip"):
    """Insert file, transition to EXTRACTED, create extracted XMLs on disk."""
    file_id = await registry.insert_file(filename, "do1", "2026-01")
    await registry.update_status(file_id, FileStatus.QUEUED)
    await registry.update_status(file_id, FileStatus.DOWNLOADING)
    await registry.update_status(file_id, FileStatus.DOWNLOADED)
    await registry.update_status(file_id, FileStatus.EXTRACTING)
    await registry.update_status(file_id, FileStatus.EXTRACTED)
    await registry.update_file_fields(file_id, doc_count=2)

    # Create extracted XML files
    extract_dir = tmp_path / "extract" / "S01012026"
    extract_dir.mkdir(parents=True, exist_ok=True)
    (extract_dir / "article1.xml").write_text(SAMPLE_XML, encoding="utf-8")
    (extract_dir / "article2.xml").write_text(SAMPLE_XML, encoding="utf-8")

    return file_id


async def test_ingest_parses_and_indexes(registry, tmp_path):
    """run_ingest parses extracted XMLs and bulk-indexes to ES."""
    file_id = await _setup_extracted_file(registry, tmp_path)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "errors": False,
        "items": [
            {"index": {"_id": "doc1", "status": 201, "result": "created"}},
            {"index": {"_id": "doc2", "status": 201, "result": "created"}},
        ],
    }
    mock_response.raise_for_status = MagicMock()

    with patch("src.backend.worker.pipeline.ingestor.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        run_id = await registry.create_pipeline_run("ingest")
        result = await run_ingest(registry, run_id, "http://localhost:9200", extract_dir=str(tmp_path / "extract"))

    assert result["ingested_files"] == 1
    assert result["ingested_docs"] >= 2

    f = await registry.get_file(file_id)
    assert f["status"] == FileStatus.INGESTED.value


async def test_ingest_deterministic_doc_id(registry, tmp_path):
    """Deterministic doc_id is generated from natural_key_hash."""
    from src.backend.worker.pipeline.ingestor import _compute_doc_id
    from src.backend.ingest.xml_parser import INLabsXMLParser

    parser = INLabsXMLParser()
    article = parser.parse_string(SAMPLE_XML)

    doc_id_1 = _compute_doc_id(article)
    doc_id_2 = _compute_doc_id(article)
    assert doc_id_1 == doc_id_2
    assert len(doc_id_1) == 64  # SHA-256 hex


async def test_ingest_failure_transitions_to_ingest_failed(registry, tmp_path):
    """Failed ingest transitions file to INGEST_FAILED with error_message."""
    file_id = await _setup_extracted_file(registry, tmp_path)

    with patch("src.backend.worker.pipeline.ingestor.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("ES connection refused"))
        mock_client_cls.return_value = mock_client

        run_id = await registry.create_pipeline_run("ingest")
        result = await run_ingest(registry, run_id, "http://localhost:9200", extract_dir=str(tmp_path / "extract"))

    assert result["failed_files"] >= 1
    f = await registry.get_file(file_id)
    assert f["status"] == FileStatus.INGEST_FAILED.value
    assert f["error_message"] is not None


async def test_ingest_bulk_batch_size():
    """Bulk batch size is 300 documents."""
    assert BULK_BATCH_SIZE == 300


async def test_ingest_no_psycopg2_imports():
    """No psycopg2 imports (PostgreSQL bypassed)."""
    import importlib
    import src.backend.worker.pipeline.ingestor as mod

    source = Path(mod.__file__).read_text()
    assert "psycopg2" not in source
    assert "psycopg" not in source
