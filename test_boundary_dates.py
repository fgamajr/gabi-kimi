#!/usr/bin/env python3
"""Focused testing for boundary dates."""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

from crawler.user_agent_rotator import create_default_rotator


def fetch(url: str, rot) -> tuple[str | None, list[dict]]:
    """Fetch URL and extract jsonArray."""
    try:
        req = Request(
            url=url,
            headers={
                "User-Agent": rot.next(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            },
            method="GET",
        )
        
        with urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            
        pattern = r'<script\s+id="params"\s+type="application/json">\s*(\{.*?\})\s*</script>'
        match = re.search(pattern, html, flags=re.S)
        if not match:
            return html, []
        
        payload = json.loads(match.group(1))
        return html, payload.get("jsonArray", [])
        
    except Exception as e:
        return None, []


def build_url(test_date: date, section: str) -> str:
    """Build the leiturajornal URL."""
    date_str = test_date.strftime("%d-%m-%Y")
    if section == "do1":
        return f"https://www.in.gov.br/leiturajornal?data={date_str}"
    return f"https://www.in.gov.br/leiturajornal?data={date_str}&secao={section}"


def test_date(d: date, section: str, rot) -> dict:
    """Test a single date."""
    url = build_url(d, section)
    html, json_array = fetch(url, rot)
    
    return {
        "date": d.isoformat(),
        "section": section,
        "url": url,
        "document_count": len(json_array),
        "has_content": len(json_array) > 0,
        "sample_titles": [item.get("title", "")[:80] for item in json_array[:2]] if json_array else [],
    }


def find_first_available_date(year: int, section: str, rot, start_month: int = 1) -> dict | None:
    """Find first available date in a year by testing first week of each month."""
    print(f"\n  Finding first available for {section.upper()} in {year}...")
    
    for month in range(start_month, 13):
        for day in range(1, 15):  # Check first two weeks
            try:
                test_date = date(year, month, day)
                if test_date.weekday() >= 5:  # Skip weekends
                    continue
                
                result = test_date(test_date, section, rot)
                time.sleep(0.5)
                
                if result["has_content"]:
                    print(f"    ✓ First content: {test_date.isoformat()} ({result['document_count']} docs)")
                    if result['sample_titles']:
                        print(f"      Sample: {result['sample_titles'][0][:60]}...")
                    return result
                
            except ValueError:
                continue
    
    print(f"    ✗ No content found in {year}")
    return None


def main():
    rot = create_default_rotator()
    
    print("="*70)
    print("FOCUSED BOUNDARY DATE TESTING")
    print("="*70)
    
    results = {}
    
    # Test 1: Find exact DO1 start in 2013
    print("\n" + "="*50)
    print("1. Testing DO1 boundary (expected: early 2013)")
    print("="*50)
    
    # Test Jan 2, 2013 first
    d = date(2013, 1, 2)
    r = test_date(d, "do1", rot)
    time.sleep(0.5)
    print(f"  2013-01-02 DO1: {r['document_count']} docs")
    if r['has_content']:
        print(f"    First DO1 content found on: 2013-01-02")
        # Try to find if there's anything before
        print("    Checking 2012 dates to confirm no earlier content...")
        for test_d in [date(2012, 12, 3), date(2012, 6, 1)]:
            r2 = test_date(test_d, "do1", rot)
            time.sleep(0.5)
            print(f"      {test_d}: {r2['document_count']} docs")
    
    # Test 2: Find exact DO2 start (expected: 2018)
    print("\n" + "="*50)
    print("2. Testing DO2 boundary (expected: 2018)")
    print("="*50)
    
    # Check early 2018
    for test_d in [date(2018, 1, 2), date(2018, 1, 3), date(2018, 1, 4), date(2018, 1, 5)]:
        r = test_date(test_d, "do2", rot)
        time.sleep(0.5)
        print(f"  {test_d} DO2: {r['document_count']} docs")
        if r['has_content']:
            print(f"    → First DO2 content: {test_d}")
            break
    
    # Check late 2017 to confirm no content
    print("  Checking late 2017 to confirm DO2 not available...")
    for test_d in [date(2017, 12, 1), date(2017, 11, 1), date(2017, 9, 1)]:
        r = test_date(test_d, "do2", rot)
        time.sleep(0.5)
        print(f"    {test_d} DO2: {r['document_count']} docs")
    
    # Test 3: Find exact DO3 start (expected: 2018/2019)
    print("\n" + "="*50)
    print("3. Testing DO3 boundary")
    print("="*50)
    
    # Check early 2018
    print("  Checking early 2018...")
    for test_d in [date(2018, 1, 2), date(2018, 3, 1), date(2018, 6, 1)]:
        r = test_date(test_d, "do3", rot)
        time.sleep(0.5)
        print(f"    {test_d} DO3: {r['document_count']} docs")
    
    # Check later 2018 when DO3 appeared in our tests
    print("  Narrowing down DO3 start date...")
    for test_d in [date(2018, 9, 3), date(2018, 8, 1), date(2018, 7, 2)]:
        r = test_date(test_d, "do3", rot)
        time.sleep(0.5)
        print(f"    {test_d} DO3: {r['document_count']} docs")
        if r['has_content']:
            print(f"    → DO3 content found on: {test_d}")
    
    # Check for DO3 in 2017 to confirm not available
    print("  Checking 2017 to confirm DO3 not available...")
    for test_d in [date(2017, 9, 1), date(2017, 12, 1)]:
        r = test_date(test_d, "do3", rot)
        time.sleep(0.5)
        print(f"    {test_d} DO3: {r['document_count']} docs")
    
    # Test 4: Sample document counts by era
    print("\n" + "="*50)
    print("4. Document counts by era (sample dates)")
    print("="*50)
    
    test_dates = [
        # Era 1: Partial (2013-2017)
        (date(2013, 6, 3), "2013-mid"),
        (date(2014, 3, 3), "2014-early"),
        (date(2015, 5, 4), "2015-mid"),
        (date(2016, 8, 1), "2016-mid"),
        (date(2017, 5, 1), "2017-mid"),
        # Era 2: Full (2018+)
        (date(2018, 10, 1), "2018-mid"),
        (date(2019, 3, 4), "2019-early"),
        (date(2020, 6, 1), "2020-mid"),
        (date(2021, 4, 1), "2021-early"),
        (date(2022, 8, 1), "2022-mid"),
        (date(2023, 5, 1), "2023-mid"),
        (date(2024, 9, 2), "2024-mid"),
        (date(2025, 3, 3), "2025-early"),
    ]
    
    for test_d, label in test_dates:
        print(f"\n  {label} ({test_d}):")
        for section in ["do1", "do2", "do3"]:
            r = test_date(test_d, section, rot)
            time.sleep(0.5)
            status = "✓" if r['has_content'] else "✗"
            print(f"    {status} {section.upper()}: {r['document_count']:>4} docs")
    
    print("\n" + "="*70)
    print("BOUNDARY TESTING COMPLETE")
    print("="*70)


if __name__ == "__main__":
    main()
