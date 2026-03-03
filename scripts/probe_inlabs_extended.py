#!/usr/bin/env python3
"""Extended INLabs probe for older dates to find availability boundary."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, timedelta

# Import the prober from the main script
sys.path.insert(0, '/home/parallels/dev/gabi-kimi/scripts')
from probe_inlabs_availability import INLabsProber, DateTestResult, AvailabilityStatus, ProbeSummary


def run_extended_probe():
    """Test dates going back 180 days to find the availability window."""
    
    username = os.environ.get("INLABS_USER")
    password = os.environ.get("INLABS_PWD")
    
    if not username or not password:
        print("Error: INLABS_USER and INLABS_PWD must be set")
        return 1
    
    prober = INLabsProber(username=username, password=password)
    
    # Test dates from today going back 180 days
    end_date = date.today()
    start_date = end_date - timedelta(days=180)
    
    # Sample every 5 days to cover more range quickly
    dates_to_test = []
    current = start_date
    while current <= end_date:
        dates_to_test.append(current)
        current += timedelta(days=1)
    
    print(f"Testing {len(dates_to_test)} dates from {start_date} to {end_date}")
    print()
    
    results: list[DateTestResult] = []
    
    for i, test_date in enumerate(dates_to_test):
        # Only test with auth for this extended probe
        result = prober.probe_date(test_date, use_auth=True)
        results.append(result)
        
        status_icon = "✓" if result.status == AvailabilityStatus.AVAILABLE.value else "✗"
        doc_count = result.document_count or 0
        print(f"[{i+1:3d}/{len(dates_to_test)}] {test_date} {status_icon} {result.status} docs={doc_count:2d}")
        
        time.sleep(0.3)  # Be polite
    
    # Analyze results
    print("\n" + "="*60)
    print("Extended Analysis")
    print("="*60)
    
    # Find the oldest available date
    available_dates = [r for r in results if r.status == AvailabilityStatus.AVAILABLE.value]
    if available_dates:
        oldest = min(available_dates, key=lambda r: r.date)
        newest = max(available_dates, key=lambda r: r.date)
        print(f"Date range with data: {oldest.date} to {newest.date}")
        print(f"Total available: {len(available_dates)} days")
    
    # Find cutoff point
    sorted_results = sorted(results, key=lambda r: r.date)
    cutoff_found = False
    for i, r in enumerate(sorted_results):
        if r.status == AvailabilityStatus.AVAILABLE.value:
            if i > 0 and sorted_results[i-1].status != AvailabilityStatus.AVAILABLE.value:
                print(f"Availability starts around: {r.date}")
                cutoff_found = True
                # Show context
                print("\nContext around cutoff:")
                for j in range(max(0, i-3), min(len(sorted_results), i+3)):
                    marker = " <-- cutoff" if j == i else ""
                    print(f"  {sorted_results[j].date}: {sorted_results[j].status}{marker}")
                break
    
    if not cutoff_found:
        print("All tested dates are available (no cutoff found in range)")
    
    # Check for any gaps
    print("\nChecking for gaps in available dates...")
    available_count = len(available_dates)
    if available_count >= 2:
        date_objs = [date.fromisoformat(r.date) for r in available_dates]
        min_date = min(date_objs)
        max_date = max(date_objs)
        expected_days = (max_date - min_date).days + 1
        if expected_days != available_count:
            print(f"  WARNING: Expected {expected_days} days, found {available_count}")
            print(f"  There may be gaps in the data")
        else:
            print(f"  No gaps detected ({available_count} consecutive days)")
    
    # Save results
    output_data = {
        "test_type": "extended_180_days",
        "date_range": [start_date.isoformat(), end_date.isoformat()],
        "total_tested": len(results),
        "available_count": len(available_dates),
        "results": [{
            "date": r.date,
            "status": r.status,
            "http_code": r.http_code,
            "document_count": r.document_count,
            "has_content": r.has_content,
        } for r in results]
    }
    
    output_file = "reports/inlabs_probe_extended.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"\nResults saved to: {output_file}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(run_extended_probe())
