"""ZIP downloader for DOU publications from in.gov.br.

Downloads daily ZIP bundles containing XML files for each DOU section.
URL pattern:
    https://www.in.gov.br/documents/{GROUP_ID}/{FOLDER_ID}/S0{section}{ddmmyyyy}.zip

TODO:
    - Discover whether folderId is static or date-dependent
    - Implement folder enumeration via Liferay REST API
    - Detect special/extra editions (DO1E, DO2E, DO3E)
    - Implement incremental download (skip already-ingested dates)
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ingest.date_selector import DateRange


# ---------------------------------------------------------------------------
# Constants — Liferay document library coordinates
# ---------------------------------------------------------------------------

GROUP_ID = "49035712"
FOLDER_ID = "685674076"       # May be static; needs validation across dates
BASE_URL = f"https://www.in.gov.br/documents/{GROUP_ID}/{FOLDER_ID}"

SECTIONS: dict[str, str] = {
    "do1": "S01",
    "do2": "S02",
    "do3": "S03",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ZIPTarget:
    """A single ZIP to download."""
    section: str          # do1, do2, do3
    pub_date: date
    url: str
    filename: str

    @property
    def date_str(self) -> str:
        return self.pub_date.strftime("%d%m%Y")


@dataclass(slots=True)
class DownloadManifest:
    """Tracks a batch of downloads."""
    targets: list[ZIPTarget] = field(default_factory=list)
    downloaded: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# URL generation
# ---------------------------------------------------------------------------

def build_zip_url(section: str, pub_date: date) -> ZIPTarget:
    """Build the ZIP download URL for a given section and date.

    Args:
        section: Section code (do1, do2, do3)
        pub_date: Publication date

    Returns:
        ZIPTarget with URL and filename
    """
    prefix = SECTIONS.get(section)
    if prefix is None:
        raise ValueError(f"Unknown section: {section}. Expected one of {list(SECTIONS)}")

    date_str = pub_date.strftime("%d%m%Y")
    filename = f"{prefix}{date_str}.zip"
    url = f"{BASE_URL}/{filename}"

    return ZIPTarget(
        section=section,
        pub_date=pub_date,
        url=url,
        filename=filename,
    )


def build_targets(date_range: DateRange, sections: list[str] | None = None) -> list[ZIPTarget]:
    """Generate download targets for a date range and sections.

    Args:
        date_range: Start/end dates
        sections: Sections to download (default: all three)

    Returns:
        List of ZIPTarget objects
    """
    if sections is None:
        sections = list(SECTIONS)

    targets: list[ZIPTarget] = []
    current = date_range.start
    while current <= date_range.end:
        for section in sections:
            targets.append(build_zip_url(section, current))
        from datetime import timedelta
        current += timedelta(days=1)

    return targets


def write_manifest(manifest: DownloadManifest, outdir: Path) -> Path:
    """Write download manifest to JSON file.

    Args:
        manifest: Completed manifest
        outdir: Output directory

    Returns:
        Path to manifest file
    """
    outdir.mkdir(parents=True, exist_ok=True)
    manifest_path = outdir / "download_manifest.json"

    data = {
        "total_targets": len(manifest.targets),
        "downloaded": len(manifest.downloaded),
        "failed": len(manifest.failed),
        "targets": [
            {
                "section": t.section,
                "date": t.pub_date.isoformat(),
                "url": t.url,
                "filename": t.filename,
            }
            for t in manifest.targets
        ],
        "failed_urls": manifest.failed,
    }

    manifest_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def file_sha256(filepath: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
