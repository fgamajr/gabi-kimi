"""Incremental sync pipeline for DOU publications.

Compares the catalog registry (all available ZIPs on in.gov.br) against
already-ingested ZIPs in the ``dou.source_zip`` table, downloads only the
missing ones, and ingests them into the ``dou.*`` schema.

Designed to be run periodically (cron, systemd timer) for hands-off operation.

Usage:
    # Full sync: discover new → download → ingest
    python -m src.backend.ingest.sync_pipeline

    # Refresh the catalog from in.gov.br first
    python -m src.backend.ingest.sync_pipeline --refresh-catalog

    # Dry-run: show what would be downloaded
    python -m src.backend.ingest.sync_pipeline --dry-run

    # Sync specific month range only
    python -m src.backend.ingest.sync_pipeline --start 2025-01 --end 2026-01

    # Limit number of ZIPs per run
    python -m src.backend.ingest.sync_pipeline --limit 20
"""

from __future__ import annotations

import argparse
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from src.backend.ingest.catalog_scraper import (
    build_registry,
    scrape_all,
    write_registry,
)
from src.backend.ingest.dou_ingest import BatchIngestResult, DOUIngestor, _log
from src.backend.ingest import zip_downloader as _zd
from src.backend.ingest.zip_downloader import (
    ZIPTarget,
    download_zip,
    load_folder_registry,
    _build_session,
    BASE_DOCUMENT_URL,
    GROUP_ID,
    ALL_SECTIONS,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SyncPlan:
    """Plan computed by comparing catalog vs DB."""

    available: list[dict[str, Any]] = field(default_factory=list)
    ingested: set[str] = field(default_factory=set)
    missing: list[dict[str, Any]] = field(default_factory=list)
    months_total: int = 0
    months_complete: int = 0
    months_partial: int = 0


@dataclass(slots=True)
class SyncResult:
    """Aggregate result of a sync run."""

    plan: SyncPlan | None = None
    downloaded: int = 0
    download_failed: int = 0
    download_bytes: int = 0
    ingest_result: BatchIngestResult | None = None
    elapsed_ms: int = 0
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Discovery — catalog side
# ---------------------------------------------------------------------------


def discover_available(
    registry_path: Path | None = None,
    start_month: str | None = None,
    end_month: str | None = None,
) -> list[dict[str, Any]]:
    """List all ZIPs available in the catalog registry.

    Each entry: {month, filename, section, folder_id, url}

    Args:
        registry_path: Path to dou_catalog_registry.json (auto-detected if None)
        start_month: Filter: only months >= this (YYYY-MM)
        end_month: Filter: only months <= this (YYYY-MM)

    Returns:
        List of available ZIP descriptors.
    """
    # Load the registry (lazily, once)
    load_folder_registry(registry_path)

    entries: list[dict[str, Any]] = []

    for month_key in sorted(_zd._FILE_REGISTRY.keys()):
        if start_month and month_key < start_month:
            continue
        if end_month and month_key > end_month:
            continue

        folder_id = _zd._FOLDER_REGISTRY.get(month_key)
        if not folder_id:
            continue

        for filename in _zd._FILE_REGISTRY[month_key]:
            section = _filename_to_section(filename)
            url = f"{BASE_DOCUMENT_URL}/{GROUP_ID}/{folder_id}/{filename}"

            entries.append(
                {
                    "month": month_key,
                    "filename": filename,
                    "section": section,
                    "folder_id": folder_id,
                    "url": url,
                }
            )

    return entries


def _filename_to_section(fname: str) -> str | None:
    """Infer section code from a ZIP filename."""
    base = fname.split("_")[0].replace(".zip", "")
    for section, prefix in ALL_SECTIONS.items():
        if base.startswith(prefix) and len(base) == len(prefix) + 6:
            return section
    return None


# ---------------------------------------------------------------------------
# Discovery — DB side
# ---------------------------------------------------------------------------


def discover_ingested(dsn: str) -> set[str]:
    """Query dou.source_zip for filenames already ingested.

    Returns:
        Set of filenames (e.g. {'S01012002.zip', '2002-01_DO1.zip', ...})
    """
    import psycopg2

    ingested: set[str] = set()
    try:
        conn = psycopg2.connect(dsn)
        cur = conn.cursor()
        cur.execute("SELECT filename FROM dou.source_zip")
        for row in cur:
            ingested.add(row[0])
        conn.close()
    except Exception as ex:
        _log(f"discover_ingested: DB error: {ex}")

    return ingested


def _extract_native_filename(local_filename: str) -> str | None:
    """Extract the INLabs native ZIP filename from a local filename.

    "2002-01_do1_S01012002.zip" → "S01012002.zip"
    "S01012002.zip"             → "S01012002.zip"
    """
    m = re.search(r"(S\d{2}(?:E)?\d{6}(?:_Parte\w+)?\.zip)", local_filename, re.IGNORECASE)
    if m:
        return m.group(1)
    return local_filename


# ---------------------------------------------------------------------------
# Delta computation
# ---------------------------------------------------------------------------


def compute_sync_plan(
    available: list[dict[str, Any]],
    ingested: set[str],
) -> SyncPlan:
    """Compute which ZIPs need to be downloaded and ingested.

    Matches by both local filename patterns and native INLabs filenames
    to handle both naming conventions.

    Returns:
        SyncPlan with missing entries.
    """
    plan = SyncPlan(available=available, ingested=ingested)

    # Build lookup of ingested filenames (both native and local forms)
    ingested_native: set[str] = set()
    for fn in ingested:
        ingested_native.add(fn)
        # Also extract native name from local convention
        native = _extract_native_filename(fn)
        if native:
            ingested_native.add(native)

    # Find missing
    months_with_some: set[str] = set()
    months_seen: set[str] = set()

    for entry in available:
        months_seen.add(entry["month"])
        fn = entry["filename"]

        # Check if already ingested (either by native name or full local name)
        if fn in ingested_native:
            months_with_some.add(entry["month"])
            continue

        # Also check with typical local naming: "YYYY-MM_SECTION_NATIVE.zip"
        month = entry["month"]
        section = entry["section"]
        local_name = f"{month}_{section}_{fn}" if section else fn
        if local_name in ingested_native:
            months_with_some.add(entry["month"])
            continue

        plan.missing.append(entry)

    # Compute completeness
    plan.months_total = len(months_seen)
    all_months_with_missing = {e["month"] for e in plan.missing}
    plan.months_complete = len(months_seen - all_months_with_missing)
    plan.months_partial = len(all_months_with_missing & months_with_some)

    return plan


# ---------------------------------------------------------------------------
# Download phase
# ---------------------------------------------------------------------------


def download_missing(
    plan: SyncPlan,
    data_dir: Path,
    delay: float = 0.8,
    limit: int = 0,
) -> tuple[list[Path], int, int, int]:
    """Download ZIPs listed as missing in the sync plan.

    Args:
        plan: Sync plan with missing entries
        data_dir: Directory to save downloaded ZIPs
        delay: Delay between requests (seconds)
        limit: Max ZIPs to download (0 = all)

    Returns:
        (downloaded_paths, download_count, failed_count, bytes_total)
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    targets = plan.missing
    if limit > 0:
        targets = targets[:limit]

    session = _build_session()
    downloaded_paths: list[Path] = []
    failed = 0
    total_bytes = 0

    try:
        for idx, entry in enumerate(targets, 1):
            month = entry["month"]
            section = entry.get("section", "")
            filename = entry["filename"]
            url = entry["url"]

            # Local filename: "YYYY-MM_SECTION_NATIVE.zip"
            sec_upper = (section or "").upper()
            local_fn = f"{month}_{sec_upper}_{filename}"
            local_path = data_dir / local_fn

            if local_path.exists() and local_path.stat().st_size > 0:
                _log(f"[{idx}/{len(targets)}] skip (exists) {local_fn}")
                downloaded_paths.append(local_path)
                continue

            target = ZIPTarget(
                section=section or "unknown",
                pub_date=date(int(month[:4]), int(month[5:7]), 1),
                url=url,
                filename=filename,
                local_filename=local_fn,
            )

            result = download_zip(target, data_dir, session=session, skip_existing=True)

            if result.success and result.local_path:
                downloaded_paths.append(result.local_path)
                total_bytes += result.size_bytes
                _log(
                    f"[{idx}/{len(targets)}] ✓ {local_fn} "
                    f"({result.size_bytes / 1024 / 1024:.1f} MB, {result.download_time_ms}ms)"
                )
            else:
                failed += 1
                _log(f"[{idx}/{len(targets)}] ✗ {local_fn}: {result.error}")

            if idx < len(targets):
                time.sleep(delay)
    finally:
        session.close()

    return downloaded_paths, len(downloaded_paths), failed, total_bytes


# ---------------------------------------------------------------------------
# Refresh catalog
# ---------------------------------------------------------------------------


def refresh_catalog(
    registry_path: Path,
    start_year: int = 2002,
    end_year: int | None = None,
    delay: float = 0.5,
) -> dict[str, Any]:
    """Re-scrape the in.gov.br catalog and update the local registry.

    Args:
        registry_path: Where to save the registry JSON
        start_year: First year to scrape
        end_year: Last year (default: current year)
        delay: Delay between requests

    Returns:
        The newly built registry dict.
    """
    today = date.today()
    if end_year is None:
        end_year = today.year

    _log(f"Refreshing catalog: {start_year} → {end_year}")
    entries = scrape_all(
        start_year=start_year,
        end_year=end_year,
        delay=delay,
    )
    registry = build_registry(entries)
    write_registry(registry, registry_path)

    _log(f"Catalog refreshed: {registry['months_with_data']}/{registry['total_months']} months with data")
    return registry


# ---------------------------------------------------------------------------
# Full sync orchestrator
# ---------------------------------------------------------------------------


def run_sync(
    dsn: str,
    data_dir: Path,
    registry_path: Path | None = None,
    refresh: bool = False,
    start_month: str | None = None,
    end_month: str | None = None,
    limit: int = 0,
    dry_run: bool = False,
    download_delay: float = 0.8,
) -> SyncResult:
    """Execute the full incremental sync pipeline.

    Steps:
      1. (optional) Refresh catalog from in.gov.br
      2. Load catalog registry → list all available ZIPs
      3. Query DB → list already-ingested ZIPs
      4. Compute delta = available − ingested
      5. Download missing ZIPs
      6. Ingest downloaded ZIPs into dou.* schema

    Args:
        dsn: PostgreSQL connection string
        data_dir: Directory for downloaded ZIPs
        registry_path: Path to catalog registry JSON
        refresh: Whether to re-scrape the catalog first
        start_month: Filter start (YYYY-MM)
        end_month: Filter end (YYYY-MM)
        limit: Max ZIPs to process per run (0 = all)
        dry_run: If True, compute plan but don't download/ingest
        download_delay: Delay between download requests (seconds)

    Returns:
        SyncResult with all metrics.
    """
    t0 = time.monotonic()
    result = SyncResult(dry_run=dry_run)

    if registry_path is None:
        registry_path = Path("ops/data/dou_catalog_registry.json")

    # Step 1: Refresh catalog
    if refresh:
        refresh_catalog(registry_path)

    # Step 2: Discover available
    _log("Discovering available ZIPs from catalog...")
    available = discover_available(
        registry_path=registry_path,
        start_month=start_month,
        end_month=end_month,
    )
    _log(f"  Catalog: {len(available)} ZIPs across {len({e['month'] for e in available})} months")

    # Step 3: Discover ingested
    _log("Querying database for already-ingested ZIPs...")
    ingested = discover_ingested(dsn)
    _log(f"  DB: {len(ingested)} ZIPs already ingested")

    # Step 4: Compute delta
    plan = compute_sync_plan(available, ingested)
    result.plan = plan

    _log(f"  Delta: {len(plan.missing)} ZIPs to download/ingest")
    _log(f"  Months: {plan.months_complete}/{plan.months_total} complete, {plan.months_partial} partial")

    if not plan.missing:
        _log("Nothing to sync — all up to date!")
        result.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return result

    if dry_run:
        _log("DRY RUN — would download:")
        to_show = plan.missing[:limit] if limit > 0 else plan.missing
        for entry in to_show:
            _log(f"  {entry['month']} {entry['filename']} ({entry['section']})")
        if limit > 0 and len(plan.missing) > limit:
            _log(f"  ... and {len(plan.missing) - limit} more")
        result.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return result

    # Step 5: Download missing
    _log(f"Downloading {min(len(plan.missing), limit) if limit else len(plan.missing)} ZIPs...")
    downloaded_paths, dl_ok, dl_failed, dl_bytes = download_missing(
        plan,
        data_dir,
        delay=download_delay,
        limit=limit,
    )
    result.downloaded = dl_ok
    result.download_failed = dl_failed
    result.download_bytes = dl_bytes

    if not downloaded_paths:
        _log("No ZIPs downloaded — nothing to ingest")
        result.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return result

    # Step 6: Ingest
    _log(f"Ingesting {len(downloaded_paths)} ZIPs into dou.* schema...")
    ingestor = DOUIngestor(dsn)
    ingest_result = ingestor.ingest_batch(downloaded_paths)
    result.ingest_result = ingest_result

    result.elapsed_ms = int((time.monotonic() - t0) * 1000)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_summary(result: SyncResult) -> None:
    """Print human-readable sync summary."""
    print("\n" + "=" * 60)
    print("SYNC PIPELINE SUMMARY")
    print("=" * 60)

    if result.plan:
        p = result.plan
        print(f"  Catalog:     {len(p.available)} available ZIPs")
        print(f"  DB:          {len(p.ingested)} already ingested")
        print(f"  Delta:       {len(p.missing)} missing")
        print(f"  Months:      {p.months_complete}/{p.months_total} complete")

    if result.dry_run:
        print("  Mode:        DRY RUN (no changes)")
    else:
        print(
            f"  Downloaded:  {result.downloaded} ok, {result.download_failed} failed "
            f"({result.download_bytes / 1024 / 1024:.1f} MB)"
        )

        if result.ingest_result:
            ir = result.ingest_result
            print(f"  Ingested:    {ir.zips_succeeded}/{ir.zips_processed} ZIPs ok")
            print(f"  Documents:   {ir.total_documents}")
            print(f"  Media:       {ir.total_media}")
            print(f"  Signatures:  {ir.total_signatures}")
            print(f"  Norm refs:   {ir.total_norm_refs}")
            print(f"  Proc refs:   {ir.total_proc_refs}")
            if ir.errors:
                print(f"  Errors:      {len(ir.errors)}")

    print(f"  Time:        {result.elapsed_ms / 1000:.1f}s")
    print("=" * 60)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Incremental DOU sync: discover → download → ingest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    p.add_argument(
        "--data-dir",
        type=Path,
        default=Path("ops/data/inlabs"),
        help="Directory for downloaded ZIPs (default: ops/data/inlabs)",
    )
    p.add_argument(
        "--registry",
        type=Path,
        default=Path("ops/data/dou_catalog_registry.json"),
        help="Path to catalog registry JSON",
    )
    p.add_argument(
        "--dsn",
        default=os.environ.get("GABI_DSN", "host=localhost port=5433 dbname=gabi user=gabi password=gabi"),
        help="PostgreSQL DSN",
    )
    p.add_argument(
        "--refresh-catalog",
        action="store_true",
        help="Re-scrape in.gov.br catalog before syncing",
    )
    p.add_argument(
        "--start",
        type=str,
        default=None,
        help="Start month filter (YYYY-MM)",
    )
    p.add_argument(
        "--end",
        type=str,
        default=None,
        help="End month filter (YYYY-MM)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max ZIPs to process per run (0 = all)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be downloaded without doing it",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=0.8,
        help="Delay between download requests (seconds)",
    )

    args = p.parse_args()

    result = run_sync(
        dsn=args.dsn,
        data_dir=args.data_dir,
        registry_path=args.registry,
        refresh=args.refresh_catalog,
        start_month=args.start,
        end_month=args.end,
        limit=args.limit,
        dry_run=args.dry_run,
        download_delay=args.delay,
    )

    _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
