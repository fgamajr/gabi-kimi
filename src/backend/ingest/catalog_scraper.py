"""Scrape the DOU 'Base de Dados' catalog to build a complete folderId registry.

The Imprensa Nacional publishes monthly ZIP archives at:
    https://www.in.gov.br/acesso-a-informacao/dados-abertos/base-de-dados?ano=YYYY&mes=MES

Each page contains download links with the folderId embedded:
    https://www.in.gov.br/documents/49035712/{folderId}/{filename}.zip/...

This script iterates all year/month combinations and extracts the folderId and
available file list for each month.

Usage:
    python -m src.backend.ingest.catalog_scraper --start-year 2002 --end-year 2026
    python -m src.backend.ingest.catalog_scraper --start-year 2020 --end-year 2026 --download ops/data/catalog_zips
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CATALOG_URL = "https://www.in.gov.br/acesso-a-informacao/dados-abertos/base-de-dados"
GROUP_ID = "49035712"

MONTHS_PT: list[str] = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]

# Regex to extract folderId and filename from download links
# Pattern: /documents/49035712/{folderId}/{filename}.zip/{uuid}?...
# Filenames may contain underscores (e.g. S01122025_Parte1.zip)
_LINK_RE = re.compile(
    r"/documents/49035712/(\d+)/([A-Za-z0-9_]+\.zip)/",
)

_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class MonthEntry:
    """Catalog entry for one year-month."""
    year: int
    month: int
    folder_id: int | None = None
    files: list[str] = field(default_factory=list)
    download_urls: list[str] = field(default_factory=list)
    error: str | None = None
    http_status: int | None = None

    @property
    def month_str(self) -> str:
        return f"{self.year}-{self.month:02d}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "month": self.month,
            "month_str": self.month_str,
            "folder_id": self.folder_id,
            "files": self.files,
            "download_urls": self.download_urls,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _build_session(max_retries: int = 3) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=max_retries,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=5, pool_maxsize=5)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
    })
    return session


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape_month(
    year: int,
    month: int,
    session: requests.Session,
    timeout: int = 30,
) -> MonthEntry:
    """Fetch the catalog page for a year/month and extract folderId + file list."""
    entry = MonthEntry(year=year, month=month)
    month_name = MONTHS_PT[month - 1]

    ua_idx = (year * 12 + month) % len(_USER_AGENTS)
    try:
        resp = session.get(
            CATALOG_URL,
            params={"ano": str(year), "mes": month_name},
            headers={"User-Agent": _USER_AGENTS[ua_idx]},
            timeout=timeout,
        )
        entry.http_status = resp.status_code

        if resp.status_code != 200:
            entry.error = f"HTTP {resp.status_code}"
            return entry

        # Extract all document links
        matches = _LINK_RE.findall(resp.text)
        if not matches:
            entry.error = "no_links"
            return entry

        folder_ids: set[int] = set()
        for folder_id_str, filename in matches:
            fid = int(folder_id_str)
            folder_ids.add(fid)
            if filename not in entry.files:
                entry.files.append(filename)

            # Reconstruct full download URL (without UUID, simpler)
            full_url = f"https://www.in.gov.br/documents/{GROUP_ID}/{fid}/{filename}"
            if full_url not in entry.download_urls:
                entry.download_urls.append(full_url)

        # All files in a month should share the same folderId
        if len(folder_ids) == 1:
            entry.folder_id = folder_ids.pop()
        elif len(folder_ids) > 1:
            # Multiple folderIds in one month — unusual, take the most common
            entry.folder_id = min(folder_ids)  # pick lowest as canonical
            entry.error = f"multiple_folder_ids: {sorted(folder_ids)}"

    except Exception as ex:
        entry.error = str(ex)

    return entry


def scrape_all(
    start_year: int,
    end_year: int,
    end_month: int | None = None,
    session: requests.Session | None = None,
    delay: float = 0.5,
) -> list[MonthEntry]:
    """Scrape catalog for all year-month combinations.

    Args:
        start_year: First year to scrape (inclusive)
        end_year: Last year to scrape (inclusive)
        end_month: Last month in end_year (default: 12, or current month for current year)
        session: Reusable requests session
        delay: Delay between requests in seconds
    """
    own_session = session is None
    if own_session:
        session = _build_session()

    entries: list[MonthEntry] = []
    today = date.today()

    # Build month list
    months_to_scrape: list[tuple[int, int]] = []
    for y in range(start_year, end_year + 1):
        max_m = 12
        if y == end_year and end_month is not None:
            max_m = end_month
        elif y == today.year:
            max_m = today.month
        for m in range(1, max_m + 1):
            months_to_scrape.append((y, m))

    total = len(months_to_scrape)
    _log(f"Scraping {total} months ({start_year}-01 to {months_to_scrape[-1][0]}-{months_to_scrape[-1][1]:02d})")

    for idx, (year, month) in enumerate(months_to_scrape, start=1):
        entry = scrape_month(year, month, session)

        status = "OK" if entry.folder_id else entry.error or "empty"
        files_str = ", ".join(entry.files) if entry.files else "none"
        _log(f"[{idx:3d}/{total}] {entry.month_str}: folderId={entry.folder_id or '???':>12}  "
             f"files=[{files_str}]  {status}")

        entries.append(entry)

        if idx < total:
            time.sleep(delay)

    if own_session and session:
        session.close()

    return entries


# ---------------------------------------------------------------------------
# Registry output
# ---------------------------------------------------------------------------

def build_registry(entries: list[MonthEntry]) -> dict[str, Any]:
    """Build a month→folderId registry from scraped entries.

    Returns a dict suitable for JSON serialization:
    {
        "scraped_at": "2026-03-03",
        "group_id": "49035712",
        "total_months": 291,
        "months_with_data": 285,
        "months_missing": 6,
        "folder_ids": {
            "2002-04": 50300481,
            "2002-05": 50300485,
            ...
        },
        "files": {
            "2002-04": ["S01042002.zip", "S02042002.zip", "S03042002.zip"],
            ...
        },
        "errors": {
            "2002-01": "no_links",
            ...
        }
    }
    """
    folder_ids: dict[str, int] = {}
    files: dict[str, list[str]] = {}
    errors: dict[str, str] = {}

    for e in entries:
        if e.folder_id:
            folder_ids[e.month_str] = e.folder_id
            files[e.month_str] = e.files
        if e.error:
            errors[e.month_str] = e.error

    return {
        "scraped_at": date.today().isoformat(),
        "group_id": GROUP_ID,
        "total_months": len(entries),
        "months_with_data": len(folder_ids),
        "months_missing": len(entries) - len(folder_ids),
        "folder_ids": folder_ids,
        "files": files,
        "errors": errors,
    }


def write_registry(registry: dict[str, Any], output_path: Path) -> None:
    """Write the registry to a JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _log(f"Registry written to {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description="Scrape DOU catalog to build folderId registry"
    )
    p.add_argument("--start-year", type=int, default=2002,
                   help="First year to scrape (default: 2002)")
    p.add_argument("--end-year", type=int, default=2026,
                   help="Last year to scrape (default: 2026)")
    p.add_argument("--end-month", type=int, default=None,
                   help="Last month in end year (default: current month)")
    p.add_argument("--output", type=str, default="ops/data/dou_catalog_registry.json",
                   help="Output JSON path (default: ops/data/dou_catalog_registry.json)")
    p.add_argument("--delay", type=float, default=0.5,
                   help="Delay between requests in seconds (default: 0.5)")
    args = p.parse_args()

    entries = scrape_all(
        start_year=args.start_year,
        end_year=args.end_year,
        end_month=args.end_month,
        delay=args.delay,
    )

    registry = build_registry(entries)

    output_path = Path(args.output)
    write_registry(registry, output_path)

    # Summary
    _log(f"\n{'='*60}")
    _log(f"CATALOG SCRAPE COMPLETE")
    _log(f"{'='*60}")
    _log(f"Total months scraped: {registry['total_months']}")
    _log(f"Months with data:     {registry['months_with_data']}")
    _log(f"Months missing:       {registry['months_missing']}")

    if registry["folder_ids"]:
        fids = list(registry["folder_ids"].values())
        _log(f"FolderId range:       {min(fids)} to {max(fids)}")

        # Detect regime changes
        sorted_months = sorted(registry["folder_ids"].items())
        prev_fid = None
        jumps: list[tuple[str, int, int]] = []
        for month, fid in sorted_months:
            if prev_fid is not None:
                diff = fid - prev_fid
                if diff > 100:  # significant jump
                    jumps.append((month, prev_fid, fid))
            prev_fid = fid

        if jumps:
            _log(f"\nPlatform migration jumps detected:")
            for month, old, new in jumps:
                _log(f"  {month}: {old:>12} → {new:>12} (jump: {new-old:+,})")

    if registry["errors"]:
        _log(f"\nFirst 10 errors:")
        for month, err in list(registry["errors"].items())[:10]:
            _log(f"  {month}: {err}")

    _log(f"\nRegistry saved to: {output_path}")
    _log(f"{'='*60}")


if __name__ == "__main__":
    main()
