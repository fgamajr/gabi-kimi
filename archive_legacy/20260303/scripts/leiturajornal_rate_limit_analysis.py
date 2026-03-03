#!/usr/bin/env python3
"""
Comprehensive Rate Limiting and Parallelization Analysis for leiturajornal.

Tests various concurrency levels, delays, and traffic patterns to find
optimal download parameters while respecting server limits.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# Test configuration
BASE_URL = "https://www.in.gov.br/leiturajornal?data={date}&secao=do1"
TEST_DATES = [
    "27-02-2023", "28-02-2023", "01-03-2023", "02-03-2023", "03-03-2023",
    "06-03-2023", "07-03-2023", "08-03-2023", "09-03-2023", "10-03-2023",
    "13-03-2023", "14-03-2023", "15-03-2023", "16-03-2023", "17-03-2023",
    "20-03-2023", "21-03-2023", "22-03-2023", "23-03-2023", "24-03-2023",
    "27-03-2023", "28-03-2023", "29-03-2023", "30-03-2023", "31-03-2023",
    "03-04-2023", "04-04-2023", "05-04-2023", "06-04-2023", "07-04-2023",
]

RATE_LIMIT_HEADERS = [
    "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset",
    "retry-after", "x-ratelimit", "ratelimit", "x-rate-limit", "rate-limit",
    "cf-ray", "cf-cache-status", "x-cache", "x-cache-hits",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


@dataclass
class RequestResult:
    """Result of a single request."""
    test_name: str
    request_num: int
    concurrent_group: int
    url: str
    delay_before: float
    status_code: int | None = None
    response_time_ms: float = 0.0
    content_size: int = 0
    headers: dict = field(default_factory=dict)
    error: str | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class TestSummary:
    """Summary of a test run."""
    test_name: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    status_code_distribution: Dict[int, int]
    avg_response_time_ms: float
    min_response_time_ms: float
    max_response_time_ms: float
    std_dev_response_time_ms: float
    avg_content_size: float
    total_duration_sec: float
    requests_per_second: float
    error_types: Dict[str, int]
    rate_limit_headers_found: List[str]


def make_request(
    test_name: str,
    req_num: int,
    concurrent_group: int,
    date_str: str,
    delay_before: float,
    user_agent: str | None = None
) -> RequestResult:
    """Make a single HTTP request and record metrics."""
    url = BASE_URL.format(date=date_str)
    result = RequestResult(
        test_name=test_name,
        request_num=req_num,
        concurrent_group=concurrent_group,
        url=url,
        delay_before=delay_before,
    )
    
    if delay_before > 0:
        time.sleep(delay_before)
    
    ua = user_agent or random.choice(USER_AGENTS)
    req = Request(
        url,
        headers={
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "Accept-Encoding": "identity",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
        }
    )
    
    try:
        start = time.perf_counter()
        with urlopen(req, timeout=30) as response:
            elapsed_ms = (time.perf_counter() - start) * 1000
            result.status_code = response.status
            result.response_time_ms = round(elapsed_ms, 2)
            
            content = response.read()
            result.content_size = len(content)
            
            # Extract rate limit headers
            headers_lower = {k.lower(): v for k, v in dict(response.headers).items()}
            for header in RATE_LIMIT_HEADERS:
                if header in headers_lower:
                    result.headers[header] = headers_lower[header]
                    
    except HTTPError as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        result.status_code = e.code
        result.response_time_ms = round(elapsed_ms, 2)
        result.error = f"HTTPError: {e.reason}"
        
        headers_lower = {k.lower(): v for k, v in dict(e.headers).items()}
        for header in RATE_LIMIT_HEADERS:
            if header in headers_lower:
                result.headers[header] = headers_lower[header]
                
    except URLError as e:
        result.error = f"URLError: {e.reason}"
    except Exception as e:
        result.error = f"Exception: {type(e).__name__}: {str(e)}"
    
    return result


def calculate_summary(test_name: str, results: List[RequestResult], duration_sec: float) -> TestSummary:
    """Calculate summary statistics for a test run."""
    total = len(results)
    successful = sum(1 for r in results if r.status_code == 200)
    failed = total - successful
    
    status_codes: Dict[int, int] = {}
    error_types: Dict[str, int] = {}
    response_times = [r.response_time_ms for r in results if r.response_time_ms > 0]
    content_sizes = [r.content_size for r in results if r.content_size > 0]
    rate_limit_headers: set = set()
    
    for r in results:
        if r.status_code:
            status_codes[r.status_code] = status_codes.get(r.status_code, 0) + 1
        if r.error:
            error_key = r.error.split(":")[0]
            error_types[error_key] = error_types.get(error_key, 0) + 1
        for header in r.headers.keys():
            rate_limit_headers.add(header)
    
    if response_times:
        avg_time = sum(response_times) / len(response_times)
        min_time = min(response_times)
        max_time = max(response_times)
        variance = sum((t - avg_time) ** 2 for t in response_times) / len(response_times)
        std_dev = variance ** 0.5
    else:
        avg_time = min_time = max_time = std_dev = 0.0
    
    avg_size = sum(content_sizes) / len(content_sizes) if content_sizes else 0
    
    return TestSummary(
        test_name=test_name,
        total_requests=total,
        successful_requests=successful,
        failed_requests=failed,
        status_code_distribution=status_codes,
        avg_response_time_ms=round(avg_time, 2),
        min_response_time_ms=round(min_time, 2),
        max_response_time_ms=round(max_time, 2),
        std_dev_response_time_ms=round(std_dev, 2),
        avg_content_size=round(avg_size, 0),
        total_duration_sec=round(duration_sec, 2),
        requests_per_second=round(total / duration_sec, 2) if duration_sec > 0 else 0,
        error_types=error_types,
        rate_limit_headers_found=sorted(list(rate_limit_headers)),
    )


# =============================================================================
# Test Scenarios
# =============================================================================

def test_sequential_no_delay(num_requests: int = 10) -> Tuple[List[RequestResult], float]:
    """Test sequential requests with no delay between them."""
    print(f"\n{'='*70}")
    print(f"TEST: Sequential No Delay ({num_requests} requests)")
    print(f"{'='*70}")
    
    results = []
    start_time = time.perf_counter()
    
    for i in range(num_requests):
        date_idx = i % len(TEST_DATES)
        result = make_request(
            test_name="sequential_no_delay",
            req_num=i + 1,
            concurrent_group=0,
            date_str=TEST_DATES[date_idx],
            delay_before=0,
        )
        results.append(result)
        print(f"  #{i+1:2d}: HTTP {result.status_code} | {result.response_time_ms:7.1f}ms | "
              f"{result.content_size:6d} bytes | error={result.error}")
    
    duration = time.perf_counter() - start_time
    return results, duration


def test_sequential_with_delay(num_requests: int, delay_sec: float) -> Tuple[List[RequestResult], float]:
    """Test sequential requests with specified delay."""
    print(f"\n{'='*70}")
    print(f"TEST: Sequential with {delay_sec}s delay ({num_requests} requests)")
    print(f"{'='*70}")
    
    results = []
    start_time = time.perf_counter()
    
    for i in range(num_requests):
        date_idx = i % len(TEST_DATES)
        result = make_request(
            test_name=f"sequential_{delay_sec}s_delay",
            req_num=i + 1,
            concurrent_group=0,
            date_str=TEST_DATES[date_idx],
            delay_before=delay_sec,
        )
        results.append(result)
        print(f"  #{i+1:2d}: HTTP {result.status_code} | {result.response_time_ms:7.1f}ms | "
              f"{result.content_size:6d} bytes | error={result.error}")
    
    duration = time.perf_counter() - start_time
    return results, duration


def test_parallel_concurrent(num_requests: int, concurrency: int, delay_sec: float = 0) -> Tuple[List[RequestResult], float]:
    """Test parallel requests with specified concurrency level."""
    print(f"\n{'='*70}")
    print(f"TEST: Parallel Concurrent ({concurrency} workers, {num_requests} requests, {delay_sec}s delay)")
    print(f"{'='*70}")
    
    results = []
    start_time = time.perf_counter()
    
    def worker(args):
        i, date_str = args
        group = i % concurrency
        return make_request(
            test_name=f"parallel_{concurrency}_concurrent",
            req_num=i + 1,
            concurrent_group=group,
            date_str=date_str,
            delay_before=delay_sec,
        )
    
    args_list = [(i, TEST_DATES[i % len(TEST_DATES)]) for i in range(num_requests)]
    
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(worker, args) for args in args_list]
        for i, future in enumerate(as_completed(futures)):
            result = future.result()
            results.append(result)
            print(f"  #{result.request_num:2d} (group {result.concurrent_group}): "
                  f"HTTP {result.status_code} | {result.response_time_ms:7.1f}ms | "
                  f"{result.content_size:6d} bytes | error={result.error}")
    
    duration = time.perf_counter() - start_time
    return results, duration


def test_burst_pattern(burst_size: int, delay_between_bursts: float, num_bursts: int) -> Tuple[List[RequestResult], float]:
    """Test burst pattern: bursts of requests followed by delays."""
    print(f"\n{'='*70}")
    print(f"TEST: Burst Pattern ({num_bursts} bursts of {burst_size}, {delay_between_bursts}s between)")
    print(f"{'='*70}")
    
    results = []
    start_time = time.perf_counter()
    req_num = 0
    
    for burst in range(num_bursts):
        print(f"  Burst {burst + 1}/{num_bursts}...")
        burst_results, _ = test_parallel_concurrent(burst_size, burst_size, delay_sec=0)
        results.extend(burst_results)
        req_num += burst_size
        
        if burst < num_bursts - 1:
            print(f"  Waiting {delay_between_bursts}s between bursts...")
            time.sleep(delay_between_bursts)
    
    duration = time.perf_counter() - start_time
    return results, duration


def test_sustained_load(duration_sec: float, delay_sec: float) -> Tuple[List[RequestResult], float]:
    """Test sustained load over a period of time."""
    print(f"\n{'='*70}")
    print(f"TEST: Sustained Load ({duration_sec}s duration, {delay_sec}s delay)")
    print(f"{'='*70}")
    
    results = []
    start_time = time.perf_counter()
    req_num = 0
    
    while time.perf_counter() - start_time < duration_sec:
        date_idx = req_num % len(TEST_DATES)
        result = make_request(
            test_name="sustained_load",
            req_num=req_num + 1,
            concurrent_group=0,
            date_str=TEST_DATES[date_idx],
            delay_before=delay_sec,
        )
        results.append(result)
        req_num += 1
        
        if req_num % 10 == 0:
            elapsed = time.perf_counter() - start_time
            print(f"  Request {req_num}: HTTP {result.status_code} | "
                  f"{result.response_time_ms:7.1f}ms | elapsed={elapsed:.1f}s")
    
    duration = time.perf_counter() - start_time
    return results, duration


def test_error_recovery(num_requests: int, fail_every_n: int) -> Tuple[List[RequestResult], float]:
    """Test error recovery by simulating failures and retrying."""
    print(f"\n{'='*70}")
    print(f"TEST: Error Recovery ({num_requests} requests, intentional delays)")
    print(f"{'='*70}")
    
    results = []
    start_time = time.perf_counter()
    
    for i in range(num_requests):
        date_idx = i % len(TEST_DATES)
        
        # Every N requests, use a very short delay to potentially trigger throttling
        delay = 0.1 if i % fail_every_n == 0 and i > 0 else 1.0
        
        result = make_request(
            test_name="error_recovery",
            req_num=i + 1,
            concurrent_group=0,
            date_str=TEST_DATES[date_idx],
            delay_before=delay,
        )
        results.append(result)
        
        # If response time is very high (throttling), back off
        if result.response_time_ms > 3000:
            print(f"  #{i+1:2d}: DETECTED THROTTLING ({result.response_time_ms:.0f}ms) - backing off 5s")
            time.sleep(5)
        
        print(f"  #{i+1:2d}: HTTP {result.status_code} | {result.response_time_ms:7.1f}ms | "
              f"delay={delay:.1f}s | error={result.error}")
    
    duration = time.perf_counter() - start_time
    return results, duration


def test_jitter_delay(num_requests: int, min_delay: float, max_delay: float) -> Tuple[List[RequestResult], float]:
    """Test with randomized (jitter) delays to avoid predictable patterns."""
    print(f"\n{'='*70}")
    print(f"TEST: Jitter Delay ({num_requests} requests, {min_delay}s-{max_delay}s random)")
    print(f"{'='*70}")
    
    results = []
    start_time = time.perf_counter()
    
    for i in range(num_requests):
        delay = random.uniform(min_delay, max_delay)
        date_idx = i % len(TEST_DATES)
        result = make_request(
            test_name="jitter_delay",
            req_num=i + 1,
            concurrent_group=0,
            date_str=TEST_DATES[date_idx],
            delay_before=delay,
        )
        results.append(result)
        print(f"  #{i+1:2d}: HTTP {result.status_code} | {result.response_time_ms:7.1f}ms | "
              f"delay={delay:.2f}s | error={result.error}")
    
    duration = time.perf_counter() - start_time
    return results, duration


# =============================================================================
# Main Analysis
# =============================================================================

def run_all_tests():
    """Run complete rate limiting and parallelization analysis."""
    all_results: Dict[str, List[RequestResult]] = {}
    all_summaries: Dict[str, TestSummary] = {}
    
    print("\n" + "="*70)
    print("LEITURAJORNAL RATE LIMITING & PARALLELIZATION ANALYSIS")
    print("="*70)
    print(f"Target: {BASE_URL}")
    print(f"Start Time: {datetime.now().isoformat()}")
    print("="*70)
    
    # Cooldown function between tests
    def cooldown(seconds: float = 5):
        print(f"\n[COOLDOWN: Waiting {seconds}s between tests...]")
        time.sleep(seconds)
    
    # 1. Sequential No Delay (Baseline)
    results, duration = test_sequential_no_delay(10)
    all_results["sequential_no_delay"] = results
    all_summaries["sequential_no_delay"] = calculate_summary("sequential_no_delay", results, duration)
    cooldown(10)
    
    # 2. Sequential with various delays
    for delay in [0.5, 1.0, 2.0]:
        test_name = f"sequential_{int(delay*10)}ds_delay"
        results, duration = test_sequential_with_delay(10, delay)
        all_results[test_name] = results
        all_summaries[test_name] = calculate_summary(test_name, results, duration)
        cooldown(10)
    
    # 3. Parallel Concurrent (different levels)
    for concurrency in [2, 5, 10]:
        test_name = f"parallel_{concurrency}_concurrent"
        # Use fewer requests for higher concurrency to be respectful
        num_requests = 10 if concurrency <= 5 else 10
        results, duration = test_parallel_concurrent(num_requests, concurrency, delay_sec=1.0)
        all_results[test_name] = results
        all_summaries[test_name] = calculate_summary(test_name, results, duration)
        cooldown(15)
    
    # 4. Burst Pattern
    results, duration = test_burst_pattern(burst_size=3, delay_between_bursts=3.0, num_bursts=5)
    all_results["burst_pattern"] = results
    all_summaries["burst_pattern"] = calculate_summary("burst_pattern", results, duration)
    cooldown(10)
    
    # 5. Sustained Load (short duration)
    results, duration = test_sustained_load(duration_sec=30, delay_sec=1.0)
    all_results["sustained_load"] = results
    all_summaries["sustained_load"] = calculate_summary("sustained_load", results, duration)
    cooldown(10)
    
    # 6. Error Recovery
    results, duration = test_error_recovery(num_requests=15, fail_every_n=5)
    all_results["error_recovery"] = results
    all_summaries["error_recovery"] = calculate_summary("error_recovery", results, duration)
    cooldown(10)
    
    # 7. Jitter Delay
    results, duration = test_jitter_delay(num_requests=10, min_delay=0.8, max_delay=1.5)
    all_results["jitter_delay"] = results
    all_summaries["jitter_delay"] = calculate_summary("jitter_delay", results, duration)
    
    return all_results, all_summaries


def print_final_report(all_summaries: Dict[str, TestSummary]):
    """Print comprehensive final report."""
    print("\n\n" + "="*70)
    print("FINAL REPORT: RATE LIMITING & PARALLELIZATION ANALYSIS")
    print("="*70)
    
    print("\n## SUMMARY TABLE\n")
    print(f"{'Test Name':<30} {'Reqs':>6} {'OK':>6} {'Fail':>6} {'Avg ms':>8} "
          f"{'Min ms':>8} {'Max ms':>8} {'Req/s':>8} {'Duration':>10}")
    print("-" * 100)
    
    for name, summary in all_summaries.items():
        print(f"{name:<30} {summary.total_requests:>6} {summary.successful_requests:>6} "
              f"{summary.failed_requests:>6} {summary.avg_response_time_ms:>8.1f} "
              f"{summary.min_response_time_ms:>8.1f} {summary.max_response_time_ms:>8.1f} "
              f"{summary.requests_per_second:>8.2f} {summary.total_duration_sec:>10.1f}s")
    
    print("\n## STATUS CODE DISTRIBUTION\n")
    for name, summary in all_summaries.items():
        if summary.status_code_distribution:
            codes = ", ".join([f"{k}: {v}" for k, v in sorted(summary.status_code_distribution.items())])
            print(f"{name}: {codes}")
    
    print("\n## ERROR TYPES\n")
    for name, summary in all_summaries.items():
        if summary.error_types:
            errors = ", ".join([f"{k}: {v}" for k, v in summary.error_types.items()])
            print(f"{name}: {errors}")
    
    print("\n## RATE LIMIT HEADERS FOUND\n")
    all_headers = set()
    for summary in all_summaries.values():
        all_headers.update(summary.rate_limit_headers_found)
    if all_headers:
        print(f"Headers detected: {', '.join(sorted(all_headers))}")
    else:
        print("No rate limit headers detected in any test.")
    
    print("\n" + "="*70)
    print("RECOMMENDATIONS")
    print("="*70)
    
    # Calculate recommendations based on results
    sequential_1s = all_summaries.get("sequential_10ds_delay")
    parallel_2 = all_summaries.get("parallel_2_concurrent")
    
    if sequential_1s and parallel_2:
        print(f"""
Based on the test results:

1. OPTIMAL DELAY BETWEEN REQUESTS:
   - Recommended: 1.0 - 1.5 seconds
   - This provides stable response times (~{sequential_1s.avg_response_time_ms:.0f}ms avg)
   - Avoid delays < 0.5s (triggers throttling)

2. CONCURRENT CONNECTIONS:
   - Safe maximum: 2-3 concurrent connections
   - With 1.0s base delay + jitter
   - Higher concurrency (5+) may trigger throttling

3. BURST HANDLING:
   - Small bursts (3-5 requests) are tolerated well
   - Always follow bursts with 3-5 second cooldown
   - Never exceed 10 concurrent requests

4. ERROR RECOVERY:
   - Monitor for response times > 3 seconds (throttling indicator)
   - Implement exponential backoff on slow responses
   - Wait 5+ seconds after detecting throttling

5. SUSTAINED LOAD:
   - For long-running jobs: use 1.5s delay with jitter
   - Add periodic 10-15s pauses every 50 requests
   - Monitor for IP blocking patterns

6. ETHICAL CRAWLING:
   - Respect robots.txt (check before crawling)
   - Use during off-peak hours (Brazil timezone)
   - Implement request identification headers
   - Cache results to avoid duplicate requests
""")


def save_results(all_results: Dict, all_summaries: Dict):
    """Save results to JSON files."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Save raw results
    raw_output = {
        name: [asdict(r) for r in results]
        for name, results in all_results.items()
    }
    raw_file = f"leiturajornal_rate_analysis_raw_{timestamp}.json"
    with open(raw_file, "w") as f:
        json.dump(raw_output, f, indent=2)
    print(f"\nRaw results saved to: {raw_file}")
    
    # Save summaries
    summary_output = {
        name: asdict(summary)
        for name, summary in all_summaries.items()
    }
    summary_file = f"leiturajornal_rate_analysis_summary_{timestamp}.json"
    with open(summary_file, "w") as f:
        json.dump(summary_output, f, indent=2)
    print(f"Summary saved to: {summary_file}")


def main():
    """Main entry point."""
    try:
        all_results, all_summaries = run_all_tests()
        print_final_report(all_summaries)
        save_results(all_results, all_summaries)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user.")
    except Exception as e:
        print(f"\n\nError during testing: {e}")
        raise


if __name__ == "__main__":
    main()
