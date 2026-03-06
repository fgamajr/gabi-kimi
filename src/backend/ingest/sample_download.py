"""Sample and download 200 ZIPs from the full DOU catalog (851 files).

Workflow:
    1. Build full catalog (851 deterministic URLs) from registry JSON
    2. Sample N ZIPs uniformly (reproducible seed)
    3. Persist job state as JSON (pending → downloading → done / failed)
    4. Download concurrently with ThreadPoolExecutor
    5. Extract + analyze XMLs and images per ZIP

Usage:
    # Generate catalog + sample 200 + download + analyze
    python -m src.backend.ingest.sample_download --sample 200 --seed 42 --workers 4

    # Resume interrupted download (reads existing job state)
    python -m src.backend.ingest.sample_download --resume

    # Just generate catalog + sample (no download)
    python -m src.backend.ingest.sample_download --sample 200 --seed 42 --plan-only

    # Analyze already-downloaded ZIPs
    python -m src.backend.ingest.sample_download --analyze-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GROUP_ID = "49035712"
BASE_DOCUMENT_URL = "https://www.in.gov.br/documents"
DEFAULT_REGISTRY = Path("ops/data/dou_catalog_registry.json")
DEFAULT_OUTPUT = Path("ops/data/sample200")
JOB_STATE_FILE = "job_state.json"
ANALYSIS_FILE = "analysis.json"

_USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/145.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
]

_XML_EXTENSIONS = frozenset({".xml"})
_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _build_session(max_retries: int = 3) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=max_retries,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Step 1: Build full catalog (deterministic, zero HTTP)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CatalogEntry:
    """One downloadable ZIP in the full catalog."""
    month: str          # 2002-01
    filename: str       # S01012002.zip
    folder_id: int      # 50300469
    url: str            # full download URL
    section: str        # do1, do2, do3 (inferred)

    def to_dict(self) -> dict[str, Any]:
        return {
            "month": self.month,
            "filename": self.filename,
            "folder_id": self.folder_id,
            "url": self.url,
            "section": self.section,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> CatalogEntry:
        return CatalogEntry(**d)


def _infer_section(filename: str) -> str:
    """Infer section code from filename: S01→do1, S02→do2, S03→do3."""
    base = filename.split("_")[0].replace(".zip", "")
    if base.startswith("S01"):
        return "do1"
    if base.startswith("S02"):
        return "do2"
    if base.startswith("S03"):
        return "do3"
    return "unknown"


def build_full_catalog(registry_path: Path = DEFAULT_REGISTRY) -> list[CatalogEntry]:
    """Build all 851 download targets deterministically from the registry."""
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    folder_ids = data.get("folder_ids", {})
    files = data.get("files", {})

    catalog: list[CatalogEntry] = []
    for month_key in sorted(files.keys()):
        fid = folder_ids.get(month_key)
        if not fid:
            continue
        for fname in files[month_key]:
            url = f"{BASE_DOCUMENT_URL}/{GROUP_ID}/{fid}/{fname}"
            catalog.append(CatalogEntry(
                month=month_key,
                filename=fname,
                folder_id=int(fid),
                url=url,
                section=_infer_section(fname),
            ))
    return catalog


# ---------------------------------------------------------------------------
# Step 2: Sample N entries uniformly
# ---------------------------------------------------------------------------

def sample_catalog(
    catalog: list[CatalogEntry],
    n: int = 200,
    seed: int = 42,
) -> list[CatalogEntry]:
    """Sample N entries from the catalog with a reproducible seed."""
    rng = random.Random(seed)
    if n >= len(catalog):
        return list(catalog)
    return rng.sample(catalog, n)


# ---------------------------------------------------------------------------
# Step 3: Job state management
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class JobEntry:
    """Tracks one ZIP through the download pipeline."""
    idx: int
    month: str
    filename: str
    url: str
    section: str
    status: str = "pending"    # pending → downloading → done | failed
    local_path: str | None = None
    size_bytes: int = 0
    sha256: str | None = None
    download_ms: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "idx": self.idx,
            "month": self.month,
            "filename": self.filename,
            "url": self.url,
            "section": self.section,
            "status": self.status,
            "local_path": self.local_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "download_ms": self.download_ms,
            "error": self.error,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> JobEntry:
        return JobEntry(**{k: v for k, v in d.items() if k in JobEntry.__slots__})


def create_job_state(
    sampled: list[CatalogEntry],
    output_dir: Path,
    full_catalog_size: int,
    seed: int,
) -> list[JobEntry]:
    """Create initial job state with all entries as pending."""
    entries = []
    for i, entry in enumerate(sampled):
        entries.append(JobEntry(
            idx=i,
            month=entry.month,
            filename=entry.filename,
            url=entry.url,
            section=entry.section,
        ))

    _save_job_state(entries, output_dir, full_catalog_size, seed)
    return entries


def _save_job_state(
    entries: list[JobEntry],
    output_dir: Path,
    full_catalog_size: int = 851,
    seed: int = 42,
) -> None:
    """Persist job state to JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "created": datetime.now().isoformat(),
        "full_catalog_size": full_catalog_size,
        "sample_size": len(entries),
        "seed": seed,
        "counts": {
            "pending": sum(1 for e in entries if e.status == "pending"),
            "downloading": sum(1 for e in entries if e.status == "downloading"),
            "done": sum(1 for e in entries if e.status == "done"),
            "failed": sum(1 for e in entries if e.status == "failed"),
        },
        "total_bytes": sum(e.size_bytes for e in entries if e.status == "done"),
        "entries": [e.to_dict() for e in entries],
    }
    path = output_dir / JOB_STATE_FILE
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def load_job_state(output_dir: Path) -> list[JobEntry]:
    """Load job state from JSON."""
    path = output_dir / JOB_STATE_FILE
    if not path.exists():
        raise FileNotFoundError(f"No job state at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return [JobEntry.from_dict(e) for e in data["entries"]]


# ---------------------------------------------------------------------------
# Step 4: Concurrent download
# ---------------------------------------------------------------------------

def _download_one(
    entry: JobEntry,
    output_dir: Path,
    session: requests.Session,
    timeout: int = 120,
) -> JobEntry:
    """Download a single ZIP. Mutates and returns the entry."""
    # Local filename: {month}_{section}_{filename} for uniqueness
    local_name = f"{entry.month}_{entry.section}_{entry.filename}"
    local_path = output_dir / "zips" / local_name

    # Skip if already exists
    if local_path.exists() and local_path.stat().st_size > 0:
        entry.status = "done"
        entry.local_path = str(local_path)
        entry.size_bytes = local_path.stat().st_size
        entry.sha256 = _file_sha256(local_path)
        entry.download_ms = 0
        return entry

    entry.status = "downloading"
    local_path.parent.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    try:
        ua = random.choice(_USER_AGENTS)
        resp = session.get(
            entry.url,
            headers={"User-Agent": ua},
            timeout=timeout,
            stream=True,
        )

        if resp.status_code == 404:
            entry.status = "failed"
            entry.error = "HTTP 404"
            return entry

        resp.raise_for_status()

        h = hashlib.sha256()
        size = 0
        with open(local_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
                h.update(chunk)
                size += len(chunk)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        entry.status = "done"
        entry.local_path = str(local_path)
        entry.size_bytes = size
        entry.sha256 = h.hexdigest()
        entry.download_ms = elapsed_ms

    except Exception as ex:
        entry.status = "failed"
        entry.error = str(ex)[:200]
        # Clean up partial file
        if local_path.exists():
            local_path.unlink(missing_ok=True)

    return entry


def download_all(
    entries: list[JobEntry],
    output_dir: Path,
    workers: int = 4,
    full_catalog_size: int = 851,
    seed: int = 42,
    save_interval: int = 10,
) -> list[JobEntry]:
    """Download all pending entries concurrently.

    Saves job state every `save_interval` completions for resume support.
    """
    pending = [e for e in entries if e.status in ("pending", "downloading")]
    if not pending:
        _log("Nothing to download — all entries are done or failed")
        return entries

    _log(f"Downloading {len(pending)} ZIPs with {workers} workers...")

    session = _build_session()
    completed = 0
    total_bytes = sum(e.size_bytes for e in entries if e.status == "done")

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_download_one, entry, output_dir, session): entry
                for entry in pending
            }

            for future in as_completed(futures):
                entry = future.result()
                completed += 1

                if entry.status == "done":
                    total_bytes += entry.size_bytes
                    mb = entry.size_bytes / 1024 / 1024
                    _log(
                        f"[{completed}/{len(pending)}] ✓ {entry.filename} "
                        f"({mb:.1f} MB, {entry.download_ms}ms) "
                        f"total: {total_bytes/1024/1024:.0f} MB"
                    )
                else:
                    _log(
                        f"[{completed}/{len(pending)}] ✗ {entry.filename}: {entry.error}"
                    )

                # Periodic save
                if completed % save_interval == 0:
                    _save_job_state(entries, output_dir, full_catalog_size, seed)

    finally:
        session.close()
        _save_job_state(entries, output_dir, full_catalog_size, seed)

    done = sum(1 for e in entries if e.status == "done")
    failed = sum(1 for e in entries if e.status == "failed")
    _log(f"Download complete: {done} done, {failed} failed, {total_bytes/1024/1024:.0f} MB total")
    return entries


# ---------------------------------------------------------------------------
# Step 5: Extract + Analyze
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ZIPAnalysis:
    """Analysis results for one ZIP file."""
    filename: str
    month: str
    section: str
    size_bytes: int
    xml_count: int = 0
    image_count: int = 0
    other_count: int = 0
    parse_ok: int = 0
    parse_errors: int = 0
    unique_pub_names: list[str] = field(default_factory=list)
    unique_art_types: list[str] = field(default_factory=list)
    date_range: str = ""
    sample_articles: list[dict] = field(default_factory=list)
    image_extensions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "month": self.month,
            "section": self.section,
            "size_bytes": self.size_bytes,
            "xml_count": self.xml_count,
            "image_count": self.image_count,
            "other_count": self.other_count,
            "parse_ok": self.parse_ok,
            "parse_errors": self.parse_errors,
            "unique_pub_names": self.unique_pub_names,
            "unique_art_types": self.unique_art_types,
            "date_range": self.date_range,
            "sample_articles": self.sample_articles,
            "image_extensions": self.image_extensions,
            "errors": self.errors,
        }


def analyze_zip(zip_path: Path, month: str, section: str) -> ZIPAnalysis:
    """Analyze a downloaded ZIP: count XMLs, images, parse samples."""
    from src.backend.ingest.xml_parser import INLabsXMLParser, XMLParseError

    analysis = ZIPAnalysis(
        filename=zip_path.name,
        month=month,
        section=section,
        size_bytes=zip_path.stat().st_size,
    )

    parser = INLabsXMLParser()
    pub_names: set[str] = set()
    art_types: Counter[str] = Counter()
    dates: set[str] = set()
    image_exts: Counter[str] = Counter()

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                suffix = Path(info.filename).suffix.lower()
                if suffix in _XML_EXTENSIONS:
                    analysis.xml_count += 1
                elif suffix in _IMAGE_EXTENSIONS:
                    analysis.image_count += 1
                    image_exts[suffix] += 1
                else:
                    analysis.other_count += 1

            # Parse a sample of XMLs (up to 50 for speed)
            xml_members = [
                info for info in zf.infolist()
                if not info.is_dir() and Path(info.filename).suffix.lower() in _XML_EXTENSIONS
            ]
            sample_size = min(50, len(xml_members))
            if sample_size < len(xml_members):
                rng = random.Random(42)
                xml_sample = rng.sample(xml_members, sample_size)
            else:
                xml_sample = xml_members

            for info in xml_sample:
                try:
                    raw = zf.read(info.filename)
                    text = raw.decode("utf-8-sig", errors="replace")
                    article = parser.parse_string(text)
                    analysis.parse_ok += 1
                    pub_names.add(article.pub_name)
                    art_types[article.art_type] += 1
                    if article.pub_date:
                        dates.add(article.pub_date)

                    # Save first 3 as samples
                    if len(analysis.sample_articles) < 3:
                        analysis.sample_articles.append({
                            "id": article.id,
                            "id_materia": article.id_materia,
                            "pub_name": article.pub_name,
                            "pub_date": article.pub_date,
                            "art_type": article.art_type,
                            "art_category": article.art_category[:80],
                            "identifica": article.identifica[:120],
                            "has_texto": bool(article.texto),
                            "texto_len": len(article.texto),
                        })

                except (XMLParseError, Exception) as ex:
                    analysis.parse_errors += 1
                    if len(analysis.errors) < 5:
                        analysis.errors.append(f"{info.filename}: {str(ex)[:100]}")

    except zipfile.BadZipFile as ex:
        analysis.errors.append(f"bad zip: {ex}")
    except Exception as ex:
        analysis.errors.append(f"open error: {ex}")

    analysis.unique_pub_names = sorted(pub_names)
    analysis.unique_art_types = [t for t, _ in art_types.most_common(15)]
    analysis.image_extensions = [f"{ext}:{n}" for ext, n in image_exts.most_common()]

    if dates:
        analysis.date_range = f"{min(dates)} → {max(dates)}"

    return analysis


def analyze_all(
    entries: list[JobEntry],
    output_dir: Path,
) -> list[ZIPAnalysis]:
    """Analyze all successfully downloaded ZIPs."""
    done = [e for e in entries if e.status == "done" and e.local_path]
    _log(f"Analyzing {len(done)} ZIPs...")

    results: list[ZIPAnalysis] = []
    for i, entry in enumerate(done, 1):
        path = Path(entry.local_path)
        if not path.exists():
            continue
        analysis = analyze_zip(path, entry.month, entry.section)
        results.append(analysis)
        if i % 20 == 0 or i == len(done):
            _log(f"  analyzed {i}/{len(done)}")

    # Save analysis
    total_xmls = sum(a.xml_count for a in results)
    total_images = sum(a.image_count for a in results)
    total_parsed = sum(a.parse_ok for a in results)
    total_errors = sum(a.parse_errors for a in results)
    total_bytes = sum(a.size_bytes for a in results)

    # Aggregate stats
    all_pub_names: Counter[str] = Counter()
    all_art_types: Counter[str] = Counter()
    year_dist: Counter[str] = Counter()
    section_dist: Counter[str] = Counter()
    for a in results:
        for pn in a.unique_pub_names:
            all_pub_names[pn] += 1
        for at in a.unique_art_types:
            all_art_types[at] += 1
        year_dist[a.month[:4]] += 1
        section_dist[a.section] += 1

    report = {
        "summary": {
            "zips_analyzed": len(results),
            "total_bytes": total_bytes,
            "total_mb": round(total_bytes / 1024 / 1024, 1),
            "total_xml_files": total_xmls,
            "total_image_files": total_images,
            "parsed_ok": total_parsed,
            "parse_errors": total_errors,
            "parse_rate": f"{total_parsed/(total_parsed+total_errors)*100:.1f}%" if (total_parsed + total_errors) > 0 else "N/A",
        },
        "distributions": {
            "pub_names": dict(all_pub_names.most_common()),
            "art_types_top20": dict(all_art_types.most_common(20)),
            "by_year": dict(sorted(year_dist.items())),
            "by_section": dict(sorted(section_dist.items())),
        },
        "per_zip": [a.to_dict() for a in results],
    }

    analysis_path = output_dir / ANALYSIS_FILE
    analysis_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _log(f"Analysis saved to {analysis_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("ANALYSIS SUMMARY")
    print("=" * 60)
    print(f"ZIPs analyzed:   {len(results)}")
    print(f"Total size:      {total_bytes/1024/1024:.0f} MB")
    print(f"XML files:       {total_xmls:,}")
    print(f"Image files:     {total_images:,}")
    print(f"Parse OK:        {total_parsed:,}")
    print(f"Parse errors:    {total_errors:,}")
    print(f"\npubName values:  {dict(all_pub_names.most_common())}")
    print(f"\nTop 10 artTypes: {dict(all_art_types.most_common(10))}")
    print(f"\nBy year:         {dict(sorted(year_dist.items()))}")
    print(f"By section:      {dict(sorted(section_dist.items()))}")
    print("=" * 60)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Sample and download DOU ZIPs for analysis",
    )
    p.add_argument("--sample", type=int, default=200, help="Number of ZIPs to sample (default: 200)")
    p.add_argument("--seed", type=int, default=42, help="Random seed for reproducible sampling")
    p.add_argument("--workers", type=int, default=4, help="Concurrent download workers (default: 4)")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output directory")
    p.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY, help="Registry JSON path")
    p.add_argument("--resume", action="store_true", help="Resume from existing job state")
    p.add_argument("--plan-only", action="store_true", help="Generate catalog + sample, no download")
    p.add_argument("--analyze-only", action="store_true", help="Only analyze already-downloaded ZIPs")
    p.add_argument("--timeout", type=int, default=120, help="HTTP timeout per file (seconds)")
    args = p.parse_args()

    output_dir = args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    # -- Resume mode --
    if args.resume or args.analyze_only:
        entries = load_job_state(output_dir)
        _log(f"Loaded job state: {len(entries)} entries")

        if args.analyze_only:
            analyze_all(entries, output_dir)
            return 0

        # Resume downloads
        entries = download_all(
            entries, output_dir,
            workers=args.workers,
        )
        analyze_all(entries, output_dir)
        return 0

    # -- Fresh run --
    _log(f"Building full catalog from {args.registry}...")
    catalog = build_full_catalog(args.registry)
    _log(f"Full catalog: {len(catalog)} ZIPs across {len(set(e.month for e in catalog))} months")

    # Save full catalog
    catalog_path = output_dir / "full_catalog.json"
    catalog_path.write_text(
        json.dumps([e.to_dict() for e in catalog], indent=2), encoding="utf-8"
    )
    _log(f"Full catalog saved to {catalog_path}")

    # Sample
    sampled = sample_catalog(catalog, n=args.sample, seed=args.seed)
    _log(f"Sampled {len(sampled)} ZIPs (seed={args.seed})")

    # Year distribution of sample
    year_dist = Counter(e.month[:4] for e in sampled)
    _log(f"Sample by year: {dict(sorted(year_dist.items()))}")

    # Create job state
    entries = create_job_state(sampled, output_dir, len(catalog), args.seed)
    _log(f"Job state created: {len(entries)} pending")

    if args.plan_only:
        _log("Plan-only mode — not downloading")
        return 0

    # Download
    entries = download_all(
        entries, output_dir,
        workers=args.workers,
        full_catalog_size=len(catalog),
        seed=args.seed,
    )

    # Analyze
    analyze_all(entries, output_dir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
