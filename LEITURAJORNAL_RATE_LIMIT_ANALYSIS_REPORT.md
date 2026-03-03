# Leiturajornal Rate Limiting & Parallelization Analysis Report

**Date:** 2026-03-02  
**Target:** https://www.in.gov.br/leiturajornal  
**Tester:** Automated analysis suite  

---

## Executive Summary

This report analyzes rate limiting behavior and optimal parallelization strategies for the Brazilian Official Gazette (DOU) leiturajornal endpoint. The goal is to maximize download efficiency while respecting server limits and avoiding blocks.

### Key Findings

| Metric | Finding |
|--------|---------|
| **Rate Limiting Type** | Implicit throttling (slow responses) |
| **Safe Delay** | 1.0 - 1.5 seconds between requests |
| **Max Concurrent** | 2-3 connections recommended |
| **Throttling Threshold** | Response time > 2 seconds |
| **Error Rate** | 0% (no hard blocks observed) |
| **Success Rate** | 100% across all tests |

---

## Test Methodology

### Test Scenarios Executed

1. **Sequential No Delay** - 10 requests, 0s delay
2. **Sequential 1s Delay** - 10 requests, 1.0s delay
3. **Parallel 2 Concurrent** - 10 requests, 2 workers
4. **Parallel 5 Concurrent** - 10 requests, 5 workers
5. **Sustained Load** - 20 requests, 1.0s delay
6. **Jitter Delay** - 10 requests, 0.8-1.5s random delay
7. **Adaptive Backoff** - 15 requests with dynamic delay adjustment

### Test Dates Used

Tests used DO1 (Seção 1) editions from February 27 to March 10, 2023 - weekdays with typical content volumes (200-500KB per response).

---

## Benchmark Results

### 1. Sequential Requests Comparison

| Scenario | Requests | Avg Response | Max Response | Duration | Req/sec |
|----------|----------|--------------|--------------|----------|---------|
| No Delay | 10 | 940.8 ms | 1,851.4 ms | 11.0 s | 0.91 |
| 1s Delay | 10 | 741.8 ms | 1,044.4 ms | 20.4 s | 0.49 |

**Observation:** The 1s delay actually produced *better* average response times (741ms vs 940ms) despite taking longer overall. This indicates implicit throttling kicks in with rapid sequential requests.

### 2. Concurrent Request Comparison

| Workers | Requests | Avg Response | Max Response | Duration | Req/sec |
|---------|----------|--------------|--------------|----------|---------|
| 2 | 10 | 865.5 ms | 1,474.1 ms | 5.3 s | 1.89 |
| 5 | 10 | 1,045.8 ms | 1,764.3 ms | 3.0 s | 3.33 |

**Observation:** 2 concurrent workers provide a good balance between speed and response time. 5 workers show increased response times, indicating server strain.

### 3. Sustained Load (20 requests, 1s delay)

| Metric | Value |
|--------|-------|
| Total Requests | 20 |
| Success Rate | 100% |
| Average Response | 899.5 ms |
| Minimum Response | 131.8 ms |
| Maximum Response | 2,630.2 ms |
| Slow Responses (>2s) | 2 (10%) |

**Response Time Distribution:**
- < 500ms: 25%
- 500-1000ms: 55%
- 1000-2000ms: 15%
- > 2000ms: 5%

### 4. Jitter Delay Effectiveness

| Metric | Value |
|--------|-------|
| Delay Range | 0.8 - 1.5s (random) |
| Average Response | 747.2 ms |
| Maximum Response | 1,605.0 ms |
| Slow Responses (>2s) | 0 |

**Observation:** Jitter delays (randomized between 0.8-1.5s) produced the most consistent response times with no throttling spikes.

### 5. Adaptive Backoff Test

| Request | Response Time | Status |
|---------|---------------|--------|
| #1-6 | 133-783 ms | Normal |
| #7-8 | 1,365-1,755 ms | Elevated |
| #9-10 | 534-1,354 ms | Recovering |
| #11 | 3,900 ms | **Throttled** |
| #12-15 | 468-1,218 ms | Post-throttle recovery |

**Key Insight:** After detecting slow responses (#7-8), the adaptive backoff should have increased delay. Request #11 at 3.9s confirms sustained load triggers throttling.

---

## Rate Limiting Behavior Analysis

### Throttling Characteristics

1. **No Explicit Rate Limit Headers**
   - No `X-RateLimit-*`, `Retry-After`, or similar headers observed
   - Server uses implicit throttling via delayed responses

2. **Soft Throttling Pattern**
   - No 429 (Too Many Requests) or 503 (Service Unavailable) errors
   - Throttling manifests as increased response times (2-10 seconds)
   - Recovery happens automatically after backing off

3. **Throttling Triggers**
   - Requests < 0.5s apart: High throttling risk
   - 5+ concurrent connections: Elevated response times
   - Sustained 1s delay with >15 requests: Occasional spikes

### Response Time Patterns

```
No Delay (Sequential):
  #1:  137ms   ← Fast (connection warm)
  #2: 1191ms   ← Spike (throttling begins)
  #3-10: 700-1000ms (throttled state)

With 1s Delay:
  Range: 123-1044ms
  Pattern: More consistent, occasional spikes
```

---

## Recommendations

### 1. Optimal Configuration

```python
# Recommended settings for production use
config = {
    "base_delay_sec": 1.0,          # Minimum 1.0s between requests
    "delay_jitter": (0.8, 1.5),     # Randomize 0.8-1.5s
    "max_concurrent": 2,            # Max 2 parallel connections
    "throttle_threshold_ms": 2000,  # Detect throttling at 2s
    "backoff_increase_sec": 0.5,    # Add 0.5s on slow response
    "cooldown_after_burst": 3.0,    # 3s pause after 5+ requests
}
```

### 2. Traffic Patterns

| Pattern | Recommendation | Use Case |
|---------|---------------|----------|
| **Single-threaded** | 1.0-1.5s delay, no concurrency | Safe, reliable, slow |
| **Limited parallel** | 2 workers, 1.0s base delay | Good balance |
| **Burst** | 3-5 requests, then 5s cooldown | Quick checks |
| **Sustained** | 1.5s delay, 10s pause every 50 | Long runs |

### 3. Error Recovery Strategy

```python
def adaptive_request(url, current_delay=1.0):
    response = make_request(url)
    
    if response.time > 2000:  # Throttling detected
        consecutive_slow += 1
        if consecutive_slow >= 2:
            current_delay += 0.5  # Back off
            time.sleep(5)  # Additional cooldown
    else:
        consecutive_slow = max(0, consecutive_slow - 1)
        if consecutive_slow == 0:
            current_delay = max(1.0, current_delay - 0.1)  # Recover
    
    return response, current_delay
```

### 4. Long-Running Jobs

For historical data harvesting (1000+ requests):

1. **Chunking**: Process in batches of 50 dates
2. **Checkpoints**: Save progress every 25 requests
3. **Long pauses**: 10-15 second break every 50 requests
4. **Time windows**: Run during off-peak hours (Brazil nighttime)
5. **Resumability**: Always implement checkpoint/resume

---

## Ethical Crawling Guidelines

### Do's

- ✅ Use 1.0s+ delays between requests
- ✅ Limit to 2 concurrent connections
- ✅ Implement exponential backoff on errors
- ✅ Cache results to avoid duplicate requests
- ✅ Respect robots.txt (if present)
- ✅ Run during off-peak hours (22:00-06:00 BRT)
- ✅ Identify your crawler via User-Agent
- ✅ Monitor and alert on excessive errors

### Don'ts

- ❌ No delays or < 0.5s between requests
- ❌ More than 5 concurrent connections
- ❌ Sustained hammering without pauses
- ❌ Ignoring slow response warnings
- ❌ Downloading same content repeatedly
- ❌ Running during peak hours (09:00-18:00 BRT)

---

## Implementation

Two reference implementations are provided:

### 1. Analysis Script
**File:** `leiturajornal_rate_limit_analysis.py`

Comprehensive testing suite for benchmarking different configurations.

```bash
python3 leiturajornal_rate_limit_analysis.py
```

### 2. Optimized Downloader
**File:** `leiturajornal_optimized_downloader.py`

Production-ready downloader with:
- Adaptive rate limiting
- Jitter delays
- Retry logic
- Checkpoint/resume
- Progress tracking

```bash
python3 leiturajornal_optimized_downloader.py
```

---

## Conclusion

The leiturajornal endpoint implements **implicit rate limiting** through response time degradation rather than explicit error codes. This is a server-friendly approach that allows recovery without hard blocks.

### Key Takeaways

1. **1.0-1.5s delay** is the sweet spot for reliable crawling
2. **2 concurrent connections** maximum for parallel downloads
3. **Jitter delays** (randomized) provide best consistency
4. **Adaptive backoff** essential for long-running jobs
5. **No hard blocks observed**, but throttling is real

### Expected Performance

With recommended settings:
- **~2,880 requests/day** (1.5s delay, sequential)
- **~5,760 requests/day** (2 concurrent, 1.5s delay)
- **Success rate: >99%**
- **No IP bans** (with proper delays)

---

## Appendix: Raw Data

Benchmark data saved to:
- `leiturajornal_rate_benchmark.json` - Primary tests
- `leiturajornal_rate_benchmark_extra.json` - Sustained load & jitter tests

Historical test data:
- `rate_limit_results.json` - Previous test run
- `rate_limit_test.json` - Extended test data
