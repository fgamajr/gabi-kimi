"""Evidence capture layer — DOU listing page freezer.

Downloads listing pages for do1, do2, do3 sections for each date in range.
Stores raw HTML bytes exactly as received from the server.
Computes sha256 of the unmodified response. Writes manifest.json per date.

No bytes are modified after receipt. This is the evidentiary record.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from datetime import date
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from harvest.date_selector import DateRange

log = logging.getLogger(__name__)

SECTIONS = ("do1", "do2", "do3")
BASE_URL = "https://www.in.gov.br/leiturajornal"
TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Connection": "close",
}


def _build_url(d: date, section: str) -> str:
    """Build deterministic DOU listing URL for a date and section."""
    return f"{BASE_URL}?data={d.strftime('%d-%m-%Y')}&secao={section}"


def _download(url: str) -> bytes:
    """Download URL and return raw bytes. Rejects cross-domain redirects."""
    req = Request(url, headers=_HEADERS)
    with urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        final = urlparse(resp.url)
        requested = urlparse(url)
        if (final.scheme, final.netloc) != (requested.scheme, requested.netloc):
            raise URLError(f"redirected to untrusted URL: {resp.url}")
        if final.path.rstrip("/") != requested.path.rstrip("/"):
            raise URLError(f"redirected to unexpected path: {resp.url}")
        if parse_qs(final.query) != parse_qs(requested.query):
            raise URLError(f"redirected with altered query: {resp.url}")
        status = getattr(resp, "status", 200)
        if status != 200:
            raise URLError(f"unexpected HTTP status: {status}")
        data = resp.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise URLError(f"response exceeds {MAX_RESPONSE_BYTES} bytes")
        return data


def _sha256(data: bytes) -> str:
    """Return hex sha256 of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes atomically via tmp + rename."""
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=path.name + ".", suffix=".tmp"
    )
    closed = False
    try:
        mv = memoryview(data)
        while mv:
            n = os.write(fd, mv)
            mv = mv[n:]
        os.fsync(fd)
        os.close(fd)
        closed = True
        os.replace(tmp_name, path)
    except BaseException:
        if not closed:
            os.close(fd)
        try:
            Path(tmp_name).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _atomic_write_text(path: Path, text: str) -> None:
    """Write text atomically via tmp + rename."""
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=path.name + ".", suffix=".tmp"
    )
    closed = False
    try:
        encoded = text.encode("utf-8")
        mv = memoryview(encoded)
        while mv:
            n = os.write(fd, mv)
            mv = mv[n:]
        os.fsync(fd)
        os.close(fd)
        closed = True
        os.replace(tmp_name, path)
    except BaseException:
        if not closed:
            os.close(fd)
        try:
            Path(tmp_name).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def freeze_date(d: date, output_dir: Path) -> dict:
    """Freeze all listing pages for a single date.

    Creates: output_dir/YYYY-MM-DD/{section}.html + manifest.json
    Returns the manifest dict. Raw bytes are stored unmodified.
    """
    day_dir = output_dir / d.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []

    for section in SECTIONS:
        url = _build_url(d, section)
        filename = f"{section}.html"
        filepath = day_dir / filename

        log.info("fetching %s %s", d.isoformat(), section)

        try:
            raw = _download(url)
        except (URLError, OSError) as exc:
            log.error("failed %s %s: %s", d.isoformat(), section, exc)
            results.append({
                "error": str(exc),
                "filename": filename,
                "section": section,
                "sha256": None,
                "size_bytes": 0,
                "url": url,
            })
            continue

        digest = _sha256(raw)
        try:
            _atomic_write_bytes(filepath, raw)
        except OSError as exc:
            log.error("write failed %s %s: %s", d.isoformat(), section, exc)
            results.append({
                "error": str(exc),
                "filename": filename,
                "section": section,
                "sha256": None,
                "size_bytes": 0,
                "url": url,
            })
            continue

        results.append({
            "filename": filename,
            "section": section,
            "sha256": digest,
            "size_bytes": len(raw),
            "url": url,
        })

        log.info("stored %s %s (%d bytes, %s)", d.isoformat(), section, len(raw), digest[:12])

    manifest = {
        "date": d.isoformat(),
        "sections": results,
    }

    manifest_path = day_dir / "manifest.json"
    _atomic_write_text(
        manifest_path,
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )

    return manifest


def freeze_range(start: date, end: date, output_dir: Path) -> list[dict]:
    """Freeze all listing pages for a date range.

    Returns list of per-date manifests.
    """
    dr = DateRange(start, end)
    dates = dr.dates()
    output_dir.mkdir(parents=True, exist_ok=True)

    manifests: list[dict] = []
    for d in dates:
        manifest = freeze_date(d, output_dir)
        manifests.append(manifest)

    top_manifest = {
        "dates": [d.isoformat() for d in dates],
        "end": end.isoformat(),
        "expected_sections": len(SECTIONS) * len(dates),
        "start": start.isoformat(),
        "total_dates": len(dates),
    }
    top_path = output_dir / "manifest.json"
    _atomic_write_text(
        top_path,
        json.dumps(top_manifest, indent=2, sort_keys=True) + "\n",
    )

    return manifests
