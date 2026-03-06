"""Bulk ingestion pipeline for DOU publications.

Orchestrates the complete flow:
  discover → download → extract → parse → normalize → ingest → seal

Usage:
    # Ingest last 7 days (download + parse + ingest + seal)
    python -m src.backend.ingest.bulk_pipeline --days 7

    # Ingest specific date range
    python -m src.backend.ingest.bulk_pipeline --start 2026-02-20 --end 2026-02-27

    # Download only (no DB ingestion)
    python -m src.backend.ingest.bulk_pipeline --days 7 --download-only

    # Parse already-downloaded ZIPs (no download, no DB)
    python -m src.backend.ingest.bulk_pipeline --parse-only --data-dir ops/data/inlabs

    # Full pipeline with sealing
    python -m src.backend.ingest.bulk_pipeline --start 2026-02-20 --end 2026-02-27 --seal

    # Ingest from already-downloaded ZIPs (skip download)
    python -m src.backend.ingest.bulk_pipeline --start 2026-02-20 --end 2026-02-27 --skip-download
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src.backend.ingest.date_selector import DateRange
from src.backend.ingest.normalizer import article_to_ingest_record
from src.backend.ingest.xml_parser import INLabsXMLParser, DOUArticle, parse_directory
from src.backend.ingest.zip_downloader import (
    ALL_SECTIONS,
    DownloadManifest,
    ExtractionResult,
    ZIPTarget,
    build_targets,
    build_zip_url,
    download_batch,
    extract_xml_from_zip,
    file_sha256,
    write_manifest,
)


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PipelineResult:
    """Aggregate result of a full pipeline run."""
    # Download phase
    zips_targeted: int = 0
    zips_downloaded: int = 0
    zips_failed: int = 0
    download_bytes: int = 0

    # Extraction phase
    xml_files_extracted: int = 0
    image_files_extracted: int = 0
    extraction_errors: list[str] = field(default_factory=list)

    # Parse phase
    articles_parsed: int = 0
    articles_skipped: int = 0

    # Normalization phase
    records_produced: int = 0

    # Ingestion phase
    records_ingested: int = 0
    records_duplicate: int = 0
    records_new_version: int = 0
    records_new_publication: int = 0
    ingestion_errors: list[str] = field(default_factory=list)

    # Commitment phase
    commitment_root: str | None = None
    commitment_sealed: bool = False

    # Timing
    elapsed_ms: int = 0


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Phase 1: Download
# ---------------------------------------------------------------------------

def phase_download(
    date_range: DateRange,
    data_dir: Path,
    sections: list[str] | None = None,
    include_extras: bool = True,
    skip_existing: bool = True,
) -> tuple[DownloadManifest, PipelineResult]:
    """Download ZIP bundles for the given date range.

    Returns:
        (manifest, partial PipelineResult with download metrics)
    """
    result = PipelineResult()

    _log(f"phase_download: {date_range.start} → {date_range.end} ({len(date_range)} days)")

    targets = build_targets(date_range, sections=sections, include_extras=include_extras)
    result.zips_targeted = len(targets)
    _log(f"phase_download: {len(targets)} targets")

    manifest = download_batch(targets, data_dir, skip_existing=skip_existing)
    result.zips_downloaded = len(manifest.downloaded)
    result.zips_failed = len(manifest.failed)
    result.download_bytes = manifest.total_bytes

    # Write manifest
    write_manifest(manifest, data_dir)

    _log(
        f"phase_download done: {result.zips_downloaded} ok, "
        f"{result.zips_failed} failed, {result.download_bytes:,} bytes"
    )
    return manifest, result


# ---------------------------------------------------------------------------
# Phase 2: Extract
# ---------------------------------------------------------------------------

def phase_extract(
    zip_paths: list[Path],
    extract_dir: Path | None = None,
) -> tuple[list[ExtractionResult], list[str]]:
    """Extract XML files from downloaded ZIPs.

    Args:
        zip_paths: Paths to ZIP files
        extract_dir: Base directory for extraction (default: alongside ZIPs)

    Returns:
        (list of ExtractionResult, list of error messages)
    """
    _log(f"phase_extract: {len(zip_paths)} zips")
    results: list[ExtractionResult] = []
    errors: list[str] = []

    for zp in zip_paths:
        if extract_dir:
            out_dir = extract_dir / zp.stem
        else:
            out_dir = None  # extract_xml_from_zip will use zip_path.parent/stem
        er = extract_xml_from_zip(zp, output_dir=out_dir)
        results.append(er)
        errors.extend(er.errors)

    total_xml = sum(len(er.xml_files) for er in results)
    total_img = sum(len(er.image_files) for er in results)
    _log(f"phase_extract done: {total_xml} xml, {total_img} images, {len(errors)} errors")
    return results, errors


# ---------------------------------------------------------------------------
# Phase 3: Parse
# ---------------------------------------------------------------------------

def phase_parse(
    extraction_results: list[ExtractionResult],
) -> tuple[list[tuple[DOUArticle, Path]], list[str]]:
    """Parse extracted XML files into DOUArticle objects.

    Returns:
        (list of (article, xml_path) tuples, list of error messages)
    """
    parser = INLabsXMLParser()
    articles: list[tuple[DOUArticle, Path]] = []
    errors: list[str] = []

    total_xml = sum(len(er.xml_files) for er in extraction_results)
    _log(f"phase_parse: {total_xml} xml files")

    for er in extraction_results:
        for xml_path in er.xml_files:
            try:
                article = parser.parse_file(xml_path)
                articles.append((article, xml_path))
            except Exception as ex:
                errors.append(f"{xml_path.name}: {ex}")

    _log(f"phase_parse done: {len(articles)} parsed, {len(errors)} skipped")
    return articles, errors


# ---------------------------------------------------------------------------
# Phase 4: Normalize
# ---------------------------------------------------------------------------

def phase_normalize(
    articles: list[tuple[DOUArticle, Path]],
    zip_sha256_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Normalize parsed articles into registry ingest records.

    Args:
        articles: List of (article, xml_path) tuples
        zip_sha256_map: Optional {zip_stem: sha256} for listing_sha256 evidence

    Returns:
        List of dicts ready for registry_ingest.ingest_records()
    """
    _log(f"phase_normalize: {len(articles)} articles")
    records: list[dict[str, Any]] = []

    for article, xml_path in articles:
        # Try to find the source ZIP's SHA-256
        zip_sha = ""
        if zip_sha256_map:
            # xml_path is inside a dir named after the zip stem
            parent_stem = xml_path.parent.name
            zip_sha = zip_sha256_map.get(parent_stem, "")

        record = article_to_ingest_record(
            article,
            zip_sha256=zip_sha,
            source_file=str(xml_path),
        )
        records.append(record)

    _log(f"phase_normalize done: {len(records)} records")
    return records


# ---------------------------------------------------------------------------
# Phase 5: Ingest
# ---------------------------------------------------------------------------

def phase_ingest(
    dsn: str,
    records: list[dict[str, Any]],
    seal: bool = False,
    sources_yaml: Path | None = None,
    identity_yaml: Path | None = None,
) -> PipelineResult:
    """Ingest normalized records into PostgreSQL.

    Args:
        dsn: PostgreSQL connection string
        records: Pre-computed ingest records
        seal: Whether to seal with CRSS-1 commitment
        sources_yaml: Path to sources YAML (for commitment)
        identity_yaml: Path to identity YAML (for commitment)

    Returns:
        PipelineResult with ingestion metrics
    """
    # Lazy import to avoid DB dependency when only downloading/parsing
    from src.backend.dbsync.registry_ingest import (
        IngestResult,
        ingest_and_seal,
        ingest_records,
    )

    result = PipelineResult(records_produced=len(records))

    _log(f"phase_ingest: {len(records)} records, seal={seal}")

    if seal:
        ir = ingest_and_seal(dsn, records, sources_yaml, identity_yaml)
    else:
        ir = ingest_records(dsn, records)

    result.records_ingested = ir.inserted
    result.records_duplicate = ir.duplicate_skipped
    result.records_new_version = ir.new_version
    result.records_new_publication = ir.new_publication
    result.ingestion_errors = [str(e) for e in ir.errors]
    result.commitment_root = ir.commitment_root
    result.commitment_sealed = ir.commitment_sealed

    _log(
        f"phase_ingest done: inserted={ir.inserted} dup={ir.duplicate_skipped} "
        f"new_ver={ir.new_version} new_pub={ir.new_publication} "
        f"errors={len(ir.errors)} sealed={ir.commitment_sealed}"
    )
    return result


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    date_range: DateRange,
    data_dir: Path,
    dsn: str | None = None,
    sections: list[str] | None = None,
    include_extras: bool = True,
    skip_download: bool = False,
    download_only: bool = False,
    parse_only: bool = False,
    seal: bool = False,
    sources_yaml: Path | None = None,
    identity_yaml: Path | None = None,
) -> PipelineResult:
    """Execute the full bulk ingestion pipeline.

    Pipeline stages:
      1. Download ZIPs (skip if --skip-download)
      2. Extract XML from ZIPs
      3. Parse XML → DOUArticle
      4. Normalize → registry records
      5. Ingest to PostgreSQL (skip if --download-only or --parse-only)
      6. Seal with CRSS-1 commitment (if --seal)

    Args:
        date_range: Date range to ingest
        data_dir: Directory for ZIP downloads and extractions
        dsn: PostgreSQL DSN (required for ingestion)
        sections: Override sections (default: auto-detect with extras)
        include_extras: Probe tags API for extra editions
        skip_download: Skip download phase (use existing ZIPs)
        download_only: Stop after download phase
        parse_only: Stop after parse phase (no DB)
        seal: Seal batch with CRSS-1 commitment
        sources_yaml: Path to sources YAML (for commitment)
        identity_yaml: Path to identity YAML (for commitment)

    Returns:
        PipelineResult with all metrics
    """
    start_time = time.monotonic()
    result = PipelineResult()
    zip_sha256_map: dict[str, str] = {}

    # --- Phase 1: Download ---
    if not skip_download:
        manifest, dl_result = phase_download(
            date_range, data_dir,
            sections=sections,
            include_extras=include_extras,
        )
        result.zips_targeted = dl_result.zips_targeted
        result.zips_downloaded = dl_result.zips_downloaded
        result.zips_failed = dl_result.zips_failed
        result.download_bytes = dl_result.download_bytes

        # Build SHA-256 map from download results
        for dr in manifest.downloaded:
            if dr.local_path and dr.sha256:
                zip_sha256_map[dr.local_path.stem] = dr.sha256

        zip_paths = [dr.local_path for dr in manifest.downloaded if dr.local_path]
    else:
        # Discover existing ZIPs in data_dir matching date range
        zip_paths = _discover_existing_zips(data_dir, date_range, sections)
        result.zips_targeted = len(zip_paths)
        result.zips_downloaded = len(zip_paths)
        _log(f"skip_download: found {len(zip_paths)} existing zips")

        # Compute SHA-256 for existing ZIPs
        for zp in zip_paths:
            zip_sha256_map[zp.stem] = file_sha256(zp)

    if download_only:
        result.elapsed_ms = int((time.monotonic() - start_time) * 1000)
        return result

    # --- Phase 2: Extract ---
    extraction_results, extract_errors = phase_extract(zip_paths)
    result.xml_files_extracted = sum(len(er.xml_files) for er in extraction_results)
    result.image_files_extracted = sum(len(er.image_files) for er in extraction_results)
    result.extraction_errors = extract_errors

    # --- Phase 3: Parse ---
    articles, parse_errors = phase_parse(extraction_results)
    result.articles_parsed = len(articles)
    result.articles_skipped = len(parse_errors)
    result.extraction_errors.extend(parse_errors)

    if parse_only:
        result.elapsed_ms = int((time.monotonic() - start_time) * 1000)
        _log(f"parse_only: {result.articles_parsed} articles from {result.xml_files_extracted} xml files")
        return result

    # --- Phase 4: Normalize ---
    records = phase_normalize(articles, zip_sha256_map)
    result.records_produced = len(records)

    # --- Phase 5+6: Ingest + Seal ---
    if dsn is None:
        _log("WARNING: no DSN provided, skipping ingestion")
        result.elapsed_ms = int((time.monotonic() - start_time) * 1000)
        return result

    ingest_result = phase_ingest(
        dsn, records,
        seal=seal,
        sources_yaml=sources_yaml,
        identity_yaml=identity_yaml,
    )
    result.records_ingested = ingest_result.records_ingested
    result.records_duplicate = ingest_result.records_duplicate
    result.records_new_version = ingest_result.records_new_version
    result.records_new_publication = ingest_result.records_new_publication
    result.ingestion_errors = ingest_result.ingestion_errors
    result.commitment_root = ingest_result.commitment_root
    result.commitment_sealed = ingest_result.commitment_sealed

    result.elapsed_ms = int((time.monotonic() - start_time) * 1000)
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _discover_existing_zips(
    data_dir: Path,
    date_range: DateRange,
    sections: list[str] | None = None,
) -> list[Path]:
    """Find already-downloaded ZIPs in data_dir matching date range.

    Checks for both monthly archive naming (YYYY-MM_SECTION.zip)
    and legacy daily naming (YYYY-MM-DD_SECTION.zip).
    """
    if not data_dir.exists():
        return []

    target_sections = sections or list(ALL_SECTIONS)
    zip_paths: list[Path] = []

    # Discover unique months in range
    months_seen: set[str] = set()
    for d in date_range.dates():
        months_seen.add(d.strftime("%Y-%m"))

    # Check for monthly archives (new naming)
    for month_str in sorted(months_seen):
        for section in target_sections:
            local_name = f"{month_str}_{section.upper()}.zip"
            zp = data_dir / local_name
            if zp.exists() and zp.stat().st_size > 0:
                zip_paths.append(zp)

    # Also check for daily archives (legacy naming from INLabs)
    for d in date_range.dates():
        for section in target_sections:
            local_name = f"{d.isoformat()}_{section.upper()}.zip"
            zp = data_dir / local_name
            if zp.exists() and zp.stat().st_size > 0 and zp not in zip_paths:
                zip_paths.append(zp)

    return sorted(zip_paths)


def _print_summary(result: PipelineResult) -> None:
    """Print a human-readable pipeline summary."""
    print("\n" + "=" * 60)
    print("BULK PIPELINE SUMMARY")
    print("=" * 60)
    print(f"  Download:    {result.zips_downloaded}/{result.zips_targeted} zips "
          f"({result.download_bytes:,} bytes)")
    print(f"  Extract:     {result.xml_files_extracted} xml, "
          f"{result.image_files_extracted} images")
    print(f"  Parse:       {result.articles_parsed} articles "
          f"({result.articles_skipped} skipped)")
    print(f"  Normalize:   {result.records_produced} records")
    print(f"  Ingest:      {result.records_ingested} inserted, "
          f"{result.records_duplicate} duplicate, "
          f"{result.records_new_version} new_version, "
          f"{result.records_new_publication} new_pub")
    if result.commitment_sealed:
        print(f"  Commitment:  {result.commitment_root[:16]}... (SEALED)")
    elif result.commitment_root:
        print(f"  Commitment:  {result.commitment_root[:16]}... (NOT sealed)")
    else:
        print(f"  Commitment:  (none)")
    print(f"  Errors:      {len(result.extraction_errors) + len(result.ingestion_errors)}")
    print(f"  Time:        {result.elapsed_ms / 1000:.1f}s")
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Bulk DOU ingestion pipeline: download → parse → ingest → seal",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Date selection
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--days", type=int, help="Ingest last N weekdays")
    g.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    g.add_argument("--sync", action="store_true",
                   help="Auto-sync: discover new ZIPs from catalog, download and ingest")
    p.add_argument("--end", type=str, help="End date (YYYY-MM-DD, required with --start)")

    # Data directory
    p.add_argument(
        "--data-dir", type=Path, default=Path("ops/data/inlabs"),
        help="Directory for ZIP downloads (default: ops/data/inlabs)",
    )

    # Sections
    p.add_argument(
        "--sections", nargs="+", default=None,
        help="Sections to download (e.g. do1 do2 do3 do1e). Default: all + auto-detect extras",
    )
    p.add_argument(
        "--no-extras", action="store_true",
        help="Skip extra edition detection via tags API",
    )

    # Pipeline modes
    p.add_argument("--download-only", action="store_true", help="Stop after download phase")
    p.add_argument("--parse-only", action="store_true", help="Stop after parse phase (no DB)")
    p.add_argument("--skip-download", action="store_true", help="Use existing ZIPs, skip download")

    # Database
    p.add_argument(
        "--dsn",
        default=os.environ.get(
            "GABI_DSN", "host=localhost port=5433 dbname=gabi user=gabi password=gabi"
        ),
        help="PostgreSQL DSN",
    )

    # Commitment
    p.add_argument("--seal", action="store_true", help="Seal batch with CRSS-1 commitment")
    p.add_argument("--sources", type=Path, default=None, help="Path to sources YAML")
    p.add_argument("--identity", type=Path, default=None, help="Path to identity YAML")

    # Sync-specific options
    p.add_argument("--refresh-catalog", action="store_true",
                   help="Re-scrape in.gov.br catalog before syncing (with --sync)")
    p.add_argument("--sync-start", type=str, default=None,
                   help="Sync: start month filter (YYYY-MM)")
    p.add_argument("--sync-end", type=str, default=None,
                   help="Sync: end month filter (YYYY-MM)")
    p.add_argument("--limit", type=int, default=0,
                   help="Sync: max ZIPs to process per run (0=all)")
    p.add_argument("--dry-run", action="store_true",
                   help="Sync: show what would be downloaded without doing it")

    args = p.parse_args()

    # --- Sync mode ---
    if args.sync:
        from src.backend.ingest.sync_pipeline import run_sync, _print_summary as _print_sync_summary

        sync_result = run_sync(
            dsn=args.dsn,
            data_dir=args.data_dir,
            refresh=args.refresh_catalog,
            start_month=args.sync_start,
            end_month=args.sync_end,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        _print_sync_summary(sync_result)
        return 0

    # Build date range
    if args.days:
        end_date = date.today()
        start_date = end_date - timedelta(days=args.days)
        date_range = DateRange(start_date, end_date)
    else:
        if not args.end:
            p.error("--end is required when using --start")
        start_date = date.fromisoformat(args.start)
        end_date = date.fromisoformat(args.end)
        date_range = DateRange(start_date, end_date)

    # Determine DSN
    dsn = args.dsn if not (args.download_only or args.parse_only) else None

    result = run_pipeline(
        date_range=date_range,
        data_dir=args.data_dir,
        dsn=dsn,
        sections=args.sections,
        include_extras=not args.no_extras,
        skip_download=args.skip_download,
        download_only=args.download_only,
        parse_only=args.parse_only,
        seal=args.seal,
        sources_yaml=args.sources,
        identity_yaml=args.identity,
    )

    _print_summary(result)

    # Exit code: 0 if no errors, 1 if any errors
    if result.ingestion_errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
