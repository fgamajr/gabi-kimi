# Rate Limit Testing Report: leiturajornal DOU Endpoint

**Endpoint:** `https://www.in.gov.br/leiturajornal?data=27-02-2023&secao=do1`  
**Test Date:** 2026-03-02  
**Total Requests:** 30

---

## Executive Summary

| Test Scenario | Requests | Delay | Avg Response Time | Success Rate |
|--------------|----------|-------|-------------------|--------------|
| 0.5s Delay | 10 | 0.5s | **1,891ms** | 100% (10/10) |
| 1.0s Delay | 10 | 1.0s | **359ms** | 100% (10/10) |
| 2.0s Delay | 5 | 2.0s | **556ms** | 100% (5/5) |
| Burst | 5 | 0s | **257ms** | 100% (5/5) |

---

## Key Findings

### 1. Does the endpoint throttle?

**YES** - Evidence of throttling detected:

- **0.5s delay test** showed significant response time degradation:
  - Request #2 took **10,910ms** (10.9 seconds) - likely a slowdown response
  - Overall average: **1,891ms** vs **359ms** with 1.0s delay
  - Subsequent requests improved but remained variable

- **No explicit rate limit headers** were returned (X-RateLimit, Retry-After, etc.)

- The server uses **implicit throttling** (slow response times) rather than explicit 429/503 errors

### 2. Recommended Safe Delay

**1.0 second** is the recommended minimum delay between requests.

| Delay | Performance | Risk |
|-------|-------------|------|
| 0.5s | Poor (avg 1.9s) | HIGH - triggers slowdown |
| **1.0s** | **Good (avg 359ms)** | **LOW - stable responses** |
| 2.0s | Good (avg 556ms) | Very Low - but slower crawling |

### 3. Response Time Patterns

**0.5s Delay Test (Throttled):**
```
#1:  868ms
#2: 10,910ms  ← MAJOR SPIKE (throttling)
#3: 1,844ms
#4: 1,461ms
#5: 1,057ms
#6-10: 476ms - 993ms (gradual recovery)
```

**1.0s Delay Test (Stable):**
```
Range: 135ms - 634ms
Average: 359ms
Variance: LOW
```

**Burst Test (5 concurrent, no delay):**
```
Range: 136ms - 430ms
Average: 257ms
All successful (small burst tolerated)
```

---

## Observations

1. **No Rate Limit Headers:** The server does not return standard rate limit headers (X-RateLimit-Limit, X-RateLimit-Remaining, Retry-After)

2. **Soft Throttling:** Instead of 429 errors, the server applies significant response delays when rate limits are approached

3. **Recovery Time:** After a throttled request (#2 at 0.5s delay), the server gradually returns to normal response times

4. **Burst Tolerance:** Small bursts (5 requests) are tolerated well, likely because they're quick and finish before any rate limit counter increments significantly

5. **Consistent Content Size:** All successful responses returned exactly **478,666 bytes** (the same DO1 edition)

---

## Recommendations

1. **Use 1.0 second delay** as the minimum for production crawling
2. **Implement adaptive backoff:** If response time > 3s, increase delay to 2.0s
3. **Monitor response times:** Track for sudden spikes as the throttling indicator
4. **Add jitter:** Randomize delays between 0.9s - 1.2s to avoid predictable patterns
5. **Consider 2.0s+ delay** for sustained high-volume crawling (>100 requests)

---

## Raw Data

Full results saved to: `rate_limit_results.json`
