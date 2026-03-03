#!/usr/bin/env python3
"""INLabs Bulk Download CLI - Optimized bulk downloader for DOU ZIP files.

Usage:
    # Benchmark different concurrency levels
    python bulk_download.py benchmark --days 7 --output ./inlabs_data

    # Download last 7 days with optimal settings
    python bulk_download.py download --days 7 --output ./inlabs_data --concurrency 2

    # Download specific date range
    python bulk_download.py download --start 2025-02-20 --end 2025-02-25 --output ./inlabs_data

    # Test rate limits
    python bulk_download.py test-rate-limit --date 2025-02-25

Environment Variables:
    INLABS_USER - INLabs username/email
    INLABS_PWD - INLabs password
    GABI_INLABS_COOKIE - Optional session cookie for authentication
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from inlabs_bulk.inlabs_client import INLabsClient, DOU_SECTIONS, BenchmarkResult

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger(__name__)


def get_recent_dates(days: int) -> list[date]:
    """Get list of recent dates (excluding weekends if possible)."""
    today = date.today()
    dates = []
    current = today

    while len(dates) < days:
        # Skip weekends (5=Saturday, 6=Sunday)
        if current.weekday() < 5:
            dates.append(current)
        current -= timedelta(days=1)

    return dates


def get_date_range(start_str: str, end_str: str) -> list[date]:
    """Get list of dates between start and end."""
    start = date.fromisoformat(start_str)
    end = date.fromisoformat(end_str)

    dates = []
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)

    return dates


def print_benchmark_summary(benchmarks: list[BenchmarkResult]) -> None:
    """Print a formatted benchmark summary."""
    print("\n" + "=" * 80)
    print("BENCHMARK SUMMARY")
    print("=" * 80)
    print(f"{'Concurrency':<12} {'Success':<8} {'Failed':<8} {'Total MB':<10} {'Time (s)':<10} {'Mbps':<8} {'DL/sec':<8}")
    print("-" * 80)

    optimal = None
    best_throughput = 0.0

    for b in benchmarks:
        total_mb = b.total_bytes / 1_000_000
        time_sec = b.total_time_ms / 1000
        print(
            f"{b.concurrency:<12} {b.successful:<8} {b.failed:<8} "
            f"{total_mb:<10.2f} {time_sec:<10.1f} {b.avg_speed_mbps:<8.2f} {b.downloads_per_sec:<8.2f}"
        )

        # Find optimal: best throughput without too many failures
        if b.failed == 0 and b.downloads_per_sec > best_throughput:
            best_throughput = b.downloads_per_sec
            optimal = b

    print("-" * 80)

    if optimal:
        print(f"\nOptimal configuration: concurrency={optimal.concurrency}")
        print(f"  - Throughput: {optimal.downloads_per_sec:.2f} downloads/sec")
        print(f"  - Average speed: {optimal.avg_speed_mbps:.2f} Mbps")
        print(f"  - Total time: {optimal.total_time_ms / 1000:.1f}s")
    else:
        print("\nWarning: No configuration completed without failures.")
        print("Recommendation: Use concurrency=1 with higher delays between requests.")


def save_benchmark_report(benchmarks: list[BenchmarkResult], output_path: Path) -> None:
    """Save detailed benchmark report to JSON."""
    report = {
        "benchmarks": [
            {
                "concurrency": b.concurrency,
                "total_downloads": b.total_downloads,
                "successful": b.successful,
                "failed": b.failed,
                "total_bytes": b.total_bytes,
                "total_time_ms": b.total_time_ms,
                "avg_speed_mbps": b.avg_speed_mbps,
                "downloads_per_sec": b.downloads_per_sec,
                "results": [
                    {
                        "date": r.date.isoformat(),
                        "section": r.section,
                        "success": r.success,
                        "size_bytes": r.size_bytes,
                        "download_time_ms": r.download_time_ms,
                        "error": r.error,
                        "http_status": r.http_status,
                    }
                    for r in b.results
                ],
            }
            for b in benchmarks
        ],
    }

    output_path.write_text(json.dumps(report, indent=2))
    log.info("Benchmark report saved to %s", output_path)


def cmd_benchmark(args: argparse.Namespace) -> int:
    """Run download benchmarks at different concurrency levels."""
    dates = get_recent_dates(args.days)
    sections = args.sections or ["DO1"]  # Just test with DO1 for benchmarks

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info("Running benchmarks for %d dates, sections: %s", len(dates), sections)

    with INLabsClient() as client:
        # First authenticate
        if not client.authenticate():
            log.error("Authentication failed - check credentials")
            return 1

        benchmarks = client.benchmark_downloads(
            dates=dates,
            sections=sections,
            output_dir=output_dir,
            concurrency_levels=args.concurrency_levels,
        )

    print_benchmark_summary(benchmarks)

    # Save detailed report
    report_path = output_dir / "benchmark_report.json"
    save_benchmark_report(benchmarks, report_path)

    return 0


def cmd_download(args: argparse.Namespace) -> int:
    """Download DOU ZIP files."""
    if args.start and args.end:
        dates = get_date_range(args.start, args.end)
    elif args.days:
        dates = get_recent_dates(args.days)
    else:
        log.error("Either --days or --start/--end must be specified")
        return 1

    sections = args.sections or DOU_SECTIONS
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info(
        "Downloading %d dates × %d sections = %d files to %s",
        len(dates), len(sections), len(dates) * len(sections), output_dir
    )

    with INLabsClient() as client:
        if not client.authenticate():
            log.error("Authentication failed - check credentials")
            return 1

        results = client.download_batch(
            dates=dates,
            sections=sections,
            output_dir=output_dir,
            concurrency=args.concurrency,
            delay_between_requests=args.delay,
            skip_existing=not args.no_skip_existing,
        )

    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    total_bytes = sum(r.size_bytes for r in successful)

    print("\n" + "=" * 60)
    print("DOWNLOAD SUMMARY")
    print("=" * 60)
    print(f"Total files: {len(results)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")
    print(f"Total size: {total_bytes / 1_000_000:.2f} MB")
    print(f"Average file size: {total_bytes / len(successful) / 1_000:.2f} KB" if successful else "N/A")

    if failed:
        print("\nFailed downloads:")
        for r in failed:
            print(f"  - {r.date} {r.section}: {r.error}")

    # Save manifest
    manifest = {
        "dates": [d.isoformat() for d in dates],
        "sections": sections,
        "total_files": len(results),
        "successful": len(successful),
        "failed": len(failed),
        "total_bytes": total_bytes,
        "files": [
            {
                "date": r.date.isoformat(),
                "section": r.section,
                "success": r.success,
                "filename": r.local_path.name if r.local_path else None,
                "size_bytes": r.size_bytes,
                "sha256": r.sha256,
                "download_time_ms": r.download_time_ms,
                "error": r.error,
            }
            for r in results
        ],
    }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    log.info("Manifest saved to %s", manifest_path)

    return 0 if not failed else 1


def cmd_test_rate_limit(args: argparse.Namespace) -> int:
    """Test rate limiting behavior."""
    target_date = date.fromisoformat(args.date) if args.date else date.today()

    log.info("Testing rate limits for %s, section %s", target_date, args.section)

    with INLabsClient() as client:
        if not client.authenticate():
            log.error("Authentication failed")
            return 1

        results = client.test_rate_limits(
            target_date=target_date,
            section=args.section,
            max_requests=args.max_requests,
            delay_between_requests=args.delay,
        )

    print("\n" + "=" * 60)
    print("RATE LIMIT TEST RESULTS")
    print("=" * 60)
    print(f"Total requests: {results['total_requests']}")
    print(f"Rate limited: {results['rate_limited']}")
    print(f"Rate limit count: {results['rate_limit_count']}")

    if results['retry_after_values']:
        print(f"Retry-After values: {results['retry_after_values']}")

    # Analyze results
    statuses = {}
    for r in results['results']:
        status = r.get('status', 'error')
        statuses[status] = statuses.get(status, 0) + 1

    print("\nStatus code distribution:")
    for status, count in sorted(statuses.items()):
        print(f"  HTTP {status}: {count}")

    # Estimate safe rate
    rate_limited_at = None
    for r in results['results']:
        if r.get('status') == 429:
            rate_limited_at = r['request_num']
            break

    if rate_limited_at:
        safe_requests = max(1, rate_limited_at - 1)
        print(f"\nRate limit hit at request #{rate_limited_at}")
        print(f"Safe request rate: ~{safe_requests} requests per burst")
        print(f"Recommended: {safe_requests // 2} requests with {args.delay}s delay")
    else:
        print(f"\nNo rate limit detected with {args.delay}s between requests")
        print(f"May be safe to increase concurrency")

    # Save detailed results
    output_path = Path(args.output) if args.output else Path("rate_limit_test.json")
    output_path.write_text(json.dumps(results, indent=2))
    log.info("Detailed results saved to %s", output_path)

    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    """Discover available files for a date."""
    target_date = date.fromisoformat(args.date) if args.date else date.today()

    log.info("Discovering available files for %s", target_date)

    with INLabsClient() as client:
        if not client.authenticate():
            log.error("Authentication failed")
            return 1

        available = client.discover_available_files(
            target_date=target_date,
            sections=DOU_SECTIONS,
        )

    print("\n" + "=" * 60)
    print(f"AVAILABLE FILES FOR {target_date}")
    print("=" * 60)

    if not available:
        print("No files found (date may be weekend or holiday)")
        return 0

    for item in available:
        print(f"  - {item['section']}: {item['url']}")

    print(f"\nTotal: {len(available)} sections available")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="INLabs Bulk Downloader for DOU ZIP files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Benchmark download speeds
  python bulk_download.py benchmark --days 3

  # Download last 7 days
  python bulk_download.py download --days 7 -o ./inlabs_data

  # Download specific range with 2 concurrent connections
  python bulk_download.py download --start 2025-02-20 --end 2025-02-25 -c 2

  # Test rate limits
  python bulk_download.py test-rate-limit --date 2025-02-25
        """,
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Benchmark command
    p_benchmark = subparsers.add_parser(
        "benchmark",
        help="Benchmark download speeds at different concurrency levels",
    )
    p_benchmark.add_argument(
        "--days", "-d",
        type=int,
        default=3,
        help="Number of recent days to test (default: 3)",
    )
    p_benchmark.add_argument(
        "--output", "-o",
        default="./inlabs_benchmark",
        help="Output directory for benchmark downloads",
    )
    p_benchmark.add_argument(
        "--concurrency-levels", "-c",
        type=int,
        nargs="+",
        default=[1, 2, 3, 5],
        help="Concurrency levels to test (default: 1 2 3 5)",
    )
    p_benchmark.add_argument(
        "--sections", "-s",
        nargs="+",
        help="Sections to download (default: DO1)",
    )
    p_benchmark.set_defaults(func=cmd_benchmark)

    # Download command
    p_download = subparsers.add_parser(
        "download",
        help="Download DOU ZIP files",
    )
    p_download.add_argument(
        "--days", "-d",
        type=int,
        help="Number of recent days to download",
    )
    p_download.add_argument(
        "--start",
        help="Start date (YYYY-MM-DD)",
    )
    p_download.add_argument(
        "--end",
        help="End date (YYYY-MM-DD)",
    )
    p_download.add_argument(
        "--output", "-o",
        default="./inlabs_data",
        help="Output directory (default: ./inlabs_data)",
    )
    p_download.add_argument(
        "--sections", "-s",
        nargs="+",
        choices=DOU_SECTIONS,
        help=f"Sections to download (default: all)",
    )
    p_download.add_argument(
        "--concurrency", "-c",
        type=int,
        default=2,
        help="Concurrent downloads (default: 2)",
    )
    p_download.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay between requests in seconds (default: 0.5)",
    )
    p_download.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Re-download existing files",
    )
    p_download.set_defaults(func=cmd_download)

    # Test rate limit command
    p_test = subparsers.add_parser(
        "test-rate-limit",
        help="Test rate limiting behavior",
    )
    p_test.add_argument(
        "--date",
        help="Date to test (YYYY-MM-DD, default: today)",
    )
    p_test.add_argument(
        "--section",
        default="DO1",
        choices=DOU_SECTIONS,
        help="Section to test (default: DO1)",
    )
    p_test.add_argument(
        "--max-requests",
        type=int,
        default=20,
        help="Number of requests to make (default: 20)",
    )
    p_test.add_argument(
        "--delay",
        type=float,
        default=0.1,
        help="Delay between requests (default: 0.1)",
    )
    p_test.add_argument(
        "--output", "-o",
        help="Output file for detailed results",
    )
    p_test.set_defaults(func=cmd_test_rate_limit)

    # Discover command
    p_discover = subparsers.add_parser(
        "discover",
        help="Discover available files for a date",
    )
    p_discover.add_argument(
        "--date",
        help="Date to check (YYYY-MM-DD, default: today)",
    )
    p_discover.set_defaults(func=cmd_discover)

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
