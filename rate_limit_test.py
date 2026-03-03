#!/usr/bin/env python3
"""Rate limit testing for leiturajornal DOU endpoint."""
from __future__ import annotations

import time
import json
from dataclasses import dataclass, field, asdict
from urllib.request import Request, urlopen
from urllib.error import HTTPError


@dataclass
class RequestResult:
    """Result of a single request."""
    request_num: int
    delay_before: float
    status_code: int | None = None
    response_time_ms: float = 0.0
    content_size: int = 0
    headers: dict = field(default_factory=dict)
    error: str | None = None


URL = "https://www.in.gov.br/leiturajornal?data=27-02-2023&secao=do1"
RATE_LIMIT_HEADERS = [
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "retry-after",
    "x-ratelimit",
    "ratelimit",
    "x-rate-limit",
    "rate-limit",
]


def make_request(req_num: int, delay_before: float) -> RequestResult:
    """Make a single request and record metrics."""
    result = RequestResult(request_num=req_num, delay_before=delay_before)
    
    req = Request(
        URL,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "Accept-Encoding": "identity",
            "Connection": "keep-alive",
        }
    )
    
    try:
        start = time.perf_counter()
        with urlopen(req, timeout=30) as response:
            elapsed_ms = (time.perf_counter() - start) * 1000
            result.status_code = response.status
            result.response_time_ms = round(elapsed_ms, 2)
            
            # Read content
            content = response.read()
            result.content_size = len(content)
            
            # Extract rate limit headers (case-insensitive)
            headers_lower = {k.lower(): v for k, v in dict(response.headers).items()}
            for header in RATE_LIMIT_HEADERS:
                if header in headers_lower:
                    result.headers[header] = headers_lower[header]
                    
    except HTTPError as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        result.status_code = e.code
        result.response_time_ms = round(elapsed_ms, 2)
        result.error = str(e.reason)
        
        # Check headers on error too
        headers_lower = {k.lower(): v for k, v in dict(e.headers).items()}
        for header in RATE_LIMIT_HEADERS:
            if header in headers_lower:
                result.headers[header] = headers_lower[header]
                
    except Exception as e:
        result.error = str(e)
    
    return result


def run_test(name: str, num_requests: int, delay: float) -> list[RequestResult]:
    """Run a test with specified parameters."""
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"Requests: {num_requests}, Delay: {delay}s")
    print(f"{'='*60}")
    
    results = []
    for i in range(1, num_requests + 1):
        if delay > 0:
            time.sleep(delay)
        
        result = make_request(i, delay)
        results.append(result)
        
        headers_str = ", ".join([f"{k}={v}" for k, v in result.headers.items()])
        status = f"HTTP {result.status_code}" if result.error is None else f"ERROR: {result.error}"
        print(f"  #{i:2d}: {status} | {result.response_time_ms:6.1f}ms | {result.content_size:6d} bytes | {headers_str}")
    
    return results


def run_burst_test(num_requests: int = 5) -> list[RequestResult]:
    """Run burst test with no delay."""
    print(f"\n{'='*60}")
    print(f"BURST TEST: {num_requests} requests with NO delay")
    print(f"{'='*60}")
    
    results = []
    for i in range(1, num_requests + 1):
        result = make_request(i, 0)
        results.append(result)
        
        headers_str = ", ".join([f"{k}={v}" for k, v in result.headers.items()])
        status = f"HTTP {result.status_code}" if result.error is None else f"ERROR: {result.error}"
        print(f"  #{i:2d}: {status} | {result.response_time_ms:6.1f}ms | {result.content_size:6d} bytes | {headers_str}")
    
    return results


def print_summary(all_results: dict[str, list[RequestResult]]):
    """Print summary statistics."""
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    
    for test_name, results in all_results.items():
        total = len(results)
        successes = sum(1 for r in results if r.status_code == 200)
        errors = total - successes
        avg_time = sum(r.response_time_ms for r in results) / total if total > 0 else 0
        avg_size = sum(r.content_size for r in results) / total if total > 0 else 0
        
        status_codes = {}
        for r in results:
            status_codes[r.status_code] = status_codes.get(r.status_code, 0) + 1
        
        print(f"\n{test_name}:")
        print(f"  Total requests: {total}")
        print(f"  Success (200): {successes}")
        print(f"  Errors: {errors}")
        print(f"  Status codes: {status_codes}")
        print(f"  Avg response time: {avg_time:.1f}ms")
        print(f"  Avg content size: {avg_size:.0f} bytes")


def main():
    """Run all rate limit tests."""
    all_results = {}
    
    # Test 1: 0.5 second delay (10 requests)
    all_results["0.5s delay (10 req)"] = run_test("0.5s delay", 10, 0.5)
    time.sleep(2)  # Cool down between tests
    
    # Test 2: 1.0 second delay (10 requests)
    all_results["1.0s delay (10 req)"] = run_test("1.0s delay", 10, 1.0)
    time.sleep(2)  # Cool down between tests
    
    # Test 3: 2.0 second delay (5 requests)
    all_results["2.0s delay (5 req)"] = run_test("2.0s delay", 5, 2.0)
    time.sleep(2)  # Cool down between tests
    
    # Test 4: Burst (5 requests, no delay)
    all_results["Burst (5 req, no delay)"] = run_burst_test(5)
    
    # Print summary
    print_summary(all_results)
    
    # Save raw results to JSON
    output = {
        name: [asdict(r) for r in results]
        for name, results in all_results.items()
    }
    with open("rate_limit_results.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n\nRaw results saved to rate_limit_results.json")


if __name__ == "__main__":
    main()
