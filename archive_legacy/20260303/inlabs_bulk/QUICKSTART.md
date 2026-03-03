# INLabs Bulk Downloader - Quick Start Guide

## Installation

No installation required - uses standard library + `requests`.

```bash
# Ensure requests is available
pip install requests
```

## Configuration

Set credentials via environment variables:

```bash
export INLABS_USER="fgamajr@gmail.com"
export INLABS_PWD="kqg8YDZ2eya3exq_wev"
```

Or create a `.env` file:
```
INLABS_USER=fgamajr@gmail.com
INLABS_PWD=kqg8YDZ2eya3exq_wev
```

## Common Commands

### 1. Benchmark Performance

Find optimal download settings for your connection:

```bash
python inlabs_bulk/bulk_download.py benchmark --days 3
```

Output:
```
================================================================================
BENCHMARK SUMMARY
================================================================================
Concurrency  Success  Failed   Total MB   Time (s)   Mbps     DL/sec  
--------------------------------------------------------------------------------
1            3        0        10.07      7.0        11.53    0.43    
2            3        0        10.07      4.5        17.99    0.67    
3            3        0        10.07      3.0        26.99    1.01    
5            3        0        10.07      3.1        26.19    0.97    
--------------------------------------------------------------------------------

Optimal configuration: concurrency=3
```

### 2. Download Recent Data

Download last 7 days, all sections:

```bash
python inlabs_bulk/bulk_download.py download --days 7 -o ./inlabs_data
```

Download only main sections (DO1, DO2, DO3):

```bash
python inlabs_bulk/bulk_download.py download --days 7 \
  --sections DO1 DO2 DO3 \
  -o ./inlabs_data
```

### 3. Download Date Range

Download specific range:

```bash
python inlabs_bulk/bulk_download.py download \
  --start 2025-02-01 \
  --end 2025-02-28 \
  -o ./inlabs_feb_2025
```

### 4. Test Rate Limits

Check server rate limiting behavior:

```bash
python inlabs_bulk/bulk_download.py test-rate-limit \
  --date 2026-03-02 \
  --max-requests 30
```

### 5. Discover Available Files

Check what's available for a specific date:

```bash
python inlabs_bulk/bulk_download.py discover --date 2026-03-02
```

## Advanced Options

### Parallel Downloads

Use `--concurrency` to control parallel downloads:

```bash
# Sequential (safest, slowest)
python inlabs_bulk/bulk_download.py download --days 7 -c 1

# Optimal throughput (recommended)
python inlabs_bulk/bulk_download.py download --days 7 -c 3

# Maximum parallelism
python inlabs_bulk/bulk_download.py download --days 7 -c 5
```

### Custom Delay

Add delay between requests for politeness:

```bash
# 1 second delay between requests
python inlabs_bulk/bulk_download.py download --days 7 --delay 1.0
```

### Force Re-download

By default, existing files are skipped. To re-download:

```bash
python inlabs_bulk/bulk_download.py download --days 7 --no-skip-existing
```

### Verbose Logging

Enable debug output:

```bash
python inlabs_bulk/bulk_download.py -v download --days 3
```

## Output Structure

```
inlabs_data/
├── 2026-03-02_DO1.zip
├── 2026-03-02_DO2.zip
├── 2026-03-02_DO3.zip
├── 2026-02-27_DO1.zip
├── 2026-02-27_DO2.zip
├── 2026-02-27_DO3.zip
└── manifest.json
```

The `manifest.json` contains:
- Download status for each file
- SHA256 checksums
- File sizes and download times
- Error messages for failed downloads

## Section Codes

| Code | Description |
|------|-------------|
| DO1 | Seção 1 - Atos do Poder Executivo |
| DO2 | Seção 2 - Atos do Poder Judiciário |
| DO3 | Seção 3 - Atos do Poder Legislativo |
| DO1E | Extra - Seção 1 |
| DO2E | Extra - Seção 2 |
| DO3E | Extra - Seção 3 |

**Note**: Extra editions (DO*E) are not published every day. HTTP 404 for these is expected.

## Troubleshooting

### Authentication Failed

```
ERROR - Login failed - check credentials
```

- Verify `INLABS_USER` and `INLABS_PWD` environment variables
- Check account is active at https://inlabs.in.gov.br

### Rate Limited (rare)

```
WARNING - Rate limited (429), retry after 60s
```

- Reduce concurrency: `-c 1`
- Increase delay: `--delay 1.0`
- Wait and retry later

### File Not Found (404)

```
ERROR - Download failed for 2026-03-02 DO2E: HTTP 404
```

- Expected for extra editions that don't exist
- Check date is valid (not weekend/holiday for some sections)

### Slow Downloads

- Check internet connection speed
- Try different concurrency levels with `benchmark`
- Some ISPs may throttle long-running connections

## Performance Tips

1. **Use concurrency=3** - optimal throughput
2. **Skip existing files** - resume capability
3. **Download during off-peak** - faster speeds
4. **Use SSD storage** - better I/O for many small files

## Python API

```python
from inlabs_bulk import INLabsClient
from datetime import date, timedelta

with INLabsClient() as client:
    # Authenticate
    client.authenticate()
    
    # Download single file
    result = client.download_zip(
        target_date=date(2026, 3, 2),
        section="DO1",
        output_dir="./downloads"
    )
    
    print(f"Downloaded: {result.size_bytes} bytes")
    print(f"SHA256: {result.sha256}")
    print(f"Speed: {result.download_time_ms}ms")
```

## Help

```bash
# General help
python inlabs_bulk/bulk_download.py --help

# Command-specific help
python inlabs_bulk/bulk_download.py download --help
python inlabs_bulk/bulk_download.py benchmark --help
```
