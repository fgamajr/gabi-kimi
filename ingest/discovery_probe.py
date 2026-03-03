"""Discovery probe — validate DOU public endpoint URL patterns across years.

Generates random sample dates from 2016-2026, probes multiple URL pattern
hypotheses (monthly vs daily), queries the tags API for special editions,
and downloads confirmed-existing ZIPs.

Usage:
    python -m ingest.discovery_probe --sample 200 --download --output data/discovery
    python -m ingest.discovery_probe --sample 200 --probe-only
    python -m ingest.discovery_probe --sample 50 --probe-only --verbose
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GROUP_ID = "49035712"
FOLDER_ID = "685674076"
BASE_URL = f"https://www.in.gov.br/documents/{GROUP_ID}/{FOLDER_ID}"
TAGS_API_URL = "https://www.in.gov.br/o/tagsRest/tags/getTags"

# Section prefix map (same as zip_downloader)
SECTIONS: dict[str, str] = {
    "do1": "S01",
    "do2": "S02",
    "do3": "S03",
}

EXTRA_SECTIONS: dict[str, str] = {
    "do1e":  "S01E",
    "do2e":  "S02E",
    "do3e":  "S03E",
    "do1esp": "S01ESP",
    "do2esp": "S02ESP",
    "do1a":  "S01A",
}

ALL_SECTIONS: dict[str, str] = {**SECTIONS, **EXTRA_SECTIONS}

# URL pattern hypotheses to test
# Each generates (url, pattern_name) from (prefix, date)
def _monthly_url(prefix: str, d: date) -> str:
    """S{prefix}{MMYYYY}.zip — monthly archive hypothesis."""
    return f"{BASE_URL}/{prefix}{d.strftime('%m%Y')}.zip"

def _daily_url(prefix: str, d: date) -> str:
    """S{prefix}{DDMMYYYY}.zip — daily archive hypothesis."""
    return f"{BASE_URL}/{prefix}{d.strftime('%d%m%Y')}.zip"

def _daily_dash_url(prefix: str, d: date) -> str:
    """S{prefix}-{YYYY-MM-DD}.zip — dashed daily hypothesis."""
    return f"{BASE_URL}/{prefix}-{d.isoformat()}.zip"

def _daily_v2_url(prefix: str, d: date) -> str:
    """S{prefix}{YYYYMMDD}.zip — ISO daily hypothesis."""
    return f"{BASE_URL}/{prefix}{d.strftime('%Y%m%d')}.zip"


URL_PATTERNS: dict[str, Any] = {
    "monthly":     _monthly_url,      # S01012026.zip = Jan2026
    "daily_ddmm":  _daily_url,        # S0101012026.zip = 01Jan2026
    "daily_dash":  _daily_dash_url,   # S01-2026-01-01.zip
    "daily_iso":   _daily_v2_url,     # S0120260101.zip
}

# User-Agent rotation
_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ProbeResult:
    """Result of probing a single URL."""
    date: date
    section: str
    pattern: str
    url: str
    status_code: int
    content_length: int | None = None
    content_type: str | None = None
    redirect_url: str | None = None
    elapsed_ms: int = 0
    error: str | None = None

    @property
    def found(self) -> bool:
        return self.status_code == 200

    @property
    def is_redirect(self) -> bool:
        return self.status_code in (301, 302, 303, 307, 308)

    def as_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "section": self.section,
            "pattern": self.pattern,
            "url": self.url,
            "status": self.status_code,
            "content_length": self.content_length,
            "content_type": self.content_type,
            "redirect_url": self.redirect_url,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
        }


@dataclass(slots=True)
class TagsResult:
    """Result of querying the tags API for one date."""
    date: date
    flags: dict[str, bool]
    raw: dict[str, Any] | None = None
    error: str | None = None
    status_code: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "flags": self.flags,
            "has_any_extra": any(self.flags.values()),
            "error": self.error,
            "status_code": self.status_code,
        }


@dataclass(slots=True)
class DiscoveryReport:
    """Aggregated discovery results."""
    sample_dates: list[date]
    probe_results: list[ProbeResult] = field(default_factory=list)
    tags_results: list[TagsResult] = field(default_factory=list)
    downloaded: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_VERBOSE = False

def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)

def _debug(msg: str) -> None:
    if _VERBOSE:
        print(f"  [debug] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _build_session(max_retries: int = 2) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=max_retries,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _random_ua() -> str:
    return random.choice(_USER_AGENTS)


# ---------------------------------------------------------------------------
# Date sampling
# ---------------------------------------------------------------------------

def sample_dates(
    n: int,
    start: date = date(2016, 1, 1),
    end: date = date(2026, 3, 3),
    seed: int = 42,
) -> list[date]:
    """Pick n random dates from [start, end] inclusive."""
    rng = random.Random(seed)
    total_days = (end - start).days + 1
    if n >= total_days:
        return [start + timedelta(days=i) for i in range(total_days)]
    day_offsets = sorted(rng.sample(range(total_days), n))
    return [start + timedelta(days=d) for d in day_offsets]


def unique_months(dates: list[date]) -> list[date]:
    """Return one date per unique (year, month) from the list — the 1st of each month."""
    seen: set[tuple[int, int]] = set()
    result: list[date] = []
    for d in sorted(dates):
        key = (d.year, d.month)
        if key not in seen:
            seen.add(key)
            result.append(d.replace(day=1))
    return result


# ---------------------------------------------------------------------------
# Tags API probe
# ---------------------------------------------------------------------------

def probe_tags_api(
    dates: list[date],
    session: requests.Session,
    delay: float = 0.3,
) -> list[TagsResult]:
    """Query the tags API for each date."""
    results: list[TagsResult] = []

    for idx, d in enumerate(dates, start=1):
        if idx % 20 == 0:
            _log(f"tags [{idx}/{len(dates)}] ...")

        try:
            resp = session.get(
                TAGS_API_URL,
                params={"date": d.isoformat()},
                headers={
                    "User-Agent": _random_ua(),
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=15,
            )

            if resp.status_code != 200:
                results.append(TagsResult(
                    date=d, flags={}, error=f"HTTP {resp.status_code}",
                    status_code=resp.status_code,
                ))
                _debug(f"tags {d}: HTTP {resp.status_code}")
            else:
                data = resp.json()
                raw = data
                # Navigate Liferay wrapper
                if isinstance(data, dict):
                    if "serializable" in data:
                        flags_raw = data["serializable"].get("jsonObject", data["serializable"])
                    elif "jsonObject" in data:
                        flags_raw = data["jsonObject"]
                    else:
                        flags_raw = data
                else:
                    flags_raw = {}

                flags = {k: bool(v) for k, v in flags_raw.items()
                         if isinstance(v, bool)}
                results.append(TagsResult(
                    date=d, flags=flags, raw=raw,
                    status_code=resp.status_code,
                ))

                active = [k for k, v in flags.items() if v]
                if active:
                    _debug(f"tags {d}: {active}")

        except Exception as ex:
            results.append(TagsResult(date=d, flags={}, error=str(ex)))
            _debug(f"tags {d}: error {ex}")

        time.sleep(delay)

    return results


# ---------------------------------------------------------------------------
# URL pattern probing (HEAD requests)
# ---------------------------------------------------------------------------

def probe_url_patterns(
    dates: list[date],
    months: list[date],
    sections: dict[str, str],
    patterns: dict[str, Any],
    session: requests.Session,
    delay: float = 0.15,
) -> list[ProbeResult]:
    """Probe URL patterns with HEAD requests.

    For monthly patterns: probes each unique month × section.
    For daily patterns: probes each date × section (only regular DO1/DO2/DO3
    to limit request volume — a subset of dates for daily patterns).
    """
    results: list[ProbeResult] = []
    queue: list[tuple[date, str, str, str]] = []  # (date, section, pattern, url)

    # Monthly patterns: unique months × all sections
    for pattern_name, url_fn in patterns.items():
        if pattern_name == "monthly":
            for month_date in months:
                for section, prefix in sections.items():
                    url = url_fn(prefix, month_date)
                    queue.append((month_date, section, pattern_name, url))
        else:
            # Daily patterns: only test with a subset of dates, regular sections
            # Use up to 30 dates to keep request count manageable
            daily_dates = dates[:30] if len(dates) > 30 else dates
            for d in daily_dates:
                for section, prefix in list(SECTIONS.items())[:1]:  # only DO1 for daily probes
                    url = url_fn(prefix, d)
                    queue.append((d, section, pattern_name, url))

    # Deduplicate URLs (same URL might appear from different date inputs)
    seen_urls: set[str] = set()
    deduped: list[tuple[date, str, str, str]] = []
    for item in queue:
        if item[3] not in seen_urls:
            seen_urls.add(item[3])
            deduped.append(item)
    queue = deduped

    _log(f"probe: {len(queue)} unique URLs to check ({len(months)} months, "
         f"{len(sections)} sections, {len(patterns)} patterns)")

    for idx, (d, section, pattern_name, url) in enumerate(queue, start=1):
        if idx % 50 == 0:
            _log(f"probe [{idx}/{len(queue)}] ...")

        t0 = time.monotonic()
        try:
            resp = session.head(
                url,
                headers={"User-Agent": _random_ua()},
                timeout=15,
                allow_redirects=True,
            )
            elapsed = int((time.monotonic() - t0) * 1000)

            content_length = resp.headers.get("Content-Length")
            cl_int = int(content_length) if content_length else None
            content_type = resp.headers.get("Content-Type")
            redirect_url = resp.url if resp.url != url else None

            pr = ProbeResult(
                date=d,
                section=section,
                pattern=pattern_name,
                url=url,
                status_code=resp.status_code,
                content_length=cl_int,
                content_type=content_type,
                redirect_url=redirect_url,
                elapsed_ms=elapsed,
            )

            if pr.found:
                size_str = f" ({cl_int:,}B)" if cl_int else ""
                _log(f"  HIT  {pattern_name:12s} {section:6s} {d} → {resp.status_code}{size_str}")
            elif resp.status_code != 404:
                _log(f"  ???  {pattern_name:12s} {section:6s} {d} → {resp.status_code}")
            else:
                _debug(f"  MISS {pattern_name:12s} {section:6s} {d} → 404")

        except Exception as ex:
            elapsed = int((time.monotonic() - t0) * 1000)
            pr = ProbeResult(
                date=d, section=section, pattern=pattern_name,
                url=url, status_code=-1, elapsed_ms=elapsed,
                error=str(ex),
            )
            _debug(f"  ERR  {pattern_name:12s} {section:6s} {d}: {ex}")

        results.append(pr)
        time.sleep(delay)

    return results


# ---------------------------------------------------------------------------
# Download confirmed hits
# ---------------------------------------------------------------------------

def download_hits(
    probe_results: list[ProbeResult],
    output_dir: Path,
    session: requests.Session,
    delay: float = 0.5,
) -> list[str]:
    """Download ZIPs that responded with 200.

    Returns list of local file paths.
    """
    hits = [r for r in probe_results if r.found]
    if not hits:
        _log("download: no hits to download")
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[str] = []

    _log(f"download: {len(hits)} ZIPs to fetch")
    for idx, hit in enumerate(hits, start=1):
        # Local filename: pattern_section_date.zip
        local_name = f"{hit.date.strftime('%Y-%m')}_{hit.section.upper()}.zip"
        if hit.pattern != "monthly":
            local_name = f"{hit.date.isoformat()}_{hit.section.upper()}_{hit.pattern}.zip"

        local_path = output_dir / local_name
        if local_path.exists() and local_path.stat().st_size > 0:
            _log(f"download [{idx}/{len(hits)}]: {local_name} (cached)")
            downloaded.append(str(local_path))
            continue

        try:
            resp = session.get(
                hit.url,
                headers={"User-Agent": _random_ua()},
                timeout=120,
                stream=True,
            )
            resp.raise_for_status()

            size = 0
            with open(local_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
                    size += len(chunk)

            _log(f"download [{idx}/{len(hits)}]: {local_name} ({size:,}B)")
            downloaded.append(str(local_path))
        except Exception as ex:
            _log(f"download [{idx}/{len(hits)}]: {local_name} FAILED: {ex}")

        time.sleep(delay)

    return downloaded


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(report: DiscoveryReport, output_dir: Path) -> None:
    """Write discovery results to JSON and CSV files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Probe results JSON ---
    probe_data = [r.as_dict() for r in report.probe_results]
    (output_dir / "probe_results.json").write_text(
        json.dumps(probe_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # --- Probe results CSV ---
    if probe_data:
        with open(output_dir / "probe_results.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=probe_data[0].keys())
            writer.writeheader()
            writer.writerows(probe_data)

    # --- Tags results JSON ---
    tags_data = [r.as_dict() for r in report.tags_results]
    (output_dir / "tags_results.json").write_text(
        json.dumps(tags_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # --- Summary ---
    pattern_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"hit": 0, "miss": 0, "error": 0})
    year_stats: dict[int, dict[str, int]] = defaultdict(lambda: {"hit": 0, "miss": 0})
    section_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"hit": 0, "miss": 0})
    hit_sizes: list[int] = []

    for r in report.probe_results:
        ps = pattern_stats[r.pattern]
        ys = year_stats[r.date.year]
        ss = section_stats[r.section]
        if r.found:
            ps["hit"] += 1
            ys["hit"] += 1
            ss["hit"] += 1
            if r.content_length:
                hit_sizes.append(r.content_length)
        elif r.error:
            ps["error"] += 1
        else:
            ps["miss"] += 1
            ys["miss"] += 1
            ss["miss"] += 1

    tags_with_extras = sum(1 for t in report.tags_results if any(t.flags.values()))
    tags_total = len(report.tags_results)

    extra_flag_counts: dict[str, int] = defaultdict(int)
    for t in report.tags_results:
        for k, v in t.flags.items():
            if v:
                extra_flag_counts[k] += 1

    summary = {
        "sample_size": len(report.sample_dates),
        "date_range": f"{min(report.sample_dates).isoformat()} to {max(report.sample_dates).isoformat()}" if report.sample_dates else "",
        "total_probes": len(report.probe_results),
        "pattern_statistics": dict(pattern_stats),
        "year_statistics": {str(k): v for k, v in sorted(year_stats.items())},
        "section_statistics": dict(section_stats),
        "tags_api": {
            "total_queried": tags_total,
            "dates_with_extras": tags_with_extras,
            "extra_flag_counts": dict(extra_flag_counts),
        },
        "hit_sizes": {
            "count": len(hit_sizes),
            "min_bytes": min(hit_sizes) if hit_sizes else 0,
            "max_bytes": max(hit_sizes) if hit_sizes else 0,
            "avg_bytes": int(sum(hit_sizes) / len(hit_sizes)) if hit_sizes else 0,
        },
        "downloads": len(report.downloaded),
    }

    (output_dir / "discovery_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    _log("\n" + "=" * 70)
    _log("DISCOVERY REPORT")
    _log("=" * 70)
    _log(f"Sample: {len(report.sample_dates)} dates "
         f"({min(report.sample_dates)} to {max(report.sample_dates)})")
    _log("")

    _log("URL Pattern Results:")
    for pattern, stats in sorted(pattern_stats.items()):
        total = stats["hit"] + stats["miss"] + stats.get("error", 0)
        pct = (stats["hit"] / total * 100) if total else 0
        _log(f"  {pattern:12s}: {stats['hit']:4d} hit / {stats['miss']:4d} miss "
             f"/ {stats.get('error', 0):3d} err  ({pct:5.1f}% hit)")

    _log("")
    _log("Hits by Year (monthly pattern):")
    for year, stats in sorted(year_stats.items()):
        total = stats["hit"] + stats["miss"]
        pct = (stats["hit"] / total * 100) if total else 0
        _log(f"  {year}: {stats['hit']:4d} hit / {stats['miss']:4d} miss ({pct:5.1f}%)")

    _log("")
    _log("Hits by Section:")
    for section, stats in sorted(section_stats.items()):
        total = stats["hit"] + stats["miss"]
        pct = (stats["hit"] / total * 100) if total else 0
        _log(f"  {section:6s}: {stats['hit']:4d} hit / {stats['miss']:4d} miss ({pct:5.1f}%)")

    _log("")
    _log(f"Tags API: {tags_with_extras}/{tags_total} dates with extra editions")
    if extra_flag_counts:
        _log("  Flag frequencies:")
        for flag, count in sorted(extra_flag_counts.items(), key=lambda x: -x[1]):
            _log(f"    {flag:8s}: {count}")

    if hit_sizes:
        _log("")
        _log(f"ZIP sizes: min={min(hit_sizes):,}B  max={max(hit_sizes):,}B  "
             f"avg={int(sum(hit_sizes)/len(hit_sizes)):,}B")

    _log("")
    _log(f"Downloads: {len(report.downloaded)} files")
    _log(f"Reports saved to: {output_dir}")
    _log("=" * 70)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    global _VERBOSE

    p = argparse.ArgumentParser(
        description="Discover DOU public endpoint URL patterns across years"
    )
    p.add_argument("--sample", type=int, default=200,
                   help="Number of random dates to sample (default: 200)")
    p.add_argument("--seed", type=int, default=42,
                   help="Random seed for reproducibility (default: 42)")
    p.add_argument("--start", type=str, default="2016-01-01",
                   help="Start date YYYY-MM-DD (default: 2016-01-01)")
    p.add_argument("--end", type=str, default="2026-03-03",
                   help="End date YYYY-MM-DD (default: 2026-03-03)")
    p.add_argument("--output", type=str, default="data/discovery",
                   help="Output directory (default: data/discovery)")
    p.add_argument("--download", action="store_true",
                   help="Download confirmed-existing ZIPs after probing")
    p.add_argument("--probe-only", action="store_true",
                   help="Only probe URLs, skip tags API and download")
    p.add_argument("--tags-only", action="store_true",
                   help="Only query tags API")
    p.add_argument("--skip-daily", action="store_true",
                   help="Skip daily URL pattern probes (faster)")
    p.add_argument("--delay", type=float, default=0.15,
                   help="Delay between HEAD requests in seconds (default: 0.15)")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()
    _VERBOSE = args.verbose

    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)
    output_dir = Path(args.output)

    # 1) Sample dates
    dates = sample_dates(args.sample, start=start_date, end=end_date, seed=args.seed)
    months = unique_months(dates)
    _log(f"Sampled {len(dates)} dates → {len(months)} unique months")
    _log(f"Date range: {dates[0]} to {dates[-1]}")
    _log(f"Years covered: {sorted({d.year for d in dates})}")

    report = DiscoveryReport(sample_dates=dates)

    session = _build_session()
    try:
        # 2) Tags API
        if not args.probe_only:
            _log(f"\n--- Tags API ({len(dates)} dates) ---")
            report.tags_results = probe_tags_api(dates, session, delay=args.delay)

        if args.tags_only:
            write_report(report, output_dir)
            return

        # 3) Probe URL patterns
        patterns_to_test = {"monthly": URL_PATTERNS["monthly"]}
        if not args.skip_daily:
            patterns_to_test.update({k: v for k, v in URL_PATTERNS.items() if k != "monthly"})

        _log(f"\n--- URL Probing ({len(patterns_to_test)} patterns) ---")
        report.probe_results = probe_url_patterns(
            dates=dates,
            months=months,
            sections=ALL_SECTIONS,
            patterns=patterns_to_test,
            session=session,
            delay=args.delay,
        )

        # 4) Download
        if args.download:
            _log(f"\n--- Download ---")
            report.downloaded = download_hits(
                report.probe_results, output_dir / "zips", session, delay=0.5
            )

    finally:
        session.close()

    # 5) Report
    write_report(report, output_dir)


if __name__ == "__main__":
    main()
