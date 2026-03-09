"""Discovery pipeline module — crawls Liferay JSONWS API for new DOU files.

Discovers new DOU ZIP publications from in.gov.br, checks against the SQLite
registry, and inserts newly found files. Falls back to HEAD probes when
the Liferay API is unavailable.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from src.backend.worker.registry import FileStatus, Registry

logger = logging.getLogger(__name__)

# Liferay API constants
GROUP_ID = 49035712
LIFERAY_BASE = "https://www.in.gov.br/api/jsonws"
FOLDERS_ENDPOINT = f"{LIFERAY_BASE}/dlapp/get-folders"
FILES_ENDPOINT = f"{LIFERAY_BASE}/dlapp/get-file-entries"

MAX_CONCURRENT_REQUESTS = 5

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
    r"^(S\d{2}E?)\s*(\d{2})(\d{4})(?:_Parte\d+)?\.zip$", re.IGNORECASE
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
    """Discover new DOU files from Liferay API or HEAD probe fallback.

    Args:
        registry: SQLite registry instance
        run_id: Pipeline run identifier for logging
        es_url: Elasticsearch URL (unused in discovery, kept for interface consistency)

    Returns:
        Stats dict: {"new_files": N, "existing_files": M, "fallback_used": bool}
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    new_files = 0
    existing_files = 0
    fallback_used = False

    async with httpx.AsyncClient() as client:
        try:
            # Try Liferay API first
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

                    # Check if already in registry
                    existing = await registry.get_file_by_filename(filename)
                    if existing:
                        existing_files += 1
                        continue

                    # Insert new file
                    file_url = f"https://www.in.gov.br/documents/{GROUP_ID}/{folder_id}/{filename}"
                    file_id = await registry.insert_file(
                        filename=filename,
                        section=section,
                        year_month=year_month,
                        folder_id=str(folder_id),
                        file_url=file_url,
                    )
                    if file_id:
                        new_files += 1
                        await registry.add_log_entry(
                            run_id, file_id, "INFO", f"Discovered new file: {filename}"
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

                    existing = await registry.get_file_by_filename(filename)
                    if existing:
                        existing_files += 1
                        continue

                    file_id = await registry.insert_file(
                        filename=filename,
                        section=section,
                        year_month=year_month,
                    )
                    if file_id:
                        new_files += 1
                        await registry.add_log_entry(
                            run_id, file_id, "INFO", f"Discovered (HEAD probe): {filename}"
                        )
            except Exception as probe_err:
                logger.error("HEAD probe fallback also failed: %s", probe_err)

    return {
        "new_files": new_files,
        "existing_files": existing_files,
        "fallback_used": fallback_used,
    }
