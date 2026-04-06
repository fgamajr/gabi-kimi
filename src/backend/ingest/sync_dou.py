#!/usr/bin/env python3
"""
GABI DOU Sync Script (v3.0)
---------------------------
Orchestrator for downloading and ingesting DOU data into Postgres.
"""

import sys
import os
import json
import shutil
import logging
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import psycopg

from src.backend.core.config import settings
from src.backend.ingest.downloader import DouDownloader
from src.backend.ingest.dou_processor import DouProcessor
from src.backend.data.models.document import DouDocument

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _pg_url() -> str:
    return os.getenv("POSTGRES_URL", settings.POSTGRES_URL)


def _raw_cache_roots() -> list[Path]:
    roots: list[Path] = []
    raw_cache_path = (settings.RAW_CACHE_PATH or "").strip()
    if raw_cache_path:
        roots.append(Path(raw_cache_path))
    if settings.ICLOUD_DATA_PATH:
        roots.append(Path(settings.ICLOUD_DATA_PATH) / "raw")
    return roots


def _cached_zip_path(zip_filename: str) -> Path | None:
    for root in _raw_cache_roots():
        candidate = root / zip_filename
        if candidate.exists():
            return candidate
    return None


def _cache_destination(zip_filename: str) -> Path:
    roots = _raw_cache_roots()
    if roots:
        return roots[0] / zip_filename
    return Path(settings.PIPELINE_TMP) / "raw" / zip_filename


def _ensure_disk_space(target_path: Path) -> None:
    disk_target = target_path if target_path.is_dir() else target_path.parent
    disk_target.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(disk_target).free / (1024**3)
    if free_gb < 2:
        raise RuntimeError(
            f"Low disk space in pipeline workspace: {free_gb:.1f}GB free at {disk_target}"
        )


def ingest_documents(documents: List[DouDocument]) -> None:
    """Bulk upsert documents to Postgres (raw.dou_documents_raw).

    Uses ON CONFLICT (id) DO NOTHING — the id IS the MD5 of content_html,
    so if a row with the same id exists the content is identical.
    """
    if not documents:
        return

    tuples: list[tuple] = []
    for doc in documents:
        doc_dict = doc.model_dump(by_alias=True, exclude_none=True)
        doc_dict.setdefault("embedding_status", "pending")
        doc_dict.setdefault("embedding_attempts", 0)
        all_fields_json = json.dumps(doc_dict, default=str, ensure_ascii=False)
        tuples.append((doc.id, all_fields_json))

    try:
        with psycopg.connect(_pg_url()) as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO raw.dou_documents_raw (id, all_fields, source_type, dumped_at)
                       VALUES (%s, %s::jsonb, 'dou_documents', NOW())
                       ON CONFLICT (id) DO NOTHING""",
                    tuples,
                )
            conn.commit()
        logger.info(
            "Upserted %s documents into Postgres (skipped existing)", len(documents)
        )
    except Exception as e:
        logger.error("Postgres bulk write failed: %s", e)
        raise


def _cleanup_extracted(extract_base: str | None, zip_filename: str) -> None:
    if not extract_base or not zip_filename:
        return
    zip_name_no_ext = os.path.splitext(zip_filename)[0]
    target_dir = os.path.join(extract_base, zip_name_no_ext)
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir, ignore_errors=True)
        logger.info(f"Cleaned extracted XMLs: {target_dir}")


def _process_zip_file(
    folder_id: str, filename: str, *, extract_xmls: bool
) -> tuple[str, int, bool]:
    downloader = DouDownloader()
    processor = DouProcessor()
    extract_to = (
        os.path.join(settings.PIPELINE_TMP, "extracted") if extract_xmls else None
    )

    cached_zip = _cached_zip_path(filename)
    if cached_zip is not None:
        logger.info("Using cached ZIP %s", cached_zip)
        zip_content = cached_zip.read_bytes()
        from_cache = True
    else:
        save_path = _cache_destination(filename)
        _ensure_disk_space(save_path)
        logger.info(f"Downloading {filename}...")
        zip_content = downloader.download_file(
            str(folder_id), filename, save_path=str(save_path)
        )
        if not zip_content:
            raise RuntimeError(f"Failed to download {filename}")
        from_cache = False

    logger.info(f"Processing {filename}...")
    documents = processor.process_zip(zip_content, filename, extract_to=extract_to)
    logger.info(f"Extracted {len(documents)} documents from {filename}")
    ingest_documents(documents)
    _cleanup_extracted(extract_to, filename)
    return filename, len(documents), from_cache


def _process_month(
    folder_id: str, files: list[str], *, extract_xmls: bool, parallelism: int
) -> dict[str, int]:
    zip_files = [filename for filename in files if filename.lower().endswith(".zip")]
    if not zip_files:
        return {"zip_count": 0, "doc_count": 0, "cache_hits": 0}

    workers = max(1, min(parallelism, len(zip_files)))
    if workers == 1:
        total_docs = 0
        cache_hits = 0
        for filename in zip_files:
            _, doc_count, from_cache = _process_zip_file(
                folder_id, filename, extract_xmls=extract_xmls
            )
            total_docs += doc_count
            cache_hits += 1 if from_cache else 0
        return {
            "zip_count": len(zip_files),
            "doc_count": total_docs,
            "cache_hits": cache_hits,
        }

    failures: list[str] = []
    total_docs = 0
    cache_hits = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _process_zip_file, folder_id, filename, extract_xmls=extract_xmls
            ): filename
            for filename in zip_files
        }
        for future in as_completed(futures):
            filename = futures[future]
            try:
                processed_filename, doc_count, from_cache = future.result()
                total_docs += doc_count
                cache_hits += 1 if from_cache else 0
                logger.info(
                    "Completed %s docs=%s source=%s",
                    processed_filename,
                    doc_count,
                    "cache" if from_cache else "download",
                )
            except Exception as exc:
                logger.error("ZIP processing failed for %s: %s", filename, exc)
                failures.append(filename)

    if failures:
        raise RuntimeError(f"Failed ZIPs for month: {', '.join(sorted(failures))}")
    return {
        "zip_count": len(zip_files),
        "doc_count": total_docs,
        "cache_hits": cache_hits,
    }


def sync_month(
    year: int, month: int, *, extract_xmls: bool, parallelism: int
) -> dict[str, int]:
    downloader = DouDownloader()
    logger.info("Processing %s-%02d...", year, month)
    data = downloader.get_month_data(year, month)
    if not data:
        current_utc = datetime.now(timezone.utc)
        if year == current_utc.year and month == current_utc.month:
            logger.info("Falling back to INLABS for current month %s-%02d", year, month)
            from src.backend.ingest.inlabs_daily import ingest_month_to_date

            result = ingest_month_to_date(year, month)
            return {
                "zip_count": int(result["zip_count"]),
                "doc_count": int(result["processed_docs"]),
                "cache_hits": 0,
            }
        logger.warning("No data found for %s-%02d", year, month)
        return {"zip_count": 0, "doc_count": 0, "cache_hits": 0}

    folder_id = data["folder_id"]
    files = data["files"]
    logger.info("Found %s files for %s-%02d", len(files), year, month)
    return _process_month(
        str(folder_id),
        files,
        extract_xmls=extract_xmls,
        parallelism=parallelism,
    )


def main():
    parser = argparse.ArgumentParser(description="GABI DOU Sync")
    parser.add_argument("--year", type=int, default=2002, help="Year to sync")
    parser.add_argument("--month", type=int, help="Specific month to sync (optional)")
    parser.add_argument(
        "--skip-es-sync",
        action="store_true",
        help="Skip incremental ES sync at the end of the run",
    )
    parser.add_argument(
        "--extract-xmls",
        action="store_true",
        help="Extract XMLs to disk while processing ZIPs",
    )
    parser.add_argument(
        "--parallelism",
        type=int,
        default=settings.DOU_INGEST_PARALLELISM,
        help="Number of ZIP files to process in parallel per month",
    )
    args = parser.parse_args()

    logger.info(f"Starting GABI DOU Sync for {args.year}")

    # Determine months to process
    months = [args.month] if args.month else range(1, 13)

    for month in months:
        sync_month(
            args.year,
            month,
            extract_xmls=args.extract_xmls,
            parallelism=args.parallelism,
        )

    logger.info("Sync complete. ES sync must be triggered separately.")


if __name__ == "__main__":
    main()
