"""INLabs API client with authentication and ZIP download capabilities."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

INLABS_BASE_URL = "https://inlabs.in.gov.br"
INLABS_LOGIN_URL = f"{INLABS_BASE_URL}/logar.php"
INLABS_HOME_URL = f"{INLABS_BASE_URL}/index.php"

# All DOU sections available in INLabs
DOU_SECTIONS = ["DO1", "DO2", "DO3", "DO1E", "DO2E", "DO3E"]

DEFAULT_TIMEOUT = 60
DEFAULT_MAX_RETRIES = 3


@dataclass(slots=True)
class DownloadResult:
    """Result of a single download operation."""

    date: date
    section: str
    success: bool
    url: str | None = None
    local_path: Path | None = None
    size_bytes: int = 0
    sha256: str | None = None
    download_time_ms: int = 0
    error: str | None = None
    http_status: int | None = None
    retry_after: int | None = None


@dataclass(slots=True)
class BenchmarkResult:
    """Benchmark results for download performance."""

    concurrency: int
    total_downloads: int
    successful: int
    failed: int
    total_bytes: int
    total_time_ms: int
    avg_speed_mbps: float
    downloads_per_sec: float
    results: list[DownloadResult] = field(default_factory=list)


class INLabsClient:
    """Authenticated client for INLabs bulk downloads."""

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        session_cookie: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self.username = username or os.getenv("INLABS_USER")
        self.password = password or os.getenv("INLABS_PWD")
        self.session_cookie = session_cookie or os.getenv("GABI_INLABS_COOKIE")
        self.timeout = timeout
        self.max_retries = max_retries
        self._session: requests.Session | None = None
        self._authenticated = False
        self._last_request_time = 0.0
        self._request_count = 0
        self._request_count_start = 0.0

    def _get_session(self) -> requests.Session:
        """Get or create a requests session with retry configuration."""
        if self._session is None:
            self._session = requests.Session()
            retry_strategy = Retry(
                total=self.max_retries,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "POST"],
            )
            adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)
            self._session.mount("https://", adapter)
            self._session.mount("http://", adapter)

            # Set default headers to look like a browser
            self._session.headers.update({
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            })

            # Use provided cookie if available
            if self.session_cookie:
                self._session.headers["Cookie"] = self.session_cookie
                self._authenticated = True

        return self._session

    def authenticate(self) -> bool:
        """Authenticate with INLabs using username/password."""
        if self._authenticated and self._session:
            return True

        if not self.username or not self.password:
            log.error("No credentials provided for INLabs authentication")
            return False

        session = self._get_session()

        try:
            # Get login page to extract CSRF token if needed
            log.info("Fetching login page...")
            resp = session.get(INLABS_LOGIN_URL, timeout=self.timeout)
            resp.raise_for_status()

            # Try to find any CSRF token or hidden fields
            csrf_match = re.search(r'name=["\'](_token|csrf_token|authenticity_token)["\']\s+value=["\']([^"\']+)["\']', resp.text)
            csrf_token = csrf_match.group(2) if csrf_match else None

            # Prepare login payload
            payload: dict[str, str] = {
                "email": self.username,
                "password": self.password,
            }
            if csrf_token:
                payload["_token"] = csrf_token

            # Submit login
            log.info("Submitting login credentials...")
            login_resp = session.post(
                INLABS_LOGIN_URL,
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": INLABS_LOGIN_URL,
                },
                timeout=self.timeout,
                allow_redirects=True,
            )
            login_resp.raise_for_status()

            # Check if login was successful (redirect to home or dashboard)
            if "logout" in login_resp.text.lower() or "bem-vindo" in login_resp.text.lower():
                log.info("Successfully authenticated with INLabs")
                self._authenticated = True

                # Extract and store session cookie for future use
                cookies = session.cookies.get_dict()
                if cookies:
                    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
                    log.info("Session cookie: %s", cookie_str[:50] + "...")
                    self.session_cookie = cookie_str

                return True
            else:
                log.error("Login failed - check credentials")
                return False

        except requests.RequestException as e:
            log.error("Authentication request failed: %s", e)
            return False

    def _build_zip_url(self, d: date, section: str) -> str:
        """Build the INLabs ZIP download URL for a date and section.
        
        Section format: DO1, DO2, DO3, DO1E, DO2E, DO3E
        URL format: ?p=YYYY-MM-DD&dl=YYYY-MM-DD-SECTION.zip
        """
        date_str = d.strftime("%Y-%m-%d")
        return f"{INLABS_BASE_URL}/index.php?p={date_str}&dl={date_str}-{section}.zip"

    def _rate_limit(self, min_delay: float = 0.0) -> None:
        """Apply rate limiting between requests."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < min_delay:
            time.sleep(min_delay - elapsed)
        self._last_request_time = time.monotonic()

    def discover_available_files(
        self,
        target_date: date,
        sections: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Discover available ZIP files for a given date."""
        if not self._authenticated:
            if not self.authenticate():
                return []

        sections = sections or DOU_SECTIONS
        session = self._get_session()
        date_str = target_date.strftime("%Y-%m-%d")
        page_url = f"{INLABS_BASE_URL}/index.php?p={date_str}"

        available = []

        try:
            log.info("Discovering files for %s...", date_str)
            self._rate_limit(0.5)

            resp = session.get(page_url, timeout=self.timeout)
            resp.raise_for_status()

            # Look for download links in the page
            for section in sections:
                zip_url = self._build_zip_url(target_date, section)
                # Check if the section link exists in the page
                if f"dl={section}.zip" in resp.text or section in resp.text:
                    available.append({
                        "date": date_str,
                        "section": section,
                        "url": zip_url,
                    })

            log.info("Found %d sections for %s", len(available), date_str)
            return available

        except requests.RequestException as e:
            log.error("Discovery failed for %s: %s", date_str, e)
            return []

    def download_zip(
        self,
        target_date: date,
        section: str,
        output_dir: Path,
        skip_existing: bool = True,
        min_delay: float = 0.0,
    ) -> DownloadResult:
        """Download a single ZIP file with resume/retry support."""
        result = DownloadResult(date=target_date, section=section, success=False)

        if not self._authenticated:
            if not self.authenticate():
                result.error = "Authentication failed"
                return result

        url = self._build_zip_url(target_date, section)
        result.url = url

        date_str = target_date.strftime("%Y-%m-%d")
        filename = f"{date_str}_{section}.zip"
        filepath = output_dir / filename
        result.local_path = filepath

        # Check if already exists
        if skip_existing and filepath.exists():
            existing_size = filepath.stat().st_size
            if existing_size > 0:
                # Verify with SHA256 if we can
                sha256 = self._compute_sha256(filepath)
                result.success = True
                result.size_bytes = existing_size
                result.sha256 = sha256
                result.download_time_ms = 0
                log.debug("Skipping existing file: %s (%d bytes)", filename, existing_size)
                return result

        session = self._get_session()
        temp_filepath = filepath.with_suffix(".zip.tmp")

        start_time = time.monotonic()

        try:
            self._rate_limit(min_delay)

            # Check for partial download to resume
            headers = {}
            if temp_filepath.exists():
                resume_pos = temp_filepath.stat().st_size
                headers["Range"] = f"bytes={resume_pos}-"
                log.debug("Resuming download from byte %d", resume_pos)

            resp = session.get(
                url,
                headers=headers,
                timeout=self.timeout,
                stream=True,
            )

            result.http_status = resp.status_code

            # Check for rate limiting
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                result.retry_after = retry_after
                result.error = f"Rate limited (429), retry after {retry_after}s"
                log.warning("Rate limited on %s %s, retry-after: %ds", date_str, section, retry_after)
                return result

            if resp.status_code not in (200, 206):
                result.error = f"HTTP {resp.status_code}"
                log.error("Download failed for %s %s: HTTP %d", date_str, section, resp.status_code)
                return result

            # Stream download to disk
            mode = "ab" if resp.status_code == 206 else "wb"
            total_bytes = 0

            with open(temp_filepath, mode) as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        total_bytes += len(chunk)

            # Move temp file to final location
            temp_filepath.rename(filepath)

            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            sha256 = self._compute_sha256(filepath)

            result.success = True
            result.size_bytes = total_bytes
            result.sha256 = sha256
            result.download_time_ms = elapsed_ms

            speed_mbps = (total_bytes * 8 / 1_000_000) / (elapsed_ms / 1000) if elapsed_ms > 0 else 0
            log.info(
                "Downloaded %s %s: %d bytes in %dms (%.2f Mbps)",
                date_str, section, total_bytes, elapsed_ms, speed_mbps
            )

        except requests.RequestException as e:
            result.error = str(e)
            log.error("Download error for %s %s: %s", date_str, section, e)
        except Exception as e:
            result.error = f"Unexpected error: {e}"
            log.error("Unexpected error for %s %s: %s", date_str, section, e)

        return result

    def download_batch(
        self,
        dates: list[date],
        sections: list[str],
        output_dir: Path,
        concurrency: int = 1,
        delay_between_requests: float = 0.5,
        skip_existing: bool = True,
    ) -> list[DownloadResult]:
        """Download multiple ZIP files with configurable concurrency."""
        output_dir.mkdir(parents=True, exist_ok=True)

        # Build download queue
        downloads = [
            (d, section)
            for d in dates
            for section in sections
        ]

        log.info(
            "Starting batch download: %d dates × %d sections = %d files (concurrency=%d)",
            len(dates), len(sections), len(downloads), concurrency
        )

        results: list[DownloadResult] = []

        if concurrency == 1:
            # Sequential download
            for target_date, section in downloads:
                result = self.download_zip(
                    target_date, section, output_dir,
                    skip_existing=skip_existing,
                    min_delay=delay_between_requests,
                )
                results.append(result)
        else:
            # Parallel download with thread pool
            # Note: Each thread needs its own client instance or we need to handle session carefully
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = {
                    executor.submit(
                        self._download_worker,
                        target_date, section, output_dir, skip_existing, delay_between_requests
                    ): (target_date, section)
                    for target_date, section in downloads
                }

                for future in as_completed(futures):
                    result = future.result()
                    results.append(result)

        return results

    def _download_worker(
        self,
        target_date: date,
        section: str,
        output_dir: Path,
        skip_existing: bool,
        min_delay: float,
    ) -> DownloadResult:
        """Worker function for parallel downloads."""
        return self.download_zip(
            target_date, section, output_dir,
            skip_existing=skip_existing,
            min_delay=min_delay,
        )

    def benchmark_downloads(
        self,
        dates: list[date],
        sections: list[str],
        output_dir: Path,
        concurrency_levels: list[int] = [1, 2, 3, 5],
    ) -> list[BenchmarkResult]:
        """Run download benchmarks at different concurrency levels."""
        benchmarks: list[BenchmarkResult] = []

        for concurrency in concurrency_levels:
            log.info("=" * 60)
            log.info("Benchmarking with concurrency=%d", concurrency)
            log.info("=" * 60)

            start_time = time.monotonic()
            results = self.download_batch(
                dates=dates,
                sections=sections,
                output_dir=output_dir / f"benchmark_c{concurrency}",
                concurrency=concurrency,
                delay_between_requests=0.1 if concurrency > 1 else 0.5,
                skip_existing=False,
            )
            total_time_ms = int((time.monotonic() - start_time) * 1000)

            successful = [r for r in results if r.success]
            failed = [r for r in results if not r.success]
            total_bytes = sum(r.size_bytes for r in successful)

            avg_speed = (total_bytes * 8 / 1_000_000) / (total_time_ms / 1000) if total_time_ms > 0 else 0
            downloads_per_sec = len(successful) / (total_time_ms / 1000) if total_time_ms > 0 else 0

            benchmark = BenchmarkResult(
                concurrency=concurrency,
                total_downloads=len(results),
                successful=len(successful),
                failed=len(failed),
                total_bytes=total_bytes,
                total_time_ms=total_time_ms,
                avg_speed_mbps=avg_speed,
                downloads_per_sec=downloads_per_sec,
                results=results,
            )
            benchmarks.append(benchmark)

            log.info(
                "Concurrency=%d: %d/%d success, %.2f MB, %.2f Mbps, %.2f downloads/sec",
                concurrency,
                benchmark.successful,
                benchmark.total_downloads,
                total_bytes / 1_000_000,
                avg_speed,
                downloads_per_sec,
            )

            # Small delay between benchmark runs
            time.sleep(2)

        return benchmarks

    def test_rate_limits(
        self,
        target_date: date,
        section: str = "DO1",
        max_requests: int = 20,
        delay_between_requests: float = 0.1,
    ) -> dict[str, Any]:
        """Test rate limiting by making rapid requests."""
        log.info("Testing rate limits with %d rapid requests...", max_requests)

        session = self._get_session()
        url = self._build_zip_url(target_date, section)

        results = []
        rate_limited = False
        rate_limit_count = 0
        retry_after_values = []

        for i in range(max_requests):
            start = time.monotonic()
            try:
                resp = session.head(url, timeout=self.timeout, allow_redirects=False)
                elapsed_ms = int((time.monotonic() - start) * 1000)

                result = {
                    "request_num": i + 1,
                    "status": resp.status_code,
                    "elapsed_ms": elapsed_ms,
                    "headers": dict(resp.headers),
                }

                if resp.status_code == 429:
                    rate_limited = True
                    rate_limit_count += 1
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after:
                        retry_after_values.append(int(retry_after))
                    result["retry_after"] = retry_after

                results.append(result)

            except requests.RequestException as e:
                results.append({
                    "request_num": i + 1,
                    "error": str(e),
                })

            if i < max_requests - 1:
                time.sleep(delay_between_requests)

        return {
            "target_date": target_date.isoformat(),
            "section": section,
            "total_requests": max_requests,
            "rate_limited": rate_limited,
            "rate_limit_count": rate_limit_count,
            "retry_after_values": retry_after_values,
            "results": results,
        }

    @staticmethod
    def _compute_sha256(filepath: Path) -> str:
        """Compute SHA256 hash of a file."""
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def close(self) -> None:
        """Close the session and cleanup."""
        if self._session:
            self._session.close()
            self._session = None

    def __enter__(self) -> INLabsClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
