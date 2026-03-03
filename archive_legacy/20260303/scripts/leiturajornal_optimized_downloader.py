#!/usr/bin/env python3
"""
Optimized Downloader for leiturajornal with Adaptive Rate Limiting.

Implements best practices for ethical and efficient crawling:
- Adaptive delay based on response times
- Jitter to avoid predictable patterns
- Exponential backoff on errors/throttling
- Concurrent request limiting
- Progress tracking and resumability
"""

from __future__ import annotations

import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class DownloadConfig:
    """Configuration for optimized downloading."""
    # Timing
    base_delay_sec: float = 1.0          # Base delay between requests
    min_delay_sec: float = 0.8           # Minimum delay (with jitter)
    max_delay_sec: float = 1.5           # Maximum delay (with jitter)
    burst_cooldown_sec: float = 3.0      # Cooldown after burst
    throttle_cooldown_sec: float = 5.0   # Cooldown on throttling detection
    
    # Concurrency
    max_concurrent: int = 2              # Maximum concurrent requests
    burst_size: int = 3                  # Requests per burst
    
    # Throttling detection
    throttle_threshold_ms: float = 3000  # Response time indicating throttling
    consecutive_slow_threshold: int = 3  # Slow requests before backing off
    
    # Retry
    max_retries: int = 3                 # Max retries per request
    retry_base_delay: float = 2.0        # Base retry delay (exponential)
    
    # Progress
    checkpoint_every: int = 50           # Save progress every N requests
    pause_every: int = 100               # Long pause every N requests
    pause_duration_sec: float = 10.0     # Duration of long pause
    
    # Limits
    request_timeout_sec: float = 30.0
    max_consecutive_failures: int = 10   # Stop after N consecutive failures


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class DownloadResult:
    """Result of a single download attempt."""
    date_str: str
    url: str
    success: bool
    status_code: int | None
    response_time_ms: float
    content_size: int
    attempt_number: int
    error: str | None = None
    timestamp: float = field(default_factory=time.time)
    
    @property
    def is_throttled(self) -> bool:
        """Check if this response indicates throttling."""
        return self.response_time_ms > 3000 or self.status_code in (429, 503, 502)


@dataclass
class DownloadStats:
    """Statistics for a download session."""
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    throttled_responses: int = 0
    total_bytes: int = 0
    avg_response_time_ms: float = 0.0
    current_delay_sec: float = 1.0
    consecutive_failures: int = 0
    consecutive_slow: int = 0
    checkpoints_saved: int = 0


@dataclass
class DownloadSession:
    """Persistent session state for resumable downloads."""
    session_id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S"))
    config: DownloadConfig = field(default_factory=DownloadConfig)
    stats: DownloadStats = field(default_factory=DownloadStats)
    completed_dates: Set[str] = field(default_factory=set)
    failed_dates: Dict[str, int] = field(default_factory=dict)  # date -> retry count
    results: List[DownloadResult] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "config": asdict(self.config),
            "stats": asdict(self.stats),
            "completed_dates": list(self.completed_dates),
            "failed_dates": self.failed_dates,
            "results": [asdict(r) for r in self.results],
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "DownloadSession":
        session = cls()
        session.session_id = data.get("session_id", session.session_id)
        session.config = DownloadConfig(**data.get("config", {}))
        session.stats = DownloadStats(**data.get("stats", {}))
        session.completed_dates = set(data.get("completed_dates", []))
        session.failed_dates = data.get("failed_dates", {})
        return session


# =============================================================================
# Core Downloader
# =============================================================================

class LeiturajornalDownloader:
    """Optimized downloader with adaptive rate limiting."""
    
    BASE_URL = "https://www.in.gov.br/leiturajornal?data={date}&secao={section}"
    
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    ]
    
    def __init__(self, config: DownloadConfig | None = None, session: DownloadSession | None = None):
        self.config = config or DownloadConfig()
        self.session = session or DownloadSession(config=self.config)
        self._current_delay = self.config.base_delay_sec
        self._stop_requested = False
    
    def _get_user_agent(self) -> str:
        """Get random user agent."""
        return random.choice(self.USER_AGENTS)
    
    def _build_url(self, date_str: str, section: str = "do1") -> str:
        """Build URL for date."""
        return self.BASE_URL.format(date=date_str, section=section)
    
    def _calculate_delay(self) -> float:
        """Calculate next delay with jitter and adaptive adjustment."""
        # Base jitter
        delay = random.uniform(self.config.min_delay_sec, self.config.max_delay_sec)
        
        # Add adaptive component based on recent throttling
        if self.session.stats.consecutive_slow > 0:
            backoff = min(self.session.stats.consecutive_slow * 0.5, 3.0)
            delay += backoff
        
        return delay
    
    def _make_request(self, date_str: str, section: str = "do1", attempt: int = 1) -> DownloadResult:
        """Make a single HTTP request."""
        url = self._build_url(date_str, section)
        start_time = time.perf_counter()
        
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": self._get_user_agent(),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                    "Accept-Encoding": "identity",
                    "Connection": "keep-alive",
                    "Cache-Control": "no-cache",
                }
            )
            
            with urlopen(req, timeout=self.config.request_timeout_sec) as response:
                content = response.read()
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                
                return DownloadResult(
                    date_str=date_str,
                    url=url,
                    success=True,
                    status_code=response.status,
                    response_time_ms=elapsed_ms,
                    content_size=len(content),
                    attempt_number=attempt,
                    error=None,
                )
                
        except HTTPError as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            return DownloadResult(
                date_str=date_str,
                url=url,
                success=False,
                status_code=e.code,
                response_time_ms=elapsed_ms,
                content_size=0,
                attempt_number=attempt,
                error=f"HTTP {e.code}: {e.reason}",
            )
        except URLError as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            return DownloadResult(
                date_str=date_str,
                url=url,
                success=False,
                status_code=None,
                response_time_ms=elapsed_ms,
                content_size=0,
                attempt_number=attempt,
                error=f"URL Error: {e.reason}",
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            return DownloadResult(
                date_str=date_str,
                url=url,
                success=False,
                status_code=None,
                response_time_ms=elapsed_ms,
                content_size=0,
                attempt_number=attempt,
                error=f"{type(e).__name__}: {str(e)}",
            )
    
    def _download_with_retry(self, date_str: str, section: str = "do1") -> DownloadResult:
        """Download with retry logic."""
        for attempt in range(1, self.config.max_retries + 1):
            result = self._make_request(date_str, section, attempt)
            
            if result.success:
                return result
            
            # Check if we should retry
            if result.status_code in (429, 503, 502, 504):  # Rate limit or server errors
                if attempt < self.config.max_retries:
                    retry_delay = self.config.retry_base_delay * (2 ** (attempt - 1))
                    print(f"    Retry {attempt}/{self.config.max_retries} for {date_str} after {retry_delay}s...")
                    time.sleep(retry_delay)
                    continue
            else:
                # Non-retryable error
                return result
        
        return result
    
    def _handle_result(self, result: DownloadResult) -> None:
        """Process download result and update stats."""
        self.session.stats.total_requests += 1
        
        if result.success:
            self.session.stats.successful_requests += 1
            self.session.stats.consecutive_failures = 0
            self.session.completed_dates.add(result.date_str)
            
            if result.date_str in self.session.failed_dates:
                del self.session.failed_dates[result.date_str]
        else:
            self.session.stats.failed_requests += 1
            self.session.stats.consecutive_failures += 1
            
            # Track retry count for failed dates
            self.session.failed_dates[result.date_str] = (
                self.session.failed_dates.get(result.date_str, 0) + 1
            )
        
        # Track throttling
        if result.is_throttled:
            self.session.stats.throttled_responses += 1
            self.session.stats.consecutive_slow += 1
        else:
            self.session.stats.consecutive_slow = max(0, self.session.stats.consecutive_slow - 1)
        
        self.session.stats.total_bytes += result.content_size
        
        # Update running average
        n = self.session.stats.total_requests
        old_avg = self.session.stats.avg_response_time_ms
        self.session.stats.avg_response_time_ms = (
            (old_avg * (n - 1) + result.response_time_ms) / n
        )
        
        self.session.results.append(result)
    
    def _should_pause(self) -> bool:
        """Check if we should take a longer pause."""
        return (
            self.session.stats.total_requests > 0 and
            self.session.stats.total_requests % self.config.pause_every == 0
        )
    
    def _should_checkpoint(self) -> bool:
        """Check if we should save progress."""
        return (
            self.session.stats.total_requests > 0 and
            self.session.stats.total_requests % self.config.checkpoint_every == 0
        )
    
    def _adaptive_delay(self) -> None:
        """Apply adaptive delay with optional backoff."""
        delay = self._calculate_delay()
        
        # Extra delay if we've seen consecutive slow responses
        if self.session.stats.consecutive_slow >= self.config.consecutive_slow_threshold:
            delay += self.config.throttle_cooldown_sec
            print(f"    [ADAPTIVE] Adding throttle cooldown ({self.config.throttle_cooldown_sec}s)")
            self.session.stats.consecutive_slow = 0
        
        time.sleep(delay)
    
    def download_single(self, date_str: str, section: str = "do1") -> DownloadResult:
        """Download a single date with full handling."""
        # Skip if already completed
        if date_str in self.session.completed_dates:
            print(f"  {date_str}: Already downloaded, skipping")
            return DownloadResult(
                date_str=date_str,
                url=self._build_url(date_str, section),
                success=True,
                status_code=200,
                response_time_ms=0,
                content_size=0,
                attempt_number=0,
                error=None,
            )
        
        print(f"  Downloading {date_str}...", end=" ", flush=True)
        
        result = self._download_with_retry(date_str, section)
        self._handle_result(result)
        
        status = "✓" if result.success else "✗"
        print(f"{status} HTTP {result.status_code} | {result.response_time_ms:.0f}ms | "
              f"{result.content_size} bytes")
        
        if result.error:
            print(f"    Error: {result.error}")
        
        # Adaptive delay
        self._adaptive_delay()
        
        # Checkpoint if needed
        if self._should_checkpoint():
            self.save_checkpoint()
        
        # Long pause periodically
        if self._should_pause():
            print(f"\n  [PAUSE] Taking {self.config.pause_duration_sec}s break after "
                  f"{self.session.stats.total_requests} requests...")
            time.sleep(self.config.pause_duration_sec)
        
        return result
    
    def download_range(
        self,
        start_date: datetime,
        end_date: datetime,
        section: str = "do1",
        progress_callback: Callable[[DownloadResult], None] | None = None,
    ) -> List[DownloadResult]:
        """Download a range of dates."""
        print(f"\n{'='*70}")
        print(f"DOWNLOAD SESSION: {self.session.session_id}")
        print(f"Range: {start_date.date()} to {end_date.date()}")
        print(f"Section: {section}")
        print(f"Config: delay={self.config.base_delay_sec}s, concurrent={self.config.max_concurrent}")
        print(f"{'='*70}\n")
        
        # Generate business days only (skip weekends)
        dates = []
        current = start_date
        while current <= end_date:
            if current.weekday() < 5:  # Monday = 0, Friday = 4
                dates.append(current.strftime("%d-%m-%Y"))
            current += timedelta(days=1)
        
        print(f"Total dates to download: {len(dates)} (business days only)")
        print(f"Already completed: {len(self.session.completed_dates)}")
        print(f"Previously failed: {len(self.session.failed_dates)}\n")
        
        results = []
        
        for date_str in dates:
            if self._stop_requested:
                print("\n[STOP] Stop requested, saving progress...")
                break
            
            # Check for too many consecutive failures
            if self.session.stats.consecutive_failures >= self.config.max_consecutive_failures:
                print(f"\n[STOP] Too many consecutive failures ({self.session.stats.consecutive_failures})")
                print("This may indicate IP blocking. Saving progress...")
                break
            
            result = self.download_single(date_str, section)
            results.append(result)
            
            if progress_callback:
                progress_callback(result)
        
        self.save_checkpoint()
        self.print_summary()
        
        return results
    
    def download_parallel(
        self,
        dates: List[str],
        section: str = "do1",
    ) -> List[DownloadResult]:
        """Download dates with limited concurrency."""
        print(f"\n{'='*70}")
        print(f"PARALLEL DOWNLOAD: {len(dates)} dates, max {self.config.max_concurrent} concurrent")
        print(f"{'='*70}\n")
        
        results = []
        completed = 0
        
        with ThreadPoolExecutor(max_workers=self.config.max_concurrent) as executor:
            # Submit initial batch
            futures = {}
            pending = [d for d in dates if d not in self.session.completed_dates]
            
            for i, date_str in enumerate(pending[:self.config.burst_size]):
                future = executor.submit(self._download_with_retry, date_str, section)
                futures[future] = date_str
            
            pending = pending[self.config.burst_size:]
            
            while futures:
                # Wait for completion
                for future in as_completed(futures):
                    date_str = futures.pop(future)
                    result = future.result()
                    self._handle_result(result)
                    results.append(result)
                    completed += 1
                    
                    status = "✓" if result.success else "✗"
                    print(f"  [{completed}/{len(dates)}] {date_str}: {status} "
                          f"HTTP {result.status_code} | {result.response_time_ms:.0f}ms")
                    
                    # Submit next if available
                    if pending and not self._stop_requested:
                        next_date = pending.pop(0)
                        new_future = executor.submit(self._download_with_retry, next_date, section)
                        futures[new_future] = next_date
                    
                    break
                
                # Small delay between completions
                time.sleep(0.1)
        
        self.save_checkpoint()
        self.print_summary()
        return results
    
    def save_checkpoint(self, path: str | None = None) -> None:
        """Save session checkpoint."""
        path = path or f"leiturajornal_session_{self.session.session_id}.json"
        with open(path, "w") as f:
            json.dump(self.session.to_dict(), f, indent=2)
        self.session.stats.checkpoints_saved += 1
        print(f"  [CHECKPOINT] Progress saved to {path}")
    
    @classmethod
    def load_checkpoint(cls, path: str) -> "LeiturajornalDownloader":
        """Load from checkpoint."""
        with open(path, "r") as f:
            data = json.load(f)
        
        session = DownloadSession.from_dict(data)
        return cls(config=session.config, session=session)
    
    def print_summary(self) -> None:
        """Print session summary."""
        stats = self.session.stats
        
        print(f"\n{'='*70}")
        print("SESSION SUMMARY")
        print(f"{'='*70}")
        print(f"Session ID: {self.session.session_id}")
        print(f"Started: {stats.started_at}")
        print(f"Total Requests: {stats.total_requests}")
        print(f"Successful: {stats.successful_requests} ({stats.successful_requests/max(1,stats.total_requests)*100:.1f}%)")
        print(f"Failed: {stats.failed_requests}")
        print(f"Throttled: {stats.throttled_responses}")
        print(f"Total Bytes: {stats.total_bytes:,}")
        print(f"Avg Response Time: {stats.avg_response_time_ms:.1f}ms")
        print(f"Checkpoints Saved: {stats.checkpoints_saved}")
        print(f"{'='*70}\n")


# =============================================================================
# CLI / Example Usage
# =============================================================================

def example_single_threaded():
    """Example: Single-threaded download with adaptive rate limiting."""
    config = DownloadConfig(
        base_delay_sec=1.0,
        min_delay_sec=0.8,
        max_delay_sec=1.5,
        max_concurrent=1,
    )
    
    downloader = LeiturajornalDownloader(config)
    
    # Download last 5 business days
    end = datetime.now()
    start = end - timedelta(days=10)
    
    results = downloader.download_range(start, end, section="do1")
    return results


def example_parallel():
    """Example: Parallel download with limited concurrency."""
    config = DownloadConfig(
        base_delay_sec=1.0,
        max_concurrent=2,
        burst_size=2,
    )
    
    downloader = LeiturajornalDownloader(config)
    
    # Download specific dates
    dates = ["27-02-2023", "28-02-2023", "01-03-2023", "02-03-2023", "03-03-2023"]
    results = downloader.download_parallel(dates, section="do1")
    return results


def example_resumable():
    """Example: Resumable download session."""
    # First run - start download
    config = DownloadConfig(
        base_delay_sec=1.0,
        checkpoint_every=3,  # Save every 3 requests for demo
    )
    
    downloader = LeiturajornalDownloader(config)
    
    # Simulate partial download
    end = datetime.now()
    start = end - timedelta(days=7)
    
    # In real usage, this might be interrupted
    # For demo, we just run it
    results = downloader.download_range(start, end, section="do1")
    
    # Save checkpoint
    downloader.save_checkpoint("demo_checkpoint.json")
    
    # Later, resume from checkpoint
    # resumed = LeiturajornalDownloader.load_checkpoint("demo_checkpoint.json")
    # resumed.download_range(start, end, section="do1")
    
    return results


def main():
    """Main entry point with example runs."""
    print("\n" + "="*70)
    print("LEITURAJORNAL OPTIMIZED DOWNLOADER")
    print("="*70)
    print("\nChoose mode:")
    print("  1. Single-threaded (recommended for production)")
    print("  2. Parallel (limited concurrency)")
    print("  3. Resumable demo")
    print("  4. Exit")
    
    choice = input("\nEnter choice (1-4): ").strip()
    
    if choice == "1":
        example_single_threaded()
    elif choice == "2":
        example_parallel()
    elif choice == "3":
        example_resumable()
    else:
        print("Exiting.")


if __name__ == "__main__":
    main()
