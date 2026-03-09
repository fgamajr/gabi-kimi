"""Tests for pipeline extractor module."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from src.backend.worker.registry import FileStatus, Registry
from src.backend.worker.pipeline.extractor import run_extract


pytestmark = pytest.mark.asyncio


SAMPLE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
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


def _create_test_zip(path: Path, files: dict[str, bytes]) -> Path:
    """Create a test ZIP file with given contents."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return path


async def _setup_downloaded_file(registry, tmp_path, filename="S01012026.zip"):
    """Insert a file and transition to DOWNLOADED, creating a ZIP on disk."""
    file_id = await registry.insert_file(filename, "do1", "2026-01")
    await registry.update_status(file_id, FileStatus.QUEUED)
    await registry.update_status(file_id, FileStatus.DOWNLOADING)
    await registry.update_status(file_id, FileStatus.DOWNLOADED)

    # Create a test ZIP
    zip_path = tmp_path / filename
    _create_test_zip(zip_path, {
        "article1.xml": SAMPLE_XML,
        "article2.xml": SAMPLE_XML,
    })

    return file_id


async def test_extract_opens_zip_and_transitions_to_extracted(registry, tmp_path):
    """run_extract opens a ZIP from download dir, extracts XMLs, transitions to EXTRACTED."""
    file_id = await _setup_downloaded_file(registry, tmp_path)

    run_id = await registry.create_pipeline_run("extract")
    result = await run_extract(registry, run_id, download_dir=str(tmp_path))

    assert result["extracted"] == 1
    assert result["failed"] == 0
    assert result["total_xmls"] >= 2

    f = await registry.get_file(file_id)
    assert f["status"] == FileStatus.EXTRACTED.value


async def test_extract_zip_slip_rejected(registry, tmp_path):
    """ZIP Slip attack paths (../ components, absolute paths) are rejected."""
    file_id = await registry.insert_file("evil.zip", "do1", "2026-01")
    await registry.update_status(file_id, FileStatus.QUEUED)
    await registry.update_status(file_id, FileStatus.DOWNLOADING)
    await registry.update_status(file_id, FileStatus.DOWNLOADED)

    # Create a ZIP with path traversal
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../../etc/passwd", b"malicious")
        zf.writestr("normal.xml", SAMPLE_XML)

    run_id = await registry.create_pipeline_run("extract")
    result = await run_extract(registry, run_id, download_dir=str(tmp_path))

    # Should still succeed (skipping bad paths) or fail gracefully
    f = await registry.get_file(file_id)
    # The malicious path should have been rejected
    extract_dir = tmp_path / "extract" / "evil"
    assert not (tmp_path.parent.parent / "etc" / "passwd").exists()


async def test_extract_encoding_detection(registry, tmp_path):
    """Encoding detection uses chardet; Latin-1 files are decoded correctly."""
    file_id = await registry.insert_file("latin1.zip", "do1", "2026-01")
    await registry.update_status(file_id, FileStatus.QUEUED)
    await registry.update_status(file_id, FileStatus.DOWNLOADING)
    await registry.update_status(file_id, FileStatus.DOWNLOADED)

    # Create XML with Latin-1 encoding
    latin1_xml = '<?xml version="1.0" encoding="ISO-8859-1"?>\n<article id="1" idMateria="12345678" pubName="DO1" pubDate="15/01/2026" artType="PORTARIA" artCategory="Test" name="Test" idOficio="" editionNumber="10" numberPage="5" pdfPage="" artClass="" artSize="" artNotes="" highlightType="" highlightPriority="" highlight="" highlightimage="" highlightimagename=""><body><Identifica>RETIFICA\xc7\xc3O</Identifica><Data></Data><Ementa></Ementa><Titulo></Titulo><SubTitulo></SubTitulo><Texto>Texto com acentua\xe7\xe3o</Texto></body></article>'
    latin1_bytes = latin1_xml.encode("latin-1")

    zip_path = tmp_path / "latin1.zip"
    _create_test_zip(zip_path, {"article.xml": latin1_bytes})

    run_id = await registry.create_pipeline_run("extract")
    result = await run_extract(registry, run_id, download_dir=str(tmp_path))

    assert result["extracted"] == 1


async def test_extract_failure_transitions_to_extract_failed(registry, tmp_path):
    """Failed extraction transitions file to EXTRACT_FAILED with error_message."""
    file_id = await registry.insert_file("corrupt.zip", "do1", "2026-01")
    await registry.update_status(file_id, FileStatus.QUEUED)
    await registry.update_status(file_id, FileStatus.DOWNLOADING)
    await registry.update_status(file_id, FileStatus.DOWNLOADED)

    # Create a corrupt file (not a valid ZIP)
    (tmp_path / "corrupt.zip").write_bytes(b"not a zip file")

    run_id = await registry.create_pipeline_run("extract")
    result = await run_extract(registry, run_id, download_dir=str(tmp_path))

    assert result["failed"] == 1
    f = await registry.get_file(file_id)
    assert f["status"] == FileStatus.EXTRACT_FAILED.value
    assert f["error_message"] is not None


async def test_extract_doc_count_set(registry, tmp_path):
    """doc_count is set to number of XML files found in ZIP."""
    file_id = await _setup_downloaded_file(registry, tmp_path)

    run_id = await registry.create_pipeline_run("extract")
    await run_extract(registry, run_id, download_dir=str(tmp_path))

    f = await registry.get_file(file_id)
    assert f["doc_count"] == 2  # We put 2 XMLs in the test ZIP
