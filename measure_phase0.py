"""Phase 0 measurement script — computes metrics from frozen DOU data.

Reads manifest.json files and HTML content from a Phase 0 freeze run.
Outputs: total HTML size, avg per section, encoding distribution,
extraction success rate, and documents-per-section-per-day estimate.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


def detect_encoding_from_html(data: bytes) -> str:
    """Detect declared encoding from HTML meta tags."""
    # Check first 4KB for meta charset
    head = data[:4096]
    # <meta charset="...">
    m = re.search(rb'charset=["\']?([^"\'\s;>]+)', head, re.IGNORECASE)
    if m:
        return m.group(1).decode("ascii", errors="replace").lower().strip()
    # BOM detection
    if data[:3] == b"\xef\xbb\xbf":
        return "utf-8-bom"
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"
    return "unknown"


def count_articles(data: bytes) -> int:
    """Count articles from the embedded jsonArray in DOU listing HTML.

    DOU pages embed article data in a <script id="params"> tag as JSON
    with a "jsonArray" key containing the article list.
    """
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        return 0
    m = re.search(
        r'<script id="params" type="application/json">\s*({.*?})\s*</script>',
        text, re.DOTALL,
    )
    if not m:
        return 0
    try:
        obj = json.loads(m.group(1))
        return len(obj.get("jsonArray", []))
    except (json.JSONDecodeError, ValueError):
        return 0


def measure_bucket(bucket_dir: Path) -> dict:
    """Measure a single Phase 0 bucket (one month directory)."""
    if not bucket_dir.is_dir():
        return {"error": f"not a directory: {bucket_dir}"}

    total_size = 0
    section_sizes: dict[str, list[int]] = defaultdict(list)
    encoding_counter: Counter = Counter()
    docs_per_section_per_day: dict[str, list[int]] = defaultdict(list)
    success = 0
    fail = 0
    dates_seen = 0

    for day_dir in sorted(bucket_dir.iterdir()):
        if not day_dir.is_dir():
            continue
        manifest_path = day_dir / "manifest.json"
        if not manifest_path.exists():
            continue

        dates_seen += 1
        with open(manifest_path) as f:
            manifest = json.load(f)

        for section_info in manifest.get("sections", []):
            section = section_info.get("section", "?")
            sha = section_info.get("sha256")
            size = section_info.get("size_bytes", 0)
            error = section_info.get("error")

            if error or sha is None:
                fail += 1
                continue

            success += 1
            total_size += size
            section_sizes[section].append(size)

            # Read HTML for encoding + doc count
            html_path = day_dir / section_info.get("filename", f"{section}.html")
            if html_path.exists():
                raw = html_path.read_bytes()
                enc = detect_encoding_from_html(raw)
                encoding_counter[enc] += 1
                doc_count = count_articles(raw)
                docs_per_section_per_day[section].append(doc_count)

    # Compute averages
    avg_per_section: dict[str, float] = {}
    for sec, sizes in section_sizes.items():
        avg_per_section[sec] = sum(sizes) / len(sizes) if sizes else 0

    avg_docs_per_section: dict[str, float] = {}
    total_docs = 0
    for sec, counts in docs_per_section_per_day.items():
        avg_docs_per_section[sec] = sum(counts) / len(counts) if counts else 0
        total_docs += sum(counts)

    return {
        "bucket": bucket_dir.name,
        "dates_frozen": dates_seen,
        "sections_ok": success,
        "sections_failed": fail,
        "success_rate_pct": round(100 * success / (success + fail), 2) if (success + fail) else 0,
        "total_html_bytes": total_size,
        "total_html_mb": round(total_size / (1024 * 1024), 2),
        "avg_html_bytes_per_section": avg_per_section,
        "encoding_distribution": dict(encoding_counter.most_common()),
        "estimated_docs_per_section_per_day": avg_docs_per_section,
        "total_estimated_docs": total_docs,
    }


def extrapolate(buckets: list[dict]) -> dict:
    """Extrapolate from Phase 0 buckets to full 20-year estimate."""
    if not buckets:
        return {}

    total_days_sampled = sum(b.get("dates_frozen", 0) for b in buckets)
    total_bytes = sum(b.get("total_html_bytes", 0) for b in buckets)
    total_docs = sum(b.get("total_estimated_docs", 0) for b in buckets)

    if total_days_sampled == 0:
        return {"error": "no data"}

    # ~7305 days in 20 years (2003-2023)
    full_range_days = 7305
    scale = full_range_days / total_days_sampled

    return {
        "sampled_days": total_days_sampled,
        "full_range_days": full_range_days,
        "scale_factor": round(scale, 2),
        "projected_html_gb": round(total_bytes * scale / (1024 ** 3), 2),
        "projected_total_docs": int(total_docs * scale),
        "avg_bytes_per_day": int(total_bytes / total_days_sampled),
        "avg_docs_per_day": round(total_docs / total_days_sampled, 1),
    }


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 measure_phase0.py <phase0_dir> [bucket...]")
        print("  <phase0_dir>: root directory containing month subdirs")
        print("  [bucket...]: optional specific bucket names (e.g., 2003-01)")
        print()
        print("If no buckets specified, measures all subdirs in phase0_dir.")
        raise SystemExit(1)

    phase0_dir = Path(sys.argv[1])
    if not phase0_dir.is_dir():
        raise SystemExit(f"error: not a directory: {phase0_dir}")

    bucket_names = sys.argv[2:] if len(sys.argv) > 2 else None

    if bucket_names:
        bucket_dirs = [phase0_dir / name for name in bucket_names]
    else:
        bucket_dirs = sorted(
            p for p in phase0_dir.iterdir()
            if p.is_dir() and p.name != "__pycache__"
        )

    if not bucket_dirs:
        raise SystemExit("error: no buckets found")

    buckets: list[dict] = []
    for bd in bucket_dirs:
        print(f"--- Measuring {bd.name} ---", file=sys.stderr)
        result = measure_bucket(bd)
        buckets.append(result)

    projection = extrapolate(buckets)

    report = {
        "buckets": buckets,
        "projection": projection,
    }

    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
