"""INLabs Bulk Download Package.

Optimized bulk downloader for INLabs DOU ZIP files with:
- Rate limiting detection and handling
- Parallel download support
- Resume/retry logic
- Performance benchmarking
"""

from inlabs_bulk.inlabs_client import INLabsClient, DownloadResult, BenchmarkResult, DOU_SECTIONS

__all__ = ["INLabsClient", "DownloadResult", "BenchmarkResult", "DOU_SECTIONS"]
