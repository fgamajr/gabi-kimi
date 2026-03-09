"""Discovery pipeline module — crawls Liferay JSONWS API for new DOU files.

Discovers new DOU ZIP publications from in.gov.br, checks against the SQLite
registry, and inserts newly found files. Falls back to HEAD probes when
the Liferay API is unavailable.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import date, timedelta
from typing import Any

import httpx

from src.backend.ingest.zip_downloader import TAGS_API_URL, detect_special_editions
from src.backend.worker.inlabs_client import INLabsClient, MAX_LOOKBACK_DAYS
from src.backend.worker.registry import FileStatus, Registry

logger = logging.getLogger(__name__)

# Liferay API constants
GROUP_ID = 49035712
LIFERAY_BASE = "https://www.in.gov.br/api/jsonws"
FOLDERS_ENDPOINT = f"{LIFERAY_BASE}/dlapp/get-folders"
FILES_ENDPOINT = f"{LIFERAY_BASE}/dlapp/get-file-entries"

MAX_CONCURRENT_REQUESTS = 5
RECENT_WINDOW_DAYS = MAX_LOOKBACK_DAYS
REGULAR_INLABS_SECTIONS = ("do1", "do2", "do3")
EXTRA_INLABS_SECTION_FLAGS: dict[str, str] = {
    "DO1E": "do1e",
    "DO2E": "do2e",
    "DO3E": "do3e",
}

# Section prefix -> section code mapping (reverse of zip_downloader.ALL_SECTIONS)
_PREFIX_TO_SECTION: dict[str, str] = {
    "S01": "do1",
    "S02": "do2",
    "S03": "do3",
    "S01E": "do1e",
    "S02E": "do2e",
    "S03E": "do3e",
}

# Regex to parse DOU ZIP filenames: S{prefix}{MM}{YYYY}.zip
_FILENAME_RE = re.compile(
    r"^(S\d{2}E?)\s*(\d{2})(\d{4})(?:_Parte_?\d+)?\.zip$", re.IGNORECASE
)


def parse_dou_filename(filename: str) -> tuple[str, str]:
    """Parse a DOU ZIP filename to extract section and year_month.

    Args:
        filename: e.g. "S01022026.zip"

    Returns:
        Tuple of (section_code, year_month) e.g. ("do1", "2026-02")

    Raises:
        ValueError: If filename doesn't match expected pattern
    """
    m = _FILENAME_RE.match(filename)
    if not m:
        raise ValueError(f"Cannot parse DOU filename: {filename}")

    prefix = m.group(1).upper()
    month = m.group(2)
    year = m.group(3)

    section = _PREFIX_TO_SECTION.get(prefix)
    if section is None:
        raise ValueError(f"Unknown section prefix: {prefix}")

    return section, f"{year}-{month}"


async def _fetch_liferay_folders(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    """Fetch month folders from Liferay JSONWS API."""
    async with semaphore:
        resp = await client.get(
            FOLDERS_ENDPOINT,
            params={
                "repositoryId": GROUP_ID,
                "parentFolderId": 0,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


async def _fetch_liferay_files(
    client: httpx.AsyncClient,
    folder_id: int,
    semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    """Fetch file entries from a Liferay folder."""
    async with semaphore:
        resp = await client.get(
            FILES_ENDPOINT,
            params={
                "repositoryId": GROUP_ID,
                "folderId": folder_id,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


def _month_overlaps_recent_window(year_month: str, *, today: date | None = None) -> bool:
    """Return True when a monthly Liferay archive overlaps the INLABS recent window."""
    reference = today or date.today()
    cutoff = reference - timedelta(days=RECENT_WINDOW_DAYS)
    year, month = map(int, year_month.split("-"))
    month_start = date(year, month, 1)
    if month == 12:
        month_end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(year, month + 1, 1) - timedelta(days=1)
    return month_end >= cutoff


def _iter_recent_publication_dates(registry: Registry, *, today: date | None = None) -> tuple[date, date]:
    """Placeholder helper signature for clarity in discovery flow."""
    reference = today or date.today()
    return reference - timedelta(days=RECENT_WINDOW_DAYS), reference


async def _probe_inlabs_target(
    client: INLabsClient,
    publication_date: date,
    section: str,
) -> tuple[bool, str | None]:
    """Check if a recent INLABS ZIP exists without storing it."""
    target = client.build_target(publication_date, section)
    for attempt in range(2):
        if not client.client.cookies.get("inlabs_session_cookie"):
            await client.login()
        async with client.client.stream(
            "GET",
            target.url,
            headers=client.build_download_headers(),
        ) as response:
            if response.status_code == 200:
                return True, target.url
            if response.status_code in {401, 403} and attempt == 0:
                await client.login()
                continue
            if response.status_code == 404:
                return False, None
            response.raise_for_status()
    return False, None


async def _discover_recent_inlabs_files(
    registry: Registry,
    run_id: str,
    semaphore: asyncio.Semaphore,
) -> dict[str, int | bool]:
    """Discover recent daily publications through INLABS inside the supported window."""
    email = os.getenv("INLABS_EMAIL", "").strip()
    password = os.getenv("INLABS_PASSWORD", "").strip()
    if not email or not password:
        logger.warning("INLABS credentials missing; recent discovery skipped")
        return {"new_files": 0, "existing_files": 0, "login_failed": True}

    latest_known = await registry.get_latest_publication_date(source="inlabs")
    today = date.today()
    floor = today - timedelta(days=RECENT_WINDOW_DAYS)
    start_date = max(floor, date.fromisoformat(latest_known) + timedelta(days=1)) if latest_known else floor

    new_files = 0
    existing_files = 0
    client = INLabsClient(email, password)
    try:
        await client.login()
    except Exception as exc:
        logger.warning("INLABS login failed during discovery: %s", exc)
        await client.aclose()
        return {"new_files": 0, "existing_files": 0, "login_failed": True}

    try:
        current = start_date
        while current <= today:
            sections: list[str] = []
            if current.weekday() < 5:
                sections.extend(REGULAR_INLABS_SECTIONS)

            try:
                async with semaphore:
                    flags = detect_special_editions(current)
                for flag, section in EXTRA_INLABS_SECTION_FLAGS.items():
                    if flags.get(flag):
                        sections.append(section)
            except Exception:
                logger.debug("Special-edition probe failed for %s", current.isoformat(), exc_info=True)

            for section in sections:
                try:
                    filename = INLabsClient.build_target(current, section).filename
                except Exception:
                    continue

                existing = await registry.get_file_by_filename(filename)
                if existing:
                    existing_files += 1
                    continue

                async with semaphore:
                    exists, url = await _probe_inlabs_target(client, current, section)
                if not exists or not url:
                    await asyncio.sleep(0.2)
                    continue

                year_month_str = current.strftime("%Y-%m")
                file_id = await registry.insert_file(
                    filename=filename,
                    section=section,
                    year_month=year_month_str,
                    publication_date=current.isoformat(),
                    source="inlabs",
                    file_url=url,
                )
                if file_id:
                    new_files += 1
                    await registry.catalog_month_upsert(
                        year_month_str, source_of_truth="inlabs_discovery"
                    )
                    await registry.add_log_entry(
                        run_id,
                        file_id,
                        "INFO",
                        f"Discovered recent INLABS file: {filename}",
                    )
                await asyncio.sleep(0.2)
            current += timedelta(days=1)
    finally:
        await client.aclose()

    return {"new_files": new_files, "existing_files": existing_files, "login_failed": False}


async def _probe_head_fallback(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    """Fallback: probe known URL patterns with HEAD requests.

    Constructs URLs for recent months and checks if ZIPs exist.
    Returns list of dicts with fileName, section, year_month.
    """
    from datetime import date, timedelta

    from src.backend.ingest.zip_downloader import ALL_SECTIONS, get_folder_id

    results: list[dict[str, Any]] = []
    today = date.today()

    # Probe last 3 months
    for months_back in range(3):
        probe_date = today.replace(day=1)
        for _ in range(months_back):
            probe_date = (probe_date - timedelta(days=1)).replace(day=1)

        folder_id = get_folder_id(probe_date)
        if folder_id is None:
            continue

        month_str = probe_date.strftime("%m%Y")
        for section_code, prefix in ALL_SECTIONS.items():
            filename = f"{prefix}{month_str}.zip"
            url = f"https://www.in.gov.br/documents/{GROUP_ID}/{folder_id}/{filename}"

            async with semaphore:
                try:
                    resp = await client.head(url, timeout=15, follow_redirects=True)
                    if resp.status_code == 200:
                        results.append({
                            "fileName": filename,
                            "section": section_code,
                            "year_month": probe_date.strftime("%Y-%m"),
                        })
                except Exception:
                    pass

    return results


async def run_discovery(
    registry: Registry,
    run_id: str,
    es_url: str,
) -> dict[str, Any]:
    """Discover new DOU files using the hybrid strategy.

    Args:
        registry: SQLite registry instance
        run_id: Pipeline run identifier for logging
        es_url: Elasticsearch URL (unused in discovery, kept for interface consistency)

    Returns:
        Stats dict with hybrid source counts and fallback flags.
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    new_files = 0
    existing_files = 0
    fallback_used = False
    inlabs_stats = await _discover_recent_inlabs_files(registry, run_id, semaphore)
    new_files += int(inlabs_stats["new_files"])
    existing_files += int(inlabs_stats["existing_files"])
    liferay_new = 0
    liferay_existing = 0

    async with httpx.AsyncClient() as client:
        try:
            # Use Liferay for older monthly archives only.
            folders = await _fetch_liferay_folders(client, semaphore)

            for folder in folders:
                folder_id = folder.get("folderId")
                if folder_id is None:
                    continue

                files = await _fetch_liferay_files(client, folder_id, semaphore)
                for file_entry in files:
                    filename = file_entry.get("fileName") or file_entry.get("title", "")
                    if not filename.endswith(".zip"):
                        continue

                    try:
                        section, year_month = parse_dou_filename(filename)
                    except ValueError:
                        logger.warning("Skipping unparseable filename: %s", filename)
                        continue

                    if _month_overlaps_recent_window(year_month):
                        continue

                    # Check if already in registry
                    existing = await registry.get_file_by_filename(filename)
                    if existing:
                        existing_files += 1
                        liferay_existing += 1
                        continue

                    # Insert new file
                    file_url = f"https://www.in.gov.br/documents/{GROUP_ID}/{folder_id}/{filename}"
                    file_id = await registry.insert_file(
                        filename=filename,
                        section=section,
                        year_month=year_month,
                        publication_date=f"{year_month}-01",
                        source="liferay",
                        folder_id=folder_id,
                        file_url=file_url,
                    )
                    if file_id:
                        new_files += 1
                        liferay_new += 1
                        await registry.catalog_month_upsert(
                            year_month,
                            folder_id=folder_id,
                            group_id=str(GROUP_ID),
                            source_of_truth="liferay_discovery",
                        )
                        await registry.add_log_entry(
                            run_id, file_id, "INFO", f"Discovered Liferay archive: {filename}"
                        )

        except Exception as e:
            # Fallback to HEAD probes
            logger.warning("Liferay API unavailable (%s), falling back to HEAD probes", e)
            fallback_used = True

            try:
                probe_results = await _probe_head_fallback(client, semaphore)
                for probe in probe_results:
                    filename = probe["fileName"]
                    section = probe.get("section")
                    year_month = probe.get("year_month")

                    if not section or not year_month:
                        try:
                            section, year_month = parse_dou_filename(filename)
                        except ValueError:
                            continue

                    if _month_overlaps_recent_window(year_month):
                        continue

                    existing = await registry.get_file_by_filename(filename)
                    if existing:
                        existing_files += 1
                        liferay_existing += 1
                        continue

                    file_id = await registry.insert_file(
                        filename=filename,
                        section=section,
                        year_month=year_month,
                        publication_date=f"{year_month}-01",
                        source="liferay",
                    )
                    if file_id:
                        new_files += 1
                        liferay_new += 1
                        await registry.catalog_month_upsert(
                            year_month, source_of_truth="liferay_discovery"
                        )
                        await registry.add_log_entry(
                            run_id, file_id, "INFO", f"Discovered Liferay fallback: {filename}"
                        )
            except Exception as probe_err:
                logger.error("HEAD probe fallback also failed: %s", probe_err)

    return {
        "new_files": new_files,
        "existing_files": existing_files,
        "fallback_used": fallback_used,
        "inlabs_new_files": int(inlabs_stats["new_files"]),
        "liferay_new_files": liferay_new,
        "liferay_existing_files": liferay_existing,
        "inlabs_login_failed": bool(inlabs_stats["login_failed"]),
    }
