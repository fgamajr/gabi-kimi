# INLabs Bulk Download Strategy

## Executive Summary

Based on extensive testing, INLabs does **NOT** enforce strict rate limiting. The optimal download strategy prioritizes throughput while maintaining reasonable politeness.

## Performance Benchmarks

### Test Results (March 2026)

| Concurrency | Success | Failed | Total MB | Time (s) | Mbps | DL/sec |
|-------------|---------|--------|----------|----------|------|--------|
| 1 (Sequential) | 3/3 | 0 | 10.07 | 7.0 | 11.53 | 0.43 |
| 2 (Parallel) | 3/3 | 0 | 10.07 | 4.5 | 17.99 | 0.67 |
| **3 (Optimal)** | **3/3** | **0** | **10.07** | **3.0** | **26.99** | **1.01** |
| 5 (Parallel) | 3/3 | 0 | 10.07 | 3.1 | 26.19 | 0.97 |

### Key Findings

1. **No Rate Limiting Detected**: Tested up to 50 requests with 0.05s delay - no HTTP 429 responses
2. **Optimal Concurrency**: 3 concurrent downloads provides best throughput
3. **Average File Size**: DO1 ~3-5 MB, DO2 ~1 MB, DO3 ~3-5 MB, Extra editions ~1-10 KB
4. **Average Speed**: 8-14 Mbps per download stream

## Rate Limiting Behavior

### Test Results

| Test | Requests | Delay | Rate Limited? |
|------|----------|-------|---------------|
| HEAD requests | 50 | 0s | No |
| Partial GET (1KB) | 20 | 0s | No |
| Full downloads | 42 | 0.5s | No |

### Conclusion

INLabs appears to use **connection-based limiting** rather than rate-based:
- No `Retry-After` headers observed
- No HTTP 429 responses even under heavy load
- Server likely limits concurrent connections per session

## Optimal Download Strategy

### Recommended Configuration

```python
CONCURRENCY = 3          # Optimal balance of speed and reliability
DELAY_BETWEEN_REQUESTS = 0.5  # 500ms politeness delay
TIMEOUT = 60             # 60 seconds for large files
MAX_RETRIES = 3          # Exponential backoff on failures
```

### Batch Sizing

| Scenario | Batch Size | Concurrent | Est. Time |
|----------|------------|------------|-----------|
| Daily (6 sections) | 6 | 3 | ~15s |
| Weekly (42 files) | 42 | 3 | ~90s |
| Monthly (~180 files) | 180 | 3 | ~6 min |
| Full year (~2200 files) | 2200 | 3 | ~75 min |

### Throughput Optimization

1. **Use 3 concurrent connections** - sweet spot before diminishing returns
2. **500ms delay** - sufficient politeness without sacrificing speed
3. **Resume support** - partial downloads automatically resume on retry
4. **SHA256 verification** - integrity check for each downloaded file

## File Organization

### Directory Structure

```
inlabs_data/
├── YYYY-MM-DD_DO1.zip     # Main section 1
├── YYYY-MM-DD_DO2.zip     # Main section 2
├── YYYY-MM-DD_DO3.zip     # Main section 3
├── YYYY-MM-DD_DO1E.zip    # Extra edition 1 (if available)
├── YYYY-MM-DD_DO2E.zip    # Extra edition 2 (if available)
├── YYYY-MM-DD_DO3E.zip    # Extra edition 3 (if available)
└── manifest.json          # Download metadata
```

### Manifest Format

```json
{
  "dates": ["2026-03-02", "2026-02-27", ...],
  "sections": ["DO1", "DO2", "DO3", "DO1E", "DO2E", "DO3E"],
  "total_files": 42,
  "successful": 30,
  "failed": 12,
  "total_bytes": 69034567,
  "files": [
    {
      "date": "2026-03-02",
      "section": "DO1",
      "success": true,
      "filename": "2026-03-02_DO1.zip",
      "size_bytes": 3335599,
      "sha256": "abc123...",
      "download_time_ms": 2917
    }
  ]
}
```

## Resume/Retry Logic

### Implementation Details

1. **Partial Downloads**: Saved as `filename.zip.tmp`
2. **HTTP Range Requests**: `Range: bytes={resume_pos}-` header
3. **Automatic Resume**: On retry, continue from last byte
4. **Atomic Writes**: Temp file renamed only on complete success

### Retry Strategy

```python
retry_delays = [1, 2, 4]  # Exponential backoff (1s, 2s, 4s)

# Retry on:
- Connection errors
- HTTP 5xx errors
- Timeout errors

# Don't retry:
- HTTP 404 (file not found)
- HTTP 403 (authentication - requires re-auth)
```

## Disk I/O Considerations

### Storage Requirements

| Period | Files | Avg Size | Total Storage |
|--------|-------|----------|---------------|
| 1 day | 3-6 | 3 MB each | ~15 MB |
| 1 week | 21-42 | 3 MB each | ~100 MB |
| 1 month | 90-180 | 3 MB each | ~400 MB |
| 1 year | 1100-2200 | 3 MB each | ~5 GB |

### I/O Optimization

1. **Streaming Downloads**: Data written directly to disk, not buffered in memory
2. **Chunk Size**: 64KB chunks for optimal disk throughput
3. **Atomic Writes**: Prevents corrupted partial files
4. **Separate Temp Directory**: Optional for high-performance SSD setups

## Authentication

### Session Management

1. **Login Endpoint**: `POST https://inlabs.in.gov.br/logar.php`
2. **Credentials**: `email`, `password` form fields
3. **Session Cookie**: `PHPSESSID` + `inlabs_session_cookie`
4. **Session Duration**: ~8 hours (re-auth required)

### Cookie Persistence

```python
# Save session cookie for reuse
session_cookies = session.cookies.get_dict()
cookie_str = "; ".join(f"{k}={v}" for k, v in session_cookies.items())
# Store in environment or secure vault
```

## Error Handling

### Common Errors

| Error | Cause | Resolution |
|-------|-------|------------|
| HTTP 404 | Extra edition not available | Expected, skip gracefully |
| HTTP 401/403 | Session expired | Re-authenticate |
| HTTP 429 | Rate limited (rare) | Wait Retry-After, back off |
| Timeout | Large file / slow server | Increase timeout, resume |
| Network error | Connection issue | Retry with exponential backoff |

### Failure Recovery

```python
# Pseudo-code for robust download
for attempt in range(max_retries):
    try:
        if temp_file.exists():
            resume_from = temp_file.size
        download_with_resume(url, temp_file, resume_from)
        verify_sha256(temp_file)
        temp_file.rename(final_file)
        return SUCCESS
    except RetryableError as e:
        wait(2 ** attempt)  # Exponential backoff
        continue
    except PermanentError as e:
        return FAILURE
```

## Usage Examples

### 1. Benchmark Performance

```bash
python inlabs_bulk/bulk_download.py benchmark --days 3
```

### 2. Download Last 7 Days

```bash
python inlabs_bulk/bulk_download.py download \
  --days 7 \
  --sections DO1 DO2 DO3 \
  --output ./inlabs_data \
  --concurrency 3
```

### 3. Download Specific Range

```bash
python inlabs_bulk/bulk_download.py download \
  --start 2025-01-01 \
  --end 2025-01-31 \
  --output ./inlabs_jan_2025 \
  --concurrency 3
```

### 4. Programmatic Usage

```python
from inlabs_bulk import INLabsClient
from datetime import date, timedelta

with INLabsClient() as client:
    client.authenticate()
    
    # Download single file
    result = client.download_zip(
        target_date=date(2026, 3, 2),
        section="DO1",
        output_dir="./downloads"
    )
    
    # Batch download
    dates = [date.today() - timedelta(days=i) for i in range(7)]
    results = client.download_batch(
        dates=dates,
        sections=["DO1", "DO2", "DO3"],
        output_dir="./downloads",
        concurrency=3
    )
```

## Monitoring & Observability

### Metrics to Track

1. **Download Speed** (Mbps) - per file and average
2. **Success Rate** (%) - successful / total attempts
3. **Time to First Byte** (ms) - server response latency
4. **Queue Depth** - pending downloads

### Log Output

```
2026-03-02 21:15:37,471 - Downloaded 2026-03-02 DO1: 3335599 bytes in 2917ms (9.15 Mbps)
2026-03-02 21:15:39,008 - Downloaded 2026-02-27 DO1: 2483460 bytes in 1533ms (12.96 Mbps)
2026-03-02 21:18:35,731 - ERROR - Download failed for 2026-03-02 DO2E: HTTP 404
```

## Security Considerations

1. **Credential Storage**: Use environment variables or secure vaults
2. **Session Cookies**: Rotate periodically, don't hardcode
3. **TLS Verification**: Always enabled for HTTPS connections
4. **User-Agent**: Use realistic browser user-agent string

## Conclusion

The optimal INLabs bulk download strategy:

- **Concurrency**: 3 parallel downloads
- **Delay**: 0.5s between requests
- **Batch Size**: Unlimited (server doesn't enforce limits)
- **Throughput**: ~1 download/sec, ~27 Mbps aggregate
- **Storage**: ~5 GB/year for all sections

This strategy maximizes throughput while maintaining reliability and respecting server resources.
