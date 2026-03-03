"""Discovery probe — automatically detect new DOU publications.

Probes in.gov.br for new DOU publications, compares against discovery registry,
and returns a list of new publications to download.

Usage:
    # Discover new publications (dry-run)
    python -m ingest.auto_discovery --days 7 --dry-run

    # Update discovery registry with new publications
    python -m ingest.auto_discovery --days 7 --update-registry

    # List discovered publications
    python -m ingest.auto_discovery --list --days 30

    # Export discovery registry to JSON
    python -m ingest.auto_discovery --export data/discovery_registry.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ingest.discovery_registry import (
    DiscoveredPublication,
    DiscoveryRegistry,
    create_registry,
)
from ingest.zip_downloader import (
    ALL_SECTIONS,
    SECTIONS,
    TAGS_API_URL,
    _build_session,
    _random_ua,
    detect_special_editions,
    get_folder_id,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DISCOVERY_LOOKBACK_DAYS = 7
DEFAULT_REGISTRY_BACKEND = "postgresql"
DEFAULT_DSN = "host=localhost port=5433 dbname=gabi user=gabi password=gabi"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Discovery logic
# ---------------------------------------------------------------------------

def discover_publications_for_month(
    month_date: date,
    sections: dict[str, str],
    session: requests.Session,
) -> list[DiscoveredPublication]:
    """Discover publications for a specific month.

    Checks the catalog registry for the month's folder_id, then probes
    each section to see if a ZIP exists.

    Args:
        month_date: First day of the month to discover
        sections: Section code → prefix mapping
        session: HTTP session

    Returns:
        List of discovered publications
    """
    folder_id = get_folder_id(month_date)
    if folder_id is None:
        _log(f"discover: no folder_id for {month_date.strftime('%Y-%m')}")
        return []

    publications: list[DiscoveredPublication] = []

    for section, prefix in sections.items():
        # Build URL for monthly archive
        month_str = month_date.strftime("%m%Y")
        filename = f"{prefix}{month_str}.zip"
        url = f"https://www.in.gov.br/documents/49035712/{folder_id}/{filename}"

        # Probe with HEAD request
        try:
            resp = session.head(
                url,
                headers={"User-Agent": _random_ua()},
                timeout=15,
                allow_redirects=True,
            )

            if resp.status_code == 200:
                content_length = resp.headers.get("Content-Length")
                file_size = int(content_length) if content_length else None

                pub = DiscoveredPublication(
                    section=section,
                    publication_date=month_date,
                    edition_number="",
                    edition_type="regular",
                    folder_id=folder_id,
                    filename=filename,
                    file_size=file_size,
                    discovered_at=datetime.now(),
                    downloaded=False,
                )
                publications.append(pub)
                _log(f"  ✓ {section.upper()} {month_date.strftime('%Y-%m')}: {filename} ({file_size:,}B)")

            elif resp.status_code != 404:
                _log(f"  ? {section.upper()} {month_date.strftime('%Y-%m')}: HTTP {resp.status_code}")

        except Exception as ex:
            _log(f"  ✗ {section.upper()} {month_date.strftime('%Y-%m')}: error {ex}")

        # Rate limit
        time.sleep(0.2)

    return publications


def discover_special_editions_for_date(
    pub_date: date,
    session: requests.Session,
) -> list[DiscoveredPublication]:
    """Discover special editions for a specific date.

    Queries the tags API to detect which special editions exist on a given date,
    then probes for their ZIP files.

    Args:
        pub_date: Date to check for special editions
        session: HTTP session

    Returns:
        List of discovered special edition publications
    """
    # Query tags API
    flags = detect_special_editions(pub_date, session=session)
    if not flags:
        return []

    # Map tags API flags to section codes
    TAGS_SECTION_MAP = {
        "DO1E": "do1e",
        "DO2E": "do2e",
        "DO3E": "do3e",
        "DO1ESP": "do1esp",
        "DO2ESP": "do2esp",
        "DO1A": "do1a",
    }

    # Determine which sections to probe
    sections_to_probe: dict[str, str] = {}
    for flag, is_active in flags.items():
        if is_active and flag in TAGS_SECTION_MAP:
            section = TAGS_SECTION_MAP[flag]
            if section in ALL_SECTIONS:
                sections_to_probe[section] = ALL_SECTIONS[section]

    if not sections_to_probe:
        return []

    # Get folder_id for the month
    month_date = pub_date.replace(day=1)
    folder_id = get_folder_id(month_date)
    if folder_id is None:
        return []

    publications: list[DiscoveredPublication] = []

    for section, prefix in sections_to_probe.items():
        # Build URL for special edition
        # Pattern: S{prefix}{DDMMYYYY}.zip for daily special editions
        date_str = pub_date.strftime("%d%m%Y")
        filename = f"{prefix}{date_str}.zip"
        url = f"https://www.in.gov.br/documents/49035712/{folder_id}/{filename}"

        # Probe with HEAD request
        try:
            resp = session.head(
                url,
                headers={"User-Agent": _random_ua()},
                timeout=15,
                allow_redirects=True,
            )

            if resp.status_code == 200:
                content_length = resp.headers.get("Content-Length")
                file_size = int(content_length) if content_length else None

                pub = DiscoveredPublication(
                    section=section,
                    publication_date=pub_date,
                    edition_number="",
                    edition_type="extra",
                    folder_id=folder_id,
                    filename=filename,
                    file_size=file_size,
                    discovered_at=datetime.now(),
                    downloaded=False,
                )
                publications.append(pub)
                _log(f"  ✓ {section.upper()} {pub_date.isoformat()}: {filename} ({file_size:,}B)")

            elif resp.status_code != 404:
                _log(f"  ? {section.upper()} {pub_date.isoformat()}: HTTP {resp.status_code}")

        except Exception as ex:
            _log(f"  ✗ {section.upper()} {pub_date.isoformat()}: error {ex}")

        # Rate limit
        time.sleep(0.2)

    return publications


def discover_new_publications(
    lookback_days: int = DEFAULT_DISCOVERY_LOOKBACK_DAYS,
    sections: list[str] | None = None,
    registry: DiscoveryRegistry | None = None,
    session: requests.Session | None = None,
) -> list[DiscoveredPublication]:
    """Discover new DOU publications not yet in the registry.

    Args:
        lookback_days: Number of days to look back from today
        sections: List of sections to discover (None = all regular sections)
        registry: Discovery registry to check against
        session: HTTP session (created if None)

    Returns:
        List of newly discovered publications (not in registry)
    """
    _log(f"discover_new_publications: lookback={lookback_days} days")

    # Determine sections to probe
    if sections is None:
        target_sections = list(SECTIONS.keys())  # Only regular sections by default
    else:
        target_sections = sections

    section_map = {s: ALL_SECTIONS[s] for s in target_sections if s in ALL_SECTIONS}

    # Build date range
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)

    _log(f"discover: date range {start_date} to {end_date}")

    # Discover unique months in range
    months_seen: set[tuple[int, int]] = set()
    months_to_probe: list[date] = []

    current = start_date
    while current <= end_date:
        key = (current.year, current.month)
        if key not in months_seen:
            months_seen.add(key)
            months_to_probe.append(current.replace(day=1))
        current += timedelta(days=1)

    _log(f"discover: {len(months_to_probe)} unique months to probe")

    # Create session if needed
    own_session = session is None
    if own_session:
        session = _build_session()

    try:
        # Discover regular monthly editions
        all_publications: list[DiscoveredPublication] = []

        for month_date in sorted(months_to_probe):
            pubs = discover_publications_for_month(month_date, section_map, session)
            all_publications.extend(pubs)

        # Discover special editions for each day in range
        _log(f"discover: checking {lookback_days} days for special editions")
        current = start_date
        while current <= end_date:
            pubs = discover_special_editions_for_date(current, session)
            all_publications.extend(pubs)
            current += timedelta(days=1)

        # Filter out already-discovered publications
        if registry is not None:
            new_publications: list[DiscoveredPublication] = []
            for pub in all_publications:
                existing = registry.get_publication(
                    pub.section,
                    pub.publication_date,
                    pub.filename,
                )
                if existing is None:
                    new_publications.append(pub)
            _log(f"discover: {len(new_publications)} new publications (filtered from {len(all_publications)})")
            return new_publications
        else:
            _log(f"discover: {len(all_publications)} publications (no registry filtering)")
            return all_publications

    finally:
        if own_session and session:
            session.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Automatically discover new DOU publications",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Discovery mode
    p.add_argument(
        "--days", type=int, default=DEFAULT_DISCOVERY_LOOKBACK_DAYS,
        help=f"Number of days to look back (default: {DEFAULT_DISCOVERY_LOOKBACK_DAYS})",
    )
    p.add_argument(
        "--sections", nargs="+", default=None,
        help="Sections to discover (e.g. do1 do2 do3 do1e). Default: regular sections only",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Discover but don't update registry",
    )
    p.add_argument(
        "--update-registry", action="store_true",
        help="Update discovery registry with new publications",
    )

    # List mode
    p.add_argument(
        "--list", action="store_true",
        help="List discovered publications from registry",
    )
    p.add_argument(
        "--downloaded", action="store_true",
        help="List only downloaded publications (with --list)",
    )
    p.add_argument(
        "--not-downloaded", action="store_true",
        help="List only not-yet-downloaded publications (with --list)",
    )

    # Export mode
    p.add_argument(
        "--export", type=Path, default=None,
        help="Export discovery registry to JSON file",
    )

    # Registry configuration
    p.add_argument(
        "--registry-backend", choices=["postgresql", "sqlite", "memory"],
        default=DEFAULT_REGISTRY_BACKEND,
        help=f"Registry backend (default: {DEFAULT_REGISTRY_BACKEND})",
    )
    p.add_argument(
        "--dsn",
        default=os.environ.get("GABI_DSN", DEFAULT_DSN),
        help="PostgreSQL DSN (for postgresql backend)",
    )
    p.add_argument(
        "--sqlite-path", type=Path, default="data/discovery_registry.db",
        help="SQLite database path (for sqlite backend)",
    )

    args = p.parse_args()

    # Create registry
    if args.registry_backend == "postgresql":
        registry = create_registry("postgresql", dsn=args.dsn)
    elif args.registry_backend == "sqlite":
        registry = create_registry("sqlite", db_path=args.sqlite_path)
    else:
        registry = create_registry("memory")

    try:
        if args.list:
            # List mode
            downloaded = None
            if args.downloaded:
                downloaded = True
            elif args.not_downloaded:
                downloaded = False

            pubs = registry.list_discovered(
                section=args.sections[0] if args.sections and len(args.sections) == 1 else None,
                start_date=date.today() - timedelta(days=args.days),
                end_date=date.today(),
                downloaded=downloaded,
            )

            _log(f"Found {len(pubs)} publications in registry")
            for pub in pubs:
                status = "✓ downloaded" if pub.downloaded else "○ pending"
                size_str = f" ({pub.file_size:,}B)" if pub.file_size else ""
                print(
                    f"{pub.publication_date} {pub.section.upper():6s} "
                    f"{pub.filename:25s} {status}{size_str}"
                )

            # Summary
            total = len(pubs)
            downloaded_count = sum(1 for p in pubs if p.downloaded)
            pending_count = total - downloaded_count
            print(f"\nTotal: {total}, Downloaded: {downloaded_count}, Pending: {pending_count}")

        elif args.export:
            # Export mode
            pubs = registry.list_discovered()
            data = [p.as_dict() for p in pubs]
            args.export.parent.mkdir(parents=True, exist_ok=True)
            args.export.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            _log(f"Exported {len(pubs)} publications to {args.export}")

        else:
            # Discovery mode
            new_pubs = discover_new_publications(
                lookback_days=args.days,
                sections=args.sections,
                registry=registry if not args.dry_run else None,
            )

            _log(f"\nDiscovered {len(new_pubs)} new publications")

            if new_pubs:
                # Print summary
                print("\nNew publications:")
                for pub in new_pubs:
                    size_str = f" ({pub.file_size:,}B)" if pub.file_size else ""
                    print(
                        f"  {pub.publication_date} {pub.section.upper():6s} "
                        f"{pub.filename}{size_str}"
                    )

                # Update registry
                if args.update_registry and not args.dry_run:
                    _log(f"\nUpdating registry with {len(new_pubs)} publications...")
                    for pub in new_pubs:
                        registry.add_publication(pub)
                    _log("Registry updated successfully")
                elif args.dry_run:
                    _log("\nDry run: registry not updated")
                else:
                    _log("\nUse --update-registry to save discoveries to registry")

            else:
                _log("No new publications found")

    finally:
        registry.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
