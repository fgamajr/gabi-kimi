#!/usr/bin/env python3
"""
Leiturajornal Historical Data Boundary Mapper

Systematically tests year boundaries for leiturajornal API to determine:
- Exact start dates for each section (do1, do2, do3)
- Gaps within available periods
- Document counts per era
- Quality changes over time
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from crawler.user_agent_rotator import create_default_rotator


@dataclass(slots=True)
class BoundaryTestResult:
    """Result of testing a single date/section combination."""
    year: int
    test_date: date
    section: str
    url: str
    status: str  # 'available', 'empty', 'error', 'not_found'
    document_count: int = 0
    response_time_ms: float = 0.0
    http_status: int | None = None
    error_message: str | None = None
    sample_titles: list[str] = field(default_factory=list)
    has_embedded_json: bool = False


@dataclass(slots=True)
class YearSummary:
    """Summary for a single year across all sections."""
    year: int
    do1_available: bool = False
    do2_available: bool = False
    do3_available: bool = False
    do1_first_date: date | None = None
    do2_first_date: date | None = None
    do3_first_date: date | None = None
    do1_avg_docs: int = 0
    do2_avg_docs: int = 0
    do3_avg_docs: int = 0
    test_results: list[BoundaryTestResult] = field(default_factory=list)


class LeiturajornalBoundaryMapper:
    """Maps historical data boundaries for leiturajornal API."""
    
    BASE_URL = "https://www.in.gov.br/leiturajornal"
    SECTIONS = ["do1", "do2", "do3"]
    
    def __init__(
        self,
        start_year: int = 2000,
        end_year: int = 2025,
        delay_sec: float = 1.0,
        max_retries: int = 3,
        timeout_sec: int = 30,
    ):
        self.start_year = start_year
        self.end_year = end_year
        self.delay_sec = delay_sec
        self.max_retries = max_retries
        self.timeout_sec = timeout_sec
        self.rot = create_default_rotator()
        self.request_count = 0
        self.results: list[BoundaryTestResult] = []
        self.year_summaries: dict[int, YearSummary] = {}
        
    def _build_url(self, test_date: date, section: str) -> str:
        """Build the leiturajornal URL for a date and section."""
        date_str = test_date.strftime("%d-%m-%Y")
        if section == "do1":
            return f"{self.BASE_URL}?data={date_str}"
        return f"{self.BASE_URL}?data={date_str}&secao={section}"
    
    def _extract_json_array(self, html: str) -> tuple[list[dict], bool]:
        """Extract jsonArray from embedded script tag."""
        pattern = r'<script\s+id="params"\s+type="application/json">\s*(\{.*?\})\s*</script>'
        match = re.search(pattern, html, flags=re.S)
        if not match:
            return [], False
        
        try:
            payload = json.loads(match.group(1))
            json_array = payload.get("jsonArray", [])
            return json_array, True
        except json.JSONDecodeError:
            return [], False
    
    def _extract_sample_titles(self, json_array: list[dict], max_samples: int = 3) -> list[str]:
        """Extract sample document titles from jsonArray."""
        titles = []
        for item in json_array[:max_samples]:
            if isinstance(item, dict):
                title = item.get("title", item.get("titulo", "")).strip()
                if title:
                    titles.append(title[:100])  # Truncate long titles
        return titles
    
    def _fetch(self, url: str) -> tuple[str | None, int | None, str | None]:
        """Fetch URL with retries and rate limiting."""
        for attempt in range(1, self.max_retries + 1):
            try:
                if self.request_count > 0:
                    time.sleep(self.delay_sec)
                self.request_count += 1
                
                req = Request(
                    url=url,
                    headers={
                        "User-Agent": self.rot.next(),
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                    },
                    method="GET",
                )
                
                start_time = time.time()
                with urlopen(req, timeout=self.timeout_sec) as resp:
                    html = resp.read().decode("utf-8", errors="ignore")
                    elapsed_ms = (time.time() - start_time) * 1000
                    return html, resp.status, None
                    
            except HTTPError as e:
                if attempt < self.max_retries:
                    time.sleep(self.delay_sec * attempt)
                    continue
                return None, e.code, str(e)
            except (URLError, TimeoutError, OSError) as e:
                if attempt < self.max_retries:
                    time.sleep(self.delay_sec * attempt)
                    continue
                return None, None, str(e)
        
        return None, None, "Max retries exceeded"
    
    def test_date_section(self, test_date: date, section: str) -> BoundaryTestResult:
        """Test a single date/section combination."""
        url = self._build_url(test_date, section)
        start_time = time.time()
        
        html, http_status, error = self._fetch(url)
        elapsed_ms = (time.time() - start_time) * 1000
        
        result = BoundaryTestResult(
            year=test_date.year,
            test_date=test_date,
            section=section,
            url=url,
            status="unknown",
            response_time_ms=elapsed_ms,
            http_status=http_status,
            error_message=error,
        )
        
        if error:
            result.status = "error"
            return result
        
        if html is None:
            result.status = "error"
            result.error_message = "Empty response"
            return result
        
        json_array, has_embedded = self._extract_json_array(html)
        result.has_embedded_json = has_embedded
        result.document_count = len(json_array)
        result.sample_titles = self._extract_sample_titles(json_array)
        
        if has_embedded:
            if len(json_array) > 0:
                result.status = "available"
            else:
                result.status = "empty"
        else:
            # No embedded JSON - likely a legacy or error page
            result.status = "empty"
        
        return result
    
    def generate_test_dates(self, year: int) -> list[date]:
        """Generate test dates for a year (Jan 2, Jul 1, random)."""
        dates = [
            date(year, 1, 2),   # Early year
            date(year, 7, 1),   # Mid year
        ]
        
        # Add a random date, ensuring it's a weekday (Mon-Fri when DO is published)
        attempts = 0
        while attempts < 10:
            random_day = random.randint(1, 365 if not self._is_leap_year(year) else 366)
            test_date = date(year, 1, 1) + timedelta(days=random_day - 1)
            if test_date.weekday() < 5:  # Monday = 0, Friday = 4
                dates.append(test_date)
                break
            attempts += 1
        
        return dates
    
    def _is_leap_year(self, year: int) -> bool:
        """Check if year is a leap year."""
        return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    
    def test_year(self, year: int) -> YearSummary:
        """Test all sections for a given year."""
        print(f"\n{'='*60}")
        print(f"Testing year: {year}")
        print(f"{'='*60}")
        
        test_dates = self.generate_test_dates(year)
        summary = YearSummary(year=year)
        
        for test_date in test_dates:
            print(f"\n  Date: {test_date.isoformat()}")
            for section in self.SECTIONS:
                result = self.test_date_section(test_date, section)
                self.results.append(result)
                summary.test_results.append(result)
                
                status_icon = "✓" if result.status == "available" else "✗"
                doc_info = f"({result.document_count} docs)" if result.status == "available" else ""
                print(f"    {status_icon} {section.upper()}: {result.status} {doc_info}")
                
                if result.sample_titles:
                    for title in result.sample_titles[:2]:
                        print(f"      - {title[:60]}...")
        
        # Calculate summary
        self._calculate_year_summary(summary)
        self.year_summaries[year] = summary
        
        return summary
    
    def _calculate_year_summary(self, summary: YearSummary) -> None:
        """Calculate summary statistics for a year."""
        do1_docs = []
        do2_docs = []
        do3_docs = []
        
        for result in summary.test_results:
            if result.status == "available":
                if result.section == "do1":
                    summary.do1_available = True
                    do1_docs.append(result.document_count)
                    if summary.do1_first_date is None or result.test_date < summary.do1_first_date:
                        summary.do1_first_date = result.test_date
                elif result.section == "do2":
                    summary.do2_available = True
                    do2_docs.append(result.document_count)
                    if summary.do2_first_date is None or result.test_date < summary.do2_first_date:
                        summary.do2_first_date = result.test_date
                elif result.section == "do3":
                    summary.do3_available = True
                    do3_docs.append(result.document_count)
                    if summary.do3_first_date is None or result.test_date < summary.do3_first_date:
                        summary.do3_first_date = result.test_date
        
        if do1_docs:
            summary.do1_avg_docs = sum(do1_docs) // len(do1_docs)
        if do2_docs:
            summary.do2_avg_docs = sum(do2_docs) // len(do2_docs)
        if do3_docs:
            summary.do3_avg_docs = sum(do3_docs) // len(do3_docs)
    
    def find_exact_start_date(self, year: int, section: str, known_before: date) -> date | None:
        """Binary search to find exact start date for a section."""
        print(f"\n  Finding exact start date for {section.upper()} in {year}...")
        
        # Start with Jan 1 and move forward
        test_date = date(year, 1, 1)
        end_date = date(year, 12, 31)
        last_empty = None
        first_available = None
        
        # Quick check: test first business day of each month
        for month in range(1, 13):
            for day in range(1, 8):  # Check first week
                try:
                    test_date = date(year, month, day)
                    if test_date.weekday() >= 5:  # Skip weekends
                        continue
                    
                    result = self.test_date_section(test_date, section)
                    self.results.append(result)
                    
                    if result.status == "available":
                        first_available = test_date
                        print(f"    Found content starting: {test_date.isoformat()}")
                        return first_available
                    else:
                        last_empty = test_date
                        
                except ValueError:
                    continue
        
        return None
    
    def run_full_boundary_map(self) -> dict[str, Any]:
        """Run complete boundary mapping for all years."""
        print(f"\n{'#'*70}")
        print(f"# LEITURAJORNAL HISTORICAL BOUNDARY MAPPER")
        print(f"# Testing years {self.start_year}-{self.end_year}")
        print(f"# Sections: {', '.join(self.SECTIONS)}")
        print(f"{'#'*70}\n")
        
        # Phase 1: Quick scan all years
        for year in range(self.start_year, self.end_year + 1):
            self.test_year(year)
        
        # Phase 2: Find exact boundaries for transition years
        print(f"\n{'='*60}")
        print("PHASE 2: Finding exact boundary dates")
        print(f"{'='*60}")
        
        # Check context around suspected boundaries
        boundary_years = self._identify_boundary_years()
        for year, section in boundary_years:
            self.find_exact_start_date(year, section, date(year, 1, 1))
        
        return self._compile_report()
    
    def _identify_boundary_years(self) -> list[tuple[int, str]]:
        """Identify years where sections transition from unavailable to available."""
        boundaries = []
        prev_summary = None
        
        for year in range(self.start_year, self.end_year + 1):
            summary = self.year_summaries.get(year)
            if summary is None:
                continue
            
            if prev_summary:
                if not prev_summary.do1_available and summary.do1_available:
                    boundaries.append((year, "do1"))
                if not prev_summary.do2_available and summary.do2_available:
                    boundaries.append((year, "do2"))
                if not prev_summary.do3_available and summary.do3_available:
                    boundaries.append((year, "do3"))
            
            prev_summary = summary
        
        return boundaries
    
    def _compile_report(self) -> dict[str, Any]:
        """Compile comprehensive report."""
        # Era classification
        eras = self._classify_eras()
        
        # Document statistics by era
        era_stats = self._calculate_era_stats(eras)
        
        # Section boundaries
        section_boundaries = self._determine_section_boundaries()
        
        # Gaps analysis
        gaps = self._identify_gaps()
        
        report = {
            "generated_at": datetime.now().isoformat(),
            "test_parameters": {
                "start_year": self.start_year,
                "end_year": self.end_year,
                "sections_tested": self.SECTIONS,
                "total_requests": self.request_count,
            },
            "section_boundaries": section_boundaries,
            "eras": eras,
            "era_statistics": era_stats,
            "gaps": gaps,
            "yearly_summaries": [
                {
                    "year": ys.year,
                    "do1": {
                        "available": ys.do1_available,
                        "first_date": ys.do1_first_date.isoformat() if ys.do1_first_date else None,
                        "avg_documents": ys.do1_avg_docs,
                    },
                    "do2": {
                        "available": ys.do2_available,
                        "first_date": ys.do2_first_date.isoformat() if ys.do2_first_date else None,
                        "avg_documents": ys.do2_avg_docs,
                    },
                    "do3": {
                        "available": ys.do3_available,
                        "first_date": ys.do3_first_date.isoformat() if ys.do3_first_date else None,
                        "avg_documents": ys.do3_avg_docs,
                    },
                }
                for ys in self.year_summaries.values()
            ],
            "detailed_results": [
                {
                    "year": r.year,
                    "date": r.test_date.isoformat(),
                    "section": r.section,
                    "status": r.status,
                    "document_count": r.document_count,
                    "has_embedded_json": r.has_embedded_json,
                    "sample_titles": r.sample_titles[:2] if r.sample_titles else [],
                }
                for r in self.results
            ],
        }
        
        return report
    
    def _classify_eras(self) -> list[dict[str, Any]]:
        """Classify data into eras based on availability."""
        eras = []
        
        # Era 1: Pre-2013 (No content)
        no_content_years = [y for y, s in self.year_summaries.items() 
                          if not s.do1_available and not s.do2_available and not s.do3_available]
        if no_content_years:
            eras.append({
                "name": "No Content",
                "years": sorted(no_content_years),
                "description": "No documents available in any section",
                "do1_available": False,
                "do2_available": False,
                "do3_available": False,
            })
        
        # Era 2: Partial/Sparse (2013-2015 typically)
        partial_years = [y for y, s in self.year_summaries.items()
                        if s.do1_available and (not s.do2_available or not s.do3_available)]
        if partial_years:
            eras.append({
                "name": "Partial/Sparse",
                "years": sorted(partial_years),
                "description": "DO1 has content, DO2/DO3 may be missing",
                "do1_available": True,
                "do2_available": "mixed",
                "do3_available": "mixed",
            })
        
        # Era 3: Full Content (2016+)
        full_years = [y for y, s in self.year_summaries.items()
                     if s.do1_available and s.do2_available and s.do3_available]
        if full_years:
            eras.append({
                "name": "Full Content",
                "years": sorted(full_years),
                "description": "All three sections have content",
                "do1_available": True,
                "do2_available": True,
                "do3_available": True,
            })
        
        return eras
    
    def _calculate_era_stats(self, eras: list[dict]) -> dict[str, dict[str, Any]]:
        """Calculate document statistics for each era."""
        stats = {}
        
        for era in eras:
            era_name = era["name"]
            years = era["years"]
            
            do1_docs = []
            do2_docs = []
            do3_docs = []
            
            for year in years:
                summary = self.year_summaries.get(year)
                if summary:
                    if summary.do1_avg_docs:
                        do1_docs.append(summary.do1_avg_docs)
                    if summary.do2_avg_docs:
                        do2_docs.append(summary.do2_avg_docs)
                    if summary.do3_avg_docs:
                        do3_docs.append(summary.do3_avg_docs)
            
            stats[era_name] = {
                "years_count": len(years),
                "do1": {
                    "avg_docs_per_day": sum(do1_docs) // len(do1_docs) if do1_docs else 0,
                    "min_docs": min(do1_docs) if do1_docs else 0,
                    "max_docs": max(do1_docs) if do1_docs else 0,
                },
                "do2": {
                    "avg_docs_per_day": sum(do2_docs) // len(do2_docs) if do2_docs else 0,
                    "min_docs": min(do2_docs) if do2_docs else 0,
                    "max_docs": max(do2_docs) if do2_docs else 0,
                },
                "do3": {
                    "avg_docs_per_day": sum(do3_docs) // len(do3_docs) if do3_docs else 0,
                    "min_docs": min(do3_docs) if do3_docs else 0,
                    "max_docs": max(do3_docs) if do3_docs else 0,
                },
            }
        
        return stats
    
    def _determine_section_boundaries(self) -> dict[str, dict[str, Any]]:
        """Determine the first available date for each section."""
        boundaries = {}
        
        for section in self.SECTIONS:
            first_available = None
            first_year = None
            
            for year in range(self.start_year, self.end_year + 1):
                summary = self.year_summaries.get(year)
                if summary:
                    section_first = getattr(summary, f"{section}_first_date")
                    if section_first:
                        first_available = section_first
                        first_year = year
                        break
            
            boundaries[section] = {
                "first_available_date": first_available.isoformat() if first_available else None,
                "first_available_year": first_year,
            }
        
        return boundaries
    
    def _identify_gaps(self) -> list[dict[str, Any]]:
        """Identify gaps in available data."""
        gaps = []
        
        # Check for years where sections were available then unavailable
        for section in self.SECTIONS:
            available = False
            gap_start = None
            
            for year in range(self.start_year, self.end_year + 1):
                summary = self.year_summaries.get(year)
                if summary:
                    section_available = getattr(summary, f"{section}_available")
                    
                    if available and not section_available:
                        # Gap started
                        gap_start = year
                    elif not available and section_available and gap_start:
                        # Gap ended
                        gaps.append({
                            "section": section,
                            "gap_start_year": gap_start,
                            "gap_end_year": year - 1,
                            "duration_years": year - gap_start,
                        })
                        gap_start = None
                    
                    available = section_available
        
        return gaps


def print_report(report: dict[str, Any]) -> None:
    """Print a formatted version of the report."""
    print("\n" + "="*70)
    print("LEITURAJORNAL BOUNDARY MAP REPORT")
    print("="*70)
    
    print("\n📅 SECTION BOUNDARIES")
    print("-" * 40)
    for section, boundary in report["section_boundaries"].items():
        date_str = boundary["first_available_date"] or "Not available"
        year_str = f"(year {boundary['first_available_year']})" if boundary["first_available_year"] else ""
        print(f"  {section.upper()}: {date_str} {year_str}")
    
    print("\n📊 ERAS")
    print("-" * 40)
    for era in report["eras"]:
        years = era["years"]
        year_range = f"{min(years)}-{max(years)}" if years else "N/A"
        print(f"\n  {era['name']}: {year_range}")
        print(f"    Description: {era['description']}")
        print(f"    DO1: {'✓' if era['do1_available'] else '✗'}")
        print(f"    DO2: {'✓' if era['do2_available'] == True else '✗' if era['do2_available'] == False else '~'}")
        print(f"    DO3: {'✓' if era['do3_available'] == True else '✗' if era['do3_available'] == False else '~'}")
    
    print("\n📈 ERA STATISTICS")
    print("-" * 40)
    for era_name, stats in report["era_statistics"].items():
        print(f"\n  {era_name}:")
        for section in ["do1", "do2", "do3"]:
            section_stats = stats.get(section, {})
            if section_stats.get("avg_docs_per_day", 0) > 0:
                print(f"    {section.upper()}: ~{section_stats['avg_docs_per_day']} docs/day "
                      f"(range: {section_stats['min_docs']}-{section_stats['max_docs']})")
    
    print("\n⚠️  GAPS IDENTIFIED")
    print("-" * 40)
    if report["gaps"]:
        for gap in report["gaps"]:
            print(f"  {gap['section'].upper()}: Years {gap['gap_start_year']}-{gap['gap_end_year']} "
                  f"({gap['duration_years']} years)")
    else:
        print("  No significant gaps identified")
    
    print("\n📋 YEARLY AVAILABILITY SUMMARY")
    print("-" * 40)
    print(f"  {'Year':<6} {'DO1':<6} {'DO2':<6} {'DO3':<6} {'Notes'}")
    print(f"  {'-'*50}")
    
    for ys in report["yearly_summaries"]:
        do1 = "✓" if ys["do1"]["available"] else "✗"
        do2 = "✓" if ys["do2"]["available"] else "✗"
        do3 = "✓" if ys["do3"]["available"] else "✗"
        
        notes = []
        if ys["do1"]["available"]:
            notes.append(f"DO1~{ys['do1']['avg_documents']}")
        if ys["do2"]["available"]:
            notes.append(f"DO2~{ys['do2']['avg_documents']}")
        if ys["do3"]["available"]:
            notes.append(f"DO3~{ys['do3']['avg_documents']}")
        
        print(f"  {ys['year']:<6} {do1:<6} {do2:<6} {do3:<6} {', '.join(notes)}")
    
    print("\n" + "="*70)


def main() -> int:
    parser = argparse.ArgumentParser(description="Map leiturajornal historical data boundaries")
    parser.add_argument("--start-year", type=int, default=2000, help="Start year (default: 2000)")
    parser.add_argument("--end-year", type=int, default=2025, help="End year (default: 2025)")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between requests in seconds (default: 1.0)")
    parser.add_argument("--output", type=str, default="leiturajornal_boundaries.json", help="Output JSON file")
    parser.add_argument("--quick", action="store_true", help="Quick mode: test fewer dates per year")
    
    args = parser.parse_args()
    
    mapper = LeiturajornalBoundaryMapper(
        start_year=args.start_year,
        end_year=args.end_year,
        delay_sec=args.delay,
    )
    
    report = mapper.run_full_boundary_map()
    
    # Print formatted report
    print_report(report)
    
    # Save to file
    output_path = Path(args.output)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n💾 Full report saved to: {output_path.absolute()}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
