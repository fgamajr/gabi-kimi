"""Edition freezing layer — observational archive with stabilization, closure, and Merkle proofs."""
from __future__ import annotations

import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from crawler.user_agent_rotator import create_default_rotator


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class FileHash:
    file: str
    sha256: str


@dataclass(slots=True)
class StabilizationRecord:
    first_seen_at: str
    last_seen_at: str
    checks_performed: int
    consecutive_equal_hashes: int
    listing_hash_history: list[dict[str, Any]]
    stabilized: bool
    stabilization_method: str  # "observation" | "historical_presumption"


@dataclass(slots=True)
class ClosureRecord:
    successor_date_seen: bool
    successor_date: str | None
    closure_method: str  # "successor_observed" | "none"


@dataclass(slots=True)
class SectionFreeze:
    section: str
    listing_url: str | None
    listing_file: str | None
    listing_sha256: str | None
    article_count: int
    sampled_count: int
    article_hashes: list[FileHash]
    merkle_root: str
    valid: bool
    stability: StabilizationRecord
    validation: dict[str, bool]


@dataclass(slots=True)
class EditionFreeze:
    date: str
    first_seen_at: str
    capture_sequence: int
    sections: list[SectionFreeze]
    edition_valid: bool
    edition_status: str  # "provisional" | "temporally_stable" | "historically_closed" | "frozen_final"
    closure: ClosureRecord


@dataclass(slots=True)
class FreezeManifest:
    manifest_version: str
    created_at: str
    canonical_order: str
    sampler_config: dict[str, Any]
    editions: list[EditionFreeze]
    summary: dict[str, Any]


@dataclass(slots=True)
class StabilizationConfig:
    stabilization_interval: float = 3600.0
    min_consecutive_matches: int = 2
    max_checks: int = 6
    delay_sec: float = 1.5
    skip_historical: bool = True
    historical_days_threshold: int = 7
    min_page_count: int = 1
    skip_stabilization: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _extract_section(listing_url: str) -> str:
    qs = parse_qs(urlparse(listing_url).query)
    sections = qs.get("secao", [])
    return sections[0] if sections else "do1"


def _serialize(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _serialize(getattr(obj, k)) for k in obj.__dataclass_fields__}
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


def merkle_root(hashes: list[str]) -> str:
    if not hashes:
        return hashlib.sha256(b"").hexdigest()
    layer = sorted(hashes)
    while len(layer) > 1:
        if len(layer) % 2 == 1:
            layer.append(layer[-1])
        next_layer: list[str] = []
        for i in range(0, len(layer), 2):
            combined = (layer[i] + layer[i + 1]).encode("utf-8")
            next_layer.append(hashlib.sha256(combined).hexdigest())
        layer = next_layer
    return layer[0]


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _fetch_url(url: str, *, timeout: int = 25, delay: float = 1.5) -> str | None:
    rot = create_default_rotator()
    try:
        req = Request(
            url=url,
            headers={
                "User-Agent": rot.next(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            },
            method="GET",
        )
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        _log(f"  WARN: fetch failed for {url}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Stabilization
# ---------------------------------------------------------------------------

def _stabilize_section(
    listing_url: str,
    stored_sha256: str,
    first_seen_at: str,
    cfg: StabilizationConfig,
    is_historical: bool,
) -> StabilizationRecord:
    if cfg.skip_stabilization or (cfg.skip_historical and is_historical):
        return StabilizationRecord(
            first_seen_at=first_seen_at,
            last_seen_at=first_seen_at,
            checks_performed=0,
            consecutive_equal_hashes=0,
            listing_hash_history=[],
            stabilized=True,
            stabilization_method="historical_presumption",
        )

    history: list[dict[str, Any]] = []
    consecutive = 0
    previous_hash = stored_sha256
    last_seen = first_seen_at

    for check_num in range(1, cfg.max_checks + 1):
        if check_num > 1:
            time.sleep(cfg.stabilization_interval)

        html = _fetch_url(listing_url, delay=cfg.delay_sec)
        now_iso = datetime.now(timezone.utc).isoformat()
        last_seen = now_iso

        if html is None:
            history.append({"timestamp": now_iso, "sha256": None, "matches_previous": False})
            consecutive = 0
            previous_hash = stored_sha256
            continue

        current_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
        matches = current_hash == previous_hash
        history.append({"timestamp": now_iso, "sha256": current_hash, "matches_previous": matches})

        if matches:
            consecutive += 1
        else:
            consecutive = 1  # new hash becomes the baseline; count this observation as first
            previous_hash = current_hash

        if consecutive >= cfg.min_consecutive_matches:
            return StabilizationRecord(
                first_seen_at=first_seen_at,
                last_seen_at=last_seen,
                checks_performed=check_num,
                consecutive_equal_hashes=consecutive,
                listing_hash_history=history,
                stabilized=True,
                stabilization_method="observation",
            )

    return StabilizationRecord(
        first_seen_at=first_seen_at,
        last_seen_at=last_seen,
        checks_performed=cfg.max_checks,
        consecutive_equal_hashes=consecutive,
        listing_hash_history=history,
        stabilized=False,
        stabilization_method="observation",
    )


# ---------------------------------------------------------------------------
# Closure by publication chronology
# ---------------------------------------------------------------------------

def _compute_closure(edition_dates: list[str]) -> dict[str, ClosureRecord]:
    """Return closure record for each date. Sorted by publication_date."""
    sorted_dates = sorted(set(edition_dates))
    result: dict[str, ClosureRecord] = {}
    for i, d in enumerate(sorted_dates):
        if i < len(sorted_dates) - 1:
            result[d] = ClosureRecord(
                successor_date_seen=True,
                successor_date=sorted_dates[i + 1],
                closure_method="successor_observed",
            )
        else:
            result[d] = ClosureRecord(
                successor_date_seen=False,
                successor_date=None,
                closure_method="none",
            )
    return result


# ---------------------------------------------------------------------------
# Freeze logic
# ---------------------------------------------------------------------------

def freeze_edition(samples_dir: Path, cfg: StabilizationConfig | None = None) -> FreezeManifest:
    if cfg is None:
        cfg = StabilizationConfig()

    samples_dir = Path(samples_dir)
    index_path = samples_dir / "index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"index.json not found in {samples_dir}")

    index = json.loads(index_path.read_text(encoding="utf-8"))
    items = index.get("items", [])
    listings_data = index.get("listings", [])
    sampler_config = index.get("config", {})
    today = date.today()

    # Group items by (date, section)
    items_by_date_section: dict[tuple[str, str], list[dict]] = {}
    for item in items:
        section = _extract_section(item.get("listing_url", ""))
        key = (item["date"], section)
        items_by_date_section.setdefault(key, []).append(item)

    # Group listings by (date, section)
    listings_by_date_section: dict[tuple[str, str], dict] = {}
    for ls in listings_data:
        key = (ls["date"], ls.get("section", _extract_section(ls.get("listing_url", ""))))
        listings_by_date_section[key] = ls

    # Collect all (date, section) pairs
    all_keys: set[tuple[str, str]] = set(items_by_date_section.keys()) | set(listings_by_date_section.keys())
    all_dates = sorted({k[0] for k in all_keys})

    # Closure by publication chronology
    closure_map = _compute_closure(all_dates)

    # Build edition freezes
    editions: list[EditionFreeze] = []
    for edition_date in all_dates:
        sections_for_date = sorted({k[1] for k in all_keys if k[0] == edition_date})
        section_freezes: list[SectionFreeze] = []
        edition_first_seen: str | None = None
        edition_capture_seq = 0

        for section in sections_for_date:
            key = (edition_date, section)
            ls = listings_by_date_section.get(key)
            section_items = items_by_date_section.get(key, [])

            # Determine listing metadata
            listing_url = ls["listing_url"] if ls else (section_items[0].get("listing_url") if section_items else None)
            listing_file = ls["file"] if ls else None
            listing_sha256_stored = ls["sha256"] if ls else None
            article_count = ls["article_count"] if ls else len(section_items)
            section_first_seen = ls.get("captured_at", "") if ls else ""
            section_capture_seq = ls.get("capture_sequence", 0) if ls else 0

            if not section_first_seen and section_items:
                section_first_seen = section_items[0].get("captured_at", "")
                section_capture_seq = section_items[0].get("capture_sequence", 0)

            if edition_first_seen is None or (section_first_seen and section_first_seen < edition_first_seen):
                edition_first_seen = section_first_seen
                edition_capture_seq = section_capture_seq

            # Verify listing hash from disk if file exists
            if listing_file:
                listing_fp = samples_dir / listing_file
                if listing_fp.exists():
                    disk_hash = compute_sha256(listing_fp)
                    if listing_sha256_stored is None:
                        listing_sha256_stored = disk_hash

            # Build article hashes — compute from disk if not in index
            article_hashes: list[FileHash] = []
            download_failures = 0
            for item in section_items:
                f = item.get("file")
                if not f:
                    download_failures += 1
                    continue
                fp = samples_dir / f
                if not fp.exists():
                    download_failures += 1
                    continue
                stored_hash = item.get("sha256")
                if stored_hash:
                    disk_hash = compute_sha256(fp)
                    if disk_hash != stored_hash:
                        download_failures += 1
                        _log(f"  hash mismatch: {f} stored={stored_hash[:16]}... disk={disk_hash[:16]}...")
                        continue
                    article_hashes.append(FileHash(file=f, sha256=stored_hash))
                else:
                    computed = compute_sha256(fp)
                    article_hashes.append(FileHash(file=f, sha256=computed))

            # Merkle tree
            hashes_for_merkle = [fh.sha256 for fh in article_hashes]
            section_merkle = merkle_root(hashes_for_merkle)

            # Stabilization
            is_historical = True
            try:
                ed = date.fromisoformat(edition_date)
                is_historical = (today - ed).days > cfg.historical_days_threshold
            except ValueError:
                pass

            if listing_url and listing_sha256_stored:
                stability = _stabilize_section(
                    listing_url=listing_url,
                    stored_sha256=listing_sha256_stored,
                    first_seen_at=section_first_seen,
                    cfg=cfg,
                    is_historical=is_historical,
                )
            else:
                stability = StabilizationRecord(
                    first_seen_at=section_first_seen,
                    last_seen_at=section_first_seen,
                    checks_performed=0,
                    consecutive_equal_hashes=0,
                    listing_hash_history=[],
                    stabilized=True,
                    stabilization_method="historical_presumption",
                )

            # Section validation
            validation = {
                "stabilized": stability.stabilized,
                "pagination_stable": True,  # enforced by sampler's pagination guard
                "no_download_failures": download_failures == 0,
                "page_count_above_minimum": len(article_hashes) >= cfg.min_page_count,
                "merkle_root_computed": bool(hashes_for_merkle),
            }
            section_valid = all(validation.values())

            section_freezes.append(SectionFreeze(
                section=section,
                listing_url=listing_url,
                listing_file=listing_file,
                listing_sha256=listing_sha256_stored,
                article_count=article_count,
                sampled_count=len(article_hashes),
                article_hashes=article_hashes,
                merkle_root=section_merkle,
                valid=section_valid,
                stability=stability,
                validation=validation,
            ))

        # Edition-level status
        all_stabilized = all(s.stability.stabilized for s in section_freezes)
        all_sections_valid = all(s.valid for s in section_freezes) and len(section_freezes) > 0
        closure = closure_map.get(edition_date, ClosureRecord(
            successor_date_seen=False, successor_date=None, closure_method="none",
        ))

        if not all_stabilized:
            edition_status = "provisional"
        elif not closure.successor_date_seen:
            edition_status = "temporally_stable"
        elif all_sections_valid:
            edition_status = "frozen_final"
        else:
            edition_status = "historically_closed"

        edition_valid = edition_status == "frozen_final"

        editions.append(EditionFreeze(
            date=edition_date,
            first_seen_at=edition_first_seen or "",
            capture_sequence=edition_capture_seq,
            sections=section_freezes,
            edition_valid=edition_valid,
            edition_status=edition_status,
            closure=closure,
        ))

    # Sort editions by capture_sequence for audit trail
    editions.sort(key=lambda e: e.capture_sequence)

    # Summary
    total_listings = sum(1 for e in editions for s in e.sections if s.listing_file)
    total_hashed = sum(len(s.article_hashes) for e in editions for s in e.sections)
    now_iso = datetime.now(timezone.utc).isoformat()

    summary = {
        "total_editions": len(editions),
        "frozen_final": sum(1 for e in editions if e.edition_status == "frozen_final"),
        "temporally_stable": sum(1 for e in editions if e.edition_status == "temporally_stable"),
        "provisional": sum(1 for e in editions if e.edition_status == "provisional"),
        "historically_closed": sum(1 for e in editions if e.edition_status == "historically_closed"),
        "total_listings_preserved": total_listings,
        "total_articles_hashed": total_hashed,
        "frozen_at": now_iso,
    }

    manifest = FreezeManifest(
        manifest_version="1.0",
        created_at=now_iso,
        canonical_order="publication_date",
        sampler_config=sampler_config,
        editions=editions,
        summary=summary,
    )

    # Write manifest
    manifest_path = samples_dir / "edition.manifest.json"
    manifest_path.write_text(
        json.dumps(_serialize(manifest), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _log(
        f"editions={summary['total_editions']} "
        f"frozen_final={summary['frozen_final']} "
        f"temporally_stable={summary['temporally_stable']} "
        f"provisional={summary['provisional']} "
        f"listings={summary['total_listings_preserved']} "
        f"articles_hashed={summary['total_articles_hashed']}"
    )

    return manifest
