"""Catalog reconciler — delayed monthly Liferay fallback for files that failed during INLABS window.

Runs weekly: (1) transitions DOWNLOAD_FAILED to FALLBACK_PENDING when aged out of INLABS window
and retries exhausted; (2) finds months in FALLBACK_ELIGIBLE, probes Liferay for monthly ZIPs,
and transitions FALLBACK_PENDING files to DOWNLOADING when the ZIP is available.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import httpx

from src.backend.worker.registry import (
    CATALOG_STATUS_FALLBACK_ELIGIBLE,
    FileStatus,
    MAX_RETRIES,
    Registry,
)

logger = logging.getLogger(__name__)

INLABS_WINDOW_DAYS = 30

GROUP_ID = "49035712"
LIFERAY_BASE = "https://www.in.gov.br/documents"


async def _probe_liferay_url(url: str, client: httpx.AsyncClient) -> bool:
    """Return True if URL returns 200."""
    try:
        resp = await client.head(url, follow_redirects=True, timeout=15)
        return resp.status_code == 200
    except Exception as e:
        logger.debug("HEAD %s failed: %s", url, e)
        return False


def _date_from_publication_or_month(publication_date: str | None, year_month: str) -> date:
    """Derive a reference date for window check."""
    if publication_date:
        try:
            return date.fromisoformat(publication_date[:10])
        except (ValueError, TypeError):
            pass
    try:
        y, m = map(int, year_month.split("-"))
        return date(y, m, 1)
    except (ValueError, TypeError):
        return date(2000, 1, 1)


async def transition_aged_failures_to_fallback(registry: Registry) -> int:
    """Move DOWNLOAD_FAILED files that are past INLABS window and at max retries to FALLBACK_PENDING.

    Returns the number of files transitioned.
    """
    today = date.today()
    cutoff = today - timedelta(days=INLABS_WINDOW_DAYS)
    files = await registry.get_files_by_status(FileStatus.DOWNLOAD_FAILED, limit=1000)
    count = 0
    for f in files:
        if (f.get("retry_count") or 0) < MAX_RETRIES:
            continue
        ref = _date_from_publication_or_month(f.get("publication_date"), f.get("year_month") or "")
        if ref >= cutoff:
            continue
        try:
            await registry.update_status(f["id"], FileStatus.FALLBACK_PENDING, _skip_validation=True)
            count += 1
        except Exception as e:
            logger.warning("Failed to transition file %s to FALLBACK_PENDING: %s", f.get("id"), e)
    return count


async def run_reconciliation(registry: Registry, run_id: str | None = None) -> dict[str, Any]:
    """Run catalog reconciliation: find FALLBACK_ELIGIBLE months, probe Liferay, recover files.

    Args:
        registry: SQLite registry instance
        run_id: Optional pipeline run ID for logging

    Returns:
        Stats dict: recovered_months, recovered_files, months_checked, errors
    """
    # First: transition aged DOWNLOAD_FAILED to FALLBACK_PENDING
    aged = await transition_aged_failures_to_fallback(registry)
    if aged > 0 and run_id:
        await registry.add_log_entry(
            run_id,
            None,
            "INFO",
            f"Transitioned {aged} DOWNLOAD_FAILED files to FALLBACK_PENDING (aged out of INLABS window).",
        )

    months = await registry.get_catalog_months_by_status(CATALOG_STATUS_FALLBACK_ELIGIBLE)
    recovered_months = 0
    recovered_files = 0
    months_checked = len(months)
    errors: list[str] = []

    async with httpx.AsyncClient() as client:
        for row in months:
            year_month = row["year_month"]
            folder_id = row.get("folder_id")
            group_id = row.get("group_id") or GROUP_ID
            if folder_id is None:
                logger.debug("Skipping month %s: no folder_id", year_month)
                continue

            files = await registry.get_files_by_status_and_month(FileStatus.FALLBACK_PENDING, year_month)
            if not files:
                continue

            recovered_this_month = 0
            for f in files:
                filename = f["filename"]
                url = f"{LIFERAY_BASE}/{group_id}/{folder_id}/{filename}"
                if await _probe_liferay_url(url, client):
                    try:
                        await registry.update_file_fields(
                            f["id"],
                            file_url=url,
                            source="liferay",
                        )
                        await registry.update_status(f["id"], FileStatus.DOWNLOADING, _skip_validation=True)
                        recovered_this_month += 1
                        if run_id:
                            await registry.add_log_entry(
                                run_id,
                                f["id"],
                                "INFO",
                                f"Recovered via Liferay fallback: {filename}",
                            )
                    except Exception as e:
                        errors.append(f"{filename}: {e}")
                        logger.warning("Failed to transition %s: %s", filename, e)

            if recovered_this_month > 0:
                await registry.set_catalog_month_liferay_available(year_month)
                recovered_months += 1
                recovered_files += recovered_this_month
                logger.info(
                    "Reconciler: recovered %d files for %s via Liferay",
                    recovered_this_month,
                    year_month,
                )
                if run_id:
                    await registry.add_log_entry(
                        run_id,
                        None,
                        "INFO",
                        f"Recovered {recovered_this_month} files for {year_month} via Liferay monthly ZIP",
                    )

    return {
        "aged_to_fallback": aged,
        "recovered_months": recovered_months,
        "recovered_files": recovered_files,
        "months_checked": months_checked,
        "errors": errors,
    }
