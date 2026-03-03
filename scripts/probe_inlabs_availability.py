#!/usr/bin/env python3
"""Systematically probe INLabs historical data availability patterns.

Tests:
1. Date range availability (past 60 days)
2. Weekend vs weekday patterns
3. Month boundaries
4. Authenticated vs unauthenticated access
5. Download link patterns
6. Archive vs fresh data indicators
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import (HTTPCookieProcessor, Request, build_opener,
                           urlopen)
import http.cookiejar
import gzip
import io


class AvailabilityStatus(Enum):
    AVAILABLE = "available"
    EMPTY = "empty"  # Page loads but no documents
    NOT_FOUND = "not_found"  # 404 or equivalent
    FORBIDDEN = "forbidden"  # 403
    ERROR = "error"  # Other errors
    TIMEOUT = "timeout"


@dataclass(slots=True)
class DateTestResult:
    date: str  # ISO format YYYY-MM-DD
    url: str
    status: str  # AvailabilityStatus value
    http_code: int
    has_content: bool
    document_count: int | None
    sections_found: list[str] | None
    response_time_ms: int
    is_weekend: bool
    is_month_start: bool  # First 5 business days of month
    is_month_end: bool  # Last day of month
    auth_used: bool
    error_message: str | None = None
    raw_html_sample: str | None = None  # First 2KB for analysis


@dataclass(slots=True)
class DownloadLinkPattern:
    url_pattern: str
    file_type: str
    count: int
    example_urls: list[str]


@dataclass(slots=True)
class ProbeSummary:
    total_dates_tested: int
    date_range: tuple[str, str]
    auth_configured: bool
    auth_worked: bool
    
    # Availability breakdown
    available_count: int = 0
    empty_count: int = 0
    not_found_count: int = 0
    forbidden_count: int = 0
    error_count: int = 0
    timeout_count: int = 0
    
    # Pattern analysis
    weekday_available: int = 0
    weekend_available: int = 0
    month_start_available: int = 0
    month_end_available: int = 0
    
    # Gaps and inconsistencies
    gaps_found: list[dict[str, Any]] = field(default_factory=list)
    sporadic_dates: list[str] = field(default_factory=list)
    
    # URL patterns discovered
    download_patterns: list[DownloadLinkPattern] = field(default_factory=list)


class INLabsPageParser(HTMLParser):
    """Parse INLabs page to extract document links and sections."""
    
    def __init__(self) -> None:
        super().__init__()
        self.document_links: list[dict[str, str]] = []
        self.sections: list[str] = []
        self.in_script = False
        self.current_tag = ""
        self.current_attrs: dict[str, str] = {}
        
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.current_tag = tag
        self.current_attrs = {k: (v or "") for k, v in attrs}
        
        if tag.lower() == "script":
            self.in_script = True
            
        # Look for document links
        if tag.lower() == "a":
            href = self.current_attrs.get("href", "")
            text = self.current_attrs.get("title", "")
            
            # INLabs PDF download links
            if ".pdf" in href.lower() or "download" in href.lower():
                self.document_links.append({
                    "href": href,
                    "text": text,
                    "type": "pdf"
                })
            # Section links
            elif "secao" in href.lower() or "dou" in href.lower():
                self.sections.append(href)
                
    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script":
            self.in_script = False
            
    def handle_data(self, data: str) -> None:
        # Look for indicators of no content
        pass


class INLabsProber:
    """Probes INLabs for historical data availability."""
    
    BASE_URL = "https://inlabs.in.gov.br/index.php"
    LOGIN_URL = "https://inlabs.in.gov.br/logar.php"
    
    # Brazilian holidays 2025-2026 (for pattern analysis)
    KNOWN_HOLIDAYS = {
        date(2025, 1, 1),   # Confraternização Universal
        date(2025, 4, 18),  # Paixão de Cristo
        date(2025, 4, 21),  # Tiradentes
        date(2025, 5, 1),   # Dia do Trabalho
        date(2025, 6, 19),  # Corpus Christi
        date(2025, 9, 7),   # Independência
        date(2025, 10, 12), # Nossa Senhora Aparecida
        date(2025, 11, 2),  # Finados
        date(2025, 11, 15), # Proclamação da República
        date(2025, 11, 20), # Consciência Negra
        date(2025, 12, 25), # Natal
        date(2026, 1, 1),   # Confraternização Universal
        date(2026, 2, 14),  # Carnaval (likely)
        date(2026, 2, 15),  # Carnaval (likely)
        date(2026, 2, 17),  # Quarta-feira de Cinzas
        date(2026, 4, 3),   # Paixão de Cristo
        date(2026, 4, 21),  # Tiradentes
        date(2026, 5, 1),   # Dia do Trabalho
    }
    
    def __init__(self, username: str | None = None, password: str | None = None) -> None:
        self.username = username
        self.password = password
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookie_jar))
        self.authenticated = False
        self._last_auth_check: datetime | None = None
        
    def _build_url(self, target_date: date) -> str:
        """Build INLabs URL for a specific date."""
        return f"{self.BASE_URL}?p={target_date.isoformat()}"
    
    def _build_headers(self) -> dict[str, str]:
        """Build request headers."""
        return {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.0.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
    
    def authenticate(self) -> bool:
        """Authenticate with INLabs."""
        if not self.username or not self.password:
            return False
            
        # Check if recently authenticated
        if self.authenticated and self._last_auth_check:
            if (datetime.now() - self._last_auth_check).seconds < 300:  # 5 min cache
                return True
        
        try:
            # First, get the login page to capture any CSRF tokens
            login_page_req = Request(
                url=self.LOGIN_URL,
                headers=self._build_headers(),
                method="GET"
            )
            
            with self.opener.open(login_page_req, timeout=30) as resp:
                raw_data = resp.read()
                # Handle gzip
                if raw_data[:2] == b'\x1f\x8b':
                    login_html = gzip.decompress(raw_data).decode("utf-8", errors="ignore")
                else:
                    login_html = raw_data.decode("utf-8", errors="ignore")
            
            # Prepare login data
            login_data = {
                "email": self.username,
                "password": self.password,
            }
            
            # Try to extract any CSRF token
            csrf_match = re.search(r'name=["\'](_csrf|csrf_token|token)["\'][^>]*value=["\']([^"\']+)', login_html, re.I)
            if csrf_match:
                login_data[csrf_match.group(1)] = csrf_match.group(2)
            
            # Submit login
            post_data = urlencode(login_data).encode("utf-8")
            login_req = Request(
                url=self.LOGIN_URL,
                data=post_data,
                headers={
                    **self._build_headers(),
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": self.LOGIN_URL,
                },
                method="POST"
            )
            
            t0 = time.monotonic()
            with self.opener.open(login_req, timeout=30) as resp:
                response_url = resp.geturl()
                raw_data = resp.read()
                # Handle gzip
                if raw_data[:2] == b'\x1f\x8b':
                    response_body = gzip.decompress(raw_data).decode("utf-8", errors="ignore")
                else:
                    response_body = raw_data.decode("utf-8", errors="ignore")
            
            # Check if login succeeded (redirected away from login page or session cookie set)
            self.authenticated = self.LOGIN_URL not in response_url and "senha" not in response_body.lower()
            self._last_auth_check = datetime.now()
            
            return self.authenticated
            
        except Exception as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return False
    
    def probe_date(self, target_date: date, use_auth: bool = False) -> DateTestResult:
        """Probe a single date for availability."""
        url = self._build_url(target_date)
        
        # Authenticate if needed
        if use_auth and not self.authenticate():
            return DateTestResult(
                date=target_date.isoformat(),
                url=url,
                status=AvailabilityStatus.ERROR.value,
                http_code=0,
                has_content=False,
                document_count=None,
                sections_found=None,
                response_time_ms=0,
                is_weekend=target_date.weekday() >= 5,
                is_month_start=target_date.day <= 5 and self._is_business_day(target_date),
                is_month_end=target_date.day == self._days_in_month(target_date),
                auth_used=use_auth,
                error_message="Authentication failed"
            )
        
        try:
            t0 = time.monotonic()
            req = Request(
                url=url,
                headers=self._build_headers(),
                method="GET"
            )
            
            with self.opener.open(req, timeout=30) as resp:
                raw_data = resp.read()
                response_time_ms = int((time.monotonic() - t0) * 1000)
                http_code = int(getattr(resp, "status", 200))
                final_url = resp.geturl()
                
                # Handle gzip compression
                try:
                    # Check if content is gzip compressed
                    if raw_data[:2] == b'\x1f\x8b':  # gzip magic bytes
                        html = gzip.decompress(raw_data).decode("utf-8", errors="ignore")
                    else:
                        html = raw_data.decode("utf-8", errors="ignore")
                except Exception:
                    html = raw_data.decode("utf-8", errors="ignore")
            
            # Parse the page
            parser = INLabsPageParser()
            parser.feed(html)
            
            # Determine availability - check for various indicators
            html_lower = html.lower()
            
            # Check for content indicators
            has_content = len(parser.document_links) > 0 or len(parser.sections) > 0
            has_dou_content = "diário oficial" in html_lower or "dou" in html_lower or "secao" in html_lower
            has_no_content_msg = "nenhum documento" in html_lower or "não disponível" in html_lower or "nao disponivel" in html_lower
            is_login_page = "login" in html_lower and "senha" in html_lower
            is_maintenance = "manutenção" in html_lower or "maintenance" in html_lower or "indisponível" in html_lower
            
            # Additional checks for actual content
            doc_count = html_lower.count(".pdf")
            has_sections = bool(re.search(r'secao|seção|secao', html_lower))
            
            if is_maintenance:
                status = AvailabilityStatus.ERROR
            elif is_login_page and not use_auth:
                status = AvailabilityStatus.FORBIDDEN
            elif has_no_content_msg:
                status = AvailabilityStatus.EMPTY
            elif has_content or has_dou_content or doc_count > 0 or has_sections:
                status = AvailabilityStatus.AVAILABLE
                has_content = True
            else:
                status = AvailabilityStatus.EMPTY
            
            return DateTestResult(
                date=target_date.isoformat(),
                url=url,
                status=status.value,
                http_code=http_code,
                has_content=has_content,
                document_count=len(parser.document_links),
                sections_found=parser.sections[:10],  # Limit stored sections
                response_time_ms=response_time_ms,
                is_weekend=target_date.weekday() >= 5,
                is_month_start=target_date.day <= 5 and self._is_business_day(target_date),
                is_month_end=target_date.day == self._days_in_month(target_date),
                auth_used=use_auth,
                raw_html_sample=html[:4096] if status != AvailabilityStatus.AVAILABLE.value else html[:1024]
            )
            
        except HTTPError as e:
            status = AvailabilityStatus.FORBIDDEN if e.code == 403 else \
                     AvailabilityStatus.NOT_FOUND if e.code == 404 else AvailabilityStatus.ERROR
            return DateTestResult(
                date=target_date.isoformat(),
                url=url,
                status=status.value,
                http_code=int(e.code),
                has_content=False,
                document_count=0,
                sections_found=None,
                response_time_ms=int((time.monotonic() - t0) * 1000) if 't0' in dir() else 0,
                is_weekend=target_date.weekday() >= 5,
                is_month_start=target_date.day <= 5 and self._is_business_day(target_date),
                is_month_end=target_date.day == self._days_in_month(target_date),
                auth_used=use_auth,
                error_message=f"HTTPError: {e.reason}"
            )
        except URLError as e:
            return DateTestResult(
                date=target_date.isoformat(),
                url=url,
                status=AvailabilityStatus.ERROR.value,
                http_code=0,
                has_content=False,
                document_count=0,
                sections_found=None,
                response_time_ms=0,
                is_weekend=target_date.weekday() >= 5,
                is_month_start=target_date.day <= 5 and self._is_business_day(target_date),
                is_month_end=target_date.day == self._days_in_month(target_date),
                auth_used=use_auth,
                error_message=f"URLError: {e.reason}"
            )
        except Exception as e:
            return DateTestResult(
                date=target_date.isoformat(),
                url=url,
                status=AvailabilityStatus.ERROR.value,
                http_code=0,
                has_content=False,
                document_count=0,
                sections_found=None,
                response_time_ms=0,
                is_weekend=target_date.weekday() >= 5,
                is_month_start=target_date.day <= 5 and self._is_business_day(target_date),
                is_month_end=target_date.day == self._days_in_month(target_date),
                auth_used=use_auth,
                error_message=f"Exception: {str(e)[:200]}"
            )
    
    def _is_business_day(self, d: date) -> bool:
        """Check if date is a business day (not weekend, not holiday)."""
        if d.weekday() >= 5:  # Saturday or Sunday
            return False
        if d in self.KNOWN_HOLIDAYS:
            return False
        return True
    
    def _days_in_month(self, d: date) -> int:
        """Return number of days in month."""
        if d.month == 12:
            next_month = date(d.year + 1, 1, 1)
        else:
            next_month = date(d.year, d.month + 1, 1)
        return (next_month - timedelta(days=1)).day
    
    def analyze_download_patterns(self, results: list[DateTestResult]) -> list[DownloadLinkPattern]:
        """Analyze download URL patterns from results."""
        patterns: dict[str, dict[str, Any]] = {}
        
        for result in results:
            if result.sections_found:
                for url in result.sections_found:
                    # Extract pattern
                    pattern = self._extract_pattern(url)
                    if pattern not in patterns:
                        patterns[pattern] = {"count": 0, "examples": []}
                    patterns[pattern]["count"] += 1
                    if len(patterns[pattern]["examples"]) < 3:
                        patterns[pattern]["examples"].append(url)
        
        return [
            DownloadLinkPattern(
                url_pattern=p,
                file_type="html/pdf",
                count=d["count"],
                example_urls=d["examples"]
            )
            for p, d in patterns.items()
        ]
    
    def _extract_pattern(self, url: str) -> str:
        """Extract URL pattern by replacing variable parts."""
        # Replace dates
        pattern = re.sub(r'\d{4}-\d{2}-\d{2}', '{DATE}', url)
        pattern = re.sub(r'\d{4}/\d{2}/\d{2}', '{DATE}', pattern)
        pattern = re.sub(r'\d{2}-\d{2}-\d{4}', '{DATE}', pattern)
        # Replace numbers
        pattern = re.sub(r'\d+', '{N}', pattern)
        return pattern


def find_gaps(results: list[DateTestResult]) -> list[dict[str, Any]]:
    """Find gaps in availability."""
    gaps = []
    sorted_results = sorted(results, key=lambda r: r.date)
    
    # Group consecutive available and unavailable dates
    current_gap: list[str] = []
    for result in sorted_results:
        if result.status == AvailabilityStatus.AVAILABLE.value:
            if len(current_gap) >= 3:  # Only report gaps of 3+ days
                gaps.append({
                    "type": "unavailable_streak",
                    "start": current_gap[0],
                    "end": current_gap[-1],
                    "length": len(current_gap)
                })
            current_gap = []
        else:
            current_gap.append(result.date)
    
    # Also find sporadic availability (isolated available dates surrounded by unavailable)
    for i, result in enumerate(sorted_results):
        if result.status == AvailabilityStatus.AVAILABLE.value:
            prev_status = sorted_results[i-1].status if i > 0 else None
            next_status = sorted_results[i+1].status if i < len(sorted_results) - 1 else None
            
            # Isolated available date
            if prev_status and next_status:
                if prev_status != AvailabilityStatus.AVAILABLE.value and \
                   next_status != AvailabilityStatus.AVAILABLE.value:
                    gaps.append({
                        "type": "sporadic_available",
                        "date": result.date,
                        "context": [prev_status, next_status]
                    })
    
    return gaps


def run_probe(days: int = 60, auth: bool = True, output: str = "inlabs_probe_results.json") -> int:
    """Run the full availability probe."""
    
    # Get credentials from environment if not provided
    username = None
    password = None
    
    if auth:
        import os
        username = os.environ.get("INLABS_USER")
        password = os.environ.get("INLABS_PWD")
        
        if not username or not password:
            print("Warning: INLABS_USER and/or INLABS_PWD not set in environment", file=sys.stderr)
            print("Authentication will be skipped", file=sys.stderr)
            auth = False
    
    prober = INLabsProber(username=username, password=password)
    
    # Generate dates to test (past N days)
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    
    dates_to_test = []
    current = start_date
    while current <= end_date:
        dates_to_test.append(current)
        current += timedelta(days=1)
    
    print(f"Probing INLabs availability for {len(dates_to_test)} dates...")
    print(f"Range: {start_date} to {end_date}")
    print(f"Authentication: {'enabled' if auth else 'disabled'}")
    print()
    
    results: list[DateTestResult] = []
    
    # Test each date
    for i, test_date in enumerate(dates_to_test):
        # First test without auth
        result_no_auth = prober.probe_date(test_date, use_auth=False)
        results.append(result_no_auth)
        
        status_icon = "✓" if result_no_auth.status == AvailabilityStatus.AVAILABLE.value else "✗"
        print(f"[{i+1:3d}/{len(dates_to_test)}] {test_date} {status_icon} {result_no_auth.status} "
              f"({result_no_auth.response_time_ms}ms)", end="")
        
        # If auth is enabled and unauthenticated request failed, try with auth
        if auth and result_no_auth.status != AvailabilityStatus.AVAILABLE.value:
            result_auth = prober.probe_date(test_date, use_auth=True)
            if result_auth.status == AvailabilityStatus.AVAILABLE.value:
                results[-1] = result_auth  # Replace with auth result
                print(f" [AUTH OK]", end="")
        
        print()
        
        # Small delay to be polite
        time.sleep(0.5)
    
    # Analyze patterns
    print("\nAnalyzing patterns...")
    
    summary = ProbeSummary(
        total_dates_tested=len(results),
        date_range=(start_date.isoformat(), end_date.isoformat()),
        auth_configured=auth,
        auth_worked=any(r.auth_used for r in results),
    )
    
    # Count availability
    for r in results:
        if r.status == AvailabilityStatus.AVAILABLE.value:
            summary.available_count += 1
            if not r.is_weekend:
                summary.weekday_available += 1
            else:
                summary.weekend_available += 1
            if r.is_month_start:
                summary.month_start_available += 1
            if r.is_month_end:
                summary.month_end_available += 1
        elif r.status == AvailabilityStatus.EMPTY.value:
            summary.empty_count += 1
        elif r.status == AvailabilityStatus.NOT_FOUND.value:
            summary.not_found_count += 1
        elif r.status == AvailabilityStatus.FORBIDDEN.value:
            summary.forbidden_count += 1
        elif r.status == AvailabilityStatus.ERROR.value:
            summary.error_count += 1
        elif r.status == AvailabilityStatus.TIMEOUT.value:
            summary.timeout_count += 1
    
    # Find gaps
    summary.gaps_found = find_gaps(results)
    
    # Find sporadic dates (older than 30 days that are available)
    cutoff = (end_date - timedelta(days=30)).isoformat()
    summary.sporadic_dates = [
        r.date for r in results 
        if r.date < cutoff and r.status == AvailabilityStatus.AVAILABLE.value
    ]
    
    # Analyze download patterns
    summary.download_patterns = prober.analyze_download_patterns(results)
    
    # Save results
    output_data = {
        "summary": {
            "total_dates_tested": summary.total_dates_tested,
            "date_range": summary.date_range,
            "auth_configured": summary.auth_configured,
            "auth_worked": summary.auth_worked,
            "availability": {
                "available": summary.available_count,
                "empty": summary.empty_count,
                "not_found": summary.not_found_count,
                "forbidden": summary.forbidden_count,
                "error": summary.error_count,
                "timeout": summary.timeout_count,
            },
            "patterns": {
                "weekday_available": summary.weekday_available,
                "weekend_available": summary.weekend_available,
                "month_start_available": summary.month_start_available,
                "month_end_available": summary.month_end_available,
            },
            "gaps_found": summary.gaps_found,
            "sporadic_dates": summary.sporadic_dates,
            "download_patterns": [
                {"pattern": p.url_pattern, "count": p.count, "examples": p.example_urls}
                for p in summary.download_patterns
            ],
        },
        "results": [asdict(r) for r in results],
    }
    
    with open(output, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    # Print summary
    print("\n" + "="*60)
    print("INLabs Availability Probe Summary")
    print("="*60)
    print(f"Dates tested: {summary.total_dates_tested}")
    print(f"Date range: {summary.date_range[0]} to {summary.date_range[1]}")
    print(f"Authentication: {'Yes (worked)' if summary.auth_worked else 'No/failed'}")
    print()
    print("Availability:")
    print(f"  Available:  {summary.available_count} ({summary.available_count/len(results)*100:.1f}%)")
    print(f"  Empty:      {summary.empty_count}")
    print(f"  Not Found:  {summary.not_found_count}")
    print(f"  Forbidden:  {summary.forbidden_count}")
    print(f"  Error:      {summary.error_count}")
    print()
    print("Patterns:")
    print(f"  Weekday available: {summary.weekday_available}")
    print(f"  Weekend available: {summary.weekend_available}")
    print(f"  Month start available: {summary.month_start_available}")
    print(f"  Month end available: {summary.month_end_available}")
    print()
    
    if summary.gaps_found:
        print(f"Gaps found: {len(summary.gaps_found)}")
        for gap in summary.gaps_found[:5]:  # Show first 5
            print(f"  - {gap['type']}: {gap.get('date') or gap.get('start') + ' to ' + gap.get('end')}")
    
    if summary.sporadic_dates:
        print(f"\nSporadic old dates (>30 days): {len(summary.sporadic_dates)}")
        for d in summary.sporadic_dates[:10]:
            print(f"  - {d}")
    
    print(f"\nFull results saved to: {output}")
    
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe INLabs historical data availability")
    parser.add_argument("--days", type=int, default=60, help="Number of days to test")
    parser.add_argument("--no-auth", action="store_true", help="Skip authentication")
    parser.add_argument("--output", default="inlabs_probe_results.json", help="Output JSON file")
    
    args = parser.parse_args()
    
    return run_probe(days=args.days, auth=not args.no_auth, output=args.output)


if __name__ == "__main__":
    raise SystemExit(main())
