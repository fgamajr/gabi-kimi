"""Extractor pipeline module — unpacks DOU ZIP files with encoding detection.

Handles both 2002-2018 and 2019+ ZIP formats, detects encoding with chardet,
and provides ZIP Slip protection.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Any

import chardet

from src.backend.core.logging import bind_pipeline, get_logger
from src.backend.worker.registry import FileStatus, Registry

logger = get_logger(__name__)

DEFAULT_DOWNLOAD_DIR = "/data/tmp"
_XML_EXTENSIONS = frozenset({".xml"})


def _is_safe_path(base_dir: Path, entry_name: str) -> bool:
    """Validate ZIP entry path against ZIP Slip attacks.

    Rejects:
    - Absolute paths
    - Path components containing '..'
    """
    # Reject absolute paths
    if os.path.isabs(entry_name):
        return False

    # Reject path traversal
    parts = Path(entry_name).parts
    if ".." in parts:
        return False

    # Verify resolved path stays within base_dir
    resolved = (base_dir / entry_name).resolve()
    try:
        resolved.relative_to(base_dir.resolve())
    except ValueError:
        return False

    return True


def _detect_encoding(data: bytes) -> str:
    """Detect encoding of raw bytes using chardet.

    Falls back to latin-1 if confidence is low.
    """
    sample = data[:10240]  # First 10KB
    result = chardet.detect(sample)
    encoding = result.get("encoding") or "utf-8"
    confidence = result.get("confidence") or 0.0

    if confidence < 0.8:
        # Try latin-1 as fallback for low-confidence detections
        try:
            data.decode("latin-1")
            return "latin-1"
        except (UnicodeDecodeError, LookupError):
            pass

    return encoding


async def run_extract(
    registry: Registry,
    run_id: str,
    download_dir: str = DEFAULT_DOWNLOAD_DIR,
) -> dict[str, Any]:
    """Extract XML files from all DOWNLOADED ZIPs.

    Args:
        registry: SQLite registry instance
        run_id: Pipeline run identifier for logging
        download_dir: Directory containing downloaded ZIPs

    Returns:
        Stats dict: {"extracted": N, "failed": M, "total_xmls": K}
    """
    download_path = Path(download_dir)
    extract_base = download_path / "extract"
    extract_base.mkdir(parents=True, exist_ok=True)

    downloaded_files = await registry.get_files_by_status(FileStatus.DOWNLOADED)
    extracted = 0
    failed = 0
    total_xmls = 0

    for file_rec in downloaded_files:
        file_id = file_rec["id"]
        bind_pipeline(file_id=file_id)
        filename = file_rec["filename"]
        zip_path = download_path / filename
        stem = Path(filename).stem
        extract_dir = extract_base / stem

        # Transition to EXTRACTING
        await registry.update_status(file_id, FileStatus.EXTRACTING)

        try:
            if not zip_path.exists():
                raise FileNotFoundError(f"ZIP not found: {zip_path}")

            extract_dir.mkdir(parents=True, exist_ok=True)
            xml_count = 0

            with zipfile.ZipFile(zip_path, "r") as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue

                    entry_name = info.filename
                    suffix = Path(entry_name).suffix.lower()

                    # Only extract XML files
                    if suffix not in _XML_EXTENSIONS:
                        continue

                    # ZIP Slip protection
                    if not _is_safe_path(extract_dir, entry_name):
                        logger.warning("ZIP Slip rejected: %s in %s", entry_name, filename)
                        continue

                    # Extract to flat directory (use only the filename, not nested paths)
                    target_name = Path(entry_name).name
                    target_path = extract_dir / target_name

                    # Read raw bytes for encoding detection
                    raw_data = zf.read(info)

                    # Detect encoding and decode
                    encoding = _detect_encoding(raw_data)
                    try:
                        content = raw_data.decode(encoding)
                    except (UnicodeDecodeError, LookupError):
                        # Fallback: try latin-1
                        try:
                            content = raw_data.decode("latin-1")
                            encoding = "latin-1"
                        except UnicodeDecodeError:
                            logger.warning("Cannot decode %s in %s", entry_name, filename)
                            continue

                    # Write decoded content as UTF-8
                    target_path.write_text(content, encoding="utf-8")
                    xml_count += 1

            total_xmls += xml_count

            # Update registry
            await registry.update_file_fields(file_id, doc_count=xml_count)
            await registry.update_status(file_id, FileStatus.EXTRACTED)
            await registry.add_log_entry(run_id, file_id, "INFO", f"Extracted {xml_count} XMLs from {filename}")
            extracted += 1

        except Exception as e:
            error_msg = str(e)
            logger.error("Extraction failed for %s: %s", filename, error_msg)
            await registry.update_status(file_id, FileStatus.EXTRACT_FAILED)
            await registry.update_file_fields(file_id, error_message=error_msg)
            await registry.add_log_entry(run_id, file_id, "ERROR", f"Extraction failed for {filename}: {error_msg}")
            failed += 1

    return {"extracted": extracted, "failed": failed, "total_xmls": total_xmls}
