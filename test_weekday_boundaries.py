#!/usr/bin/env python3
"""Test specific weekdays to find exact boundaries."""

from __future__ import annotations

import json
import re
import time
from datetime import date, timedelta
from urllib.request import Request, urlopen

from crawler.user_agent_rotator import create_default_rotator


def fetch(url: str, rot) -> list[dict]:
    """Fetch URL and extract jsonArray."""
    try:
        req = Request(
            url=url,
            headers={
                "User-Agent": rot.next(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            method="GET",
        )
        with urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        
        pattern = r'<script\s+id="params"\s+type="application/json">\s*(\{.*?\})\s*</script>'
        match = re.search(pattern, html, flags=re.S)
        if match:
            payload = json.loads(match.group(1))
            return payload.get("jsonArray", [])
    except Exception:
        pass
    return []


def build_url(d: date, section: str) -> str:
    date_str = d.strftime("%d-%m-%Y")
    if section == "do1":
        return f"https://www.in.gov.br/leiturajornal?data={date_str}"
    return f"https://www.in.gov.br/leiturajornal?data={date_str}&secao={section}"


def test(d: date, section: str, rot) -> int:
    return len(fetch(build_url(d, section), rot))


def find_first_tuesday_of_month(year: int, month: int) -> date | None:
    """Find first Tuesday of month."""
    for day in range(1, 8):
        try:
            d = date(year, month, day)
            if d.weekday() == 1:  # Tuesday
                return d
        except ValueError:
            continue
    return None


def main():
    rot = create_default_rotator()
    
    print("="*70)
    print("WEEKDAY BOUNDARY TESTING (Tuesdays to avoid weekends)")
    print("="*70)
    
    # Find exact DO3 start date
    print("\n1. Finding exact DO3 start date in 2018...")
    print("-" * 50)
    
    for month in range(1, 13):
        d = find_first_tuesday_of_month(2018, month)
        if d:
            count = test(d, "do3", rot)
            time.sleep(0.5)
            status = "✓" if count > 0 else "✗"
            print(f"  {status} 2018-{month:02d}: {d} - {count} docs")
    
    # Check late 2017 for DO3
    print("\n  Checking DO3 in late 2017...")
    for month in [7, 8, 9, 10, 11, 12]:
        d = find_first_tuesday_of_month(2017, month)
        if d:
            count = test(d, "do3", rot)
            time.sleep(0.5)
            print(f"    2017-{month:02d}: {d} - {count} docs")
    
    # Check early 2018 for DO3 (month by month)
    print("\n  Narrowing down DO3 start in early 2018...")
    for month in [1, 2, 3]:
        for day in range(1, 15):
            try:
                d = date(2018, month, day)
                if d.weekday() >= 5:  # Skip weekends
                    continue
                count = test(d, "do3", rot)
                time.sleep(0.3)
                if count > 0:
                    print(f"    → First DO3 content: {d} ({count} docs)")
                    break
            except ValueError:
                continue
        else:
            continue
        break
    
    # Comprehensive year-by-year Tuesday testing
    print("\n2. Comprehensive Tuesday testing by year")
    print("-" * 50)
    
    results = {}
    for year in range(2013, 2026):
        print(f"\n  {year}:")
        year_data = {}
        
        for month in [1, 4, 7, 10]:  # Q1, Q2, Q3, Q4
            d = find_first_tuesday_of_month(year, month)
            if d:
                row = {}
                for section in ["do1", "do2", "do3"]:
                    count = test(d, section, rot)
                    time.sleep(0.3)
                    row[section] = count
                
                do1_s = "✓" if row["do1"] > 0 else "✗"
                do2_s = "✓" if row["do2"] > 0 else "✗"
                do3_s = "✓" if row["do3"] > 0 else "✗"
                
                print(f"    {d}: DO1{do1_s}({row['do1']:>4}) DO2{do2_s}({row['do2']:>4}) DO3{do3_s}({row['do3']:>4})")
                year_data[month] = row
        
        results[year] = year_data
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY: First appearance by section")
    print("="*70)
    
    first_dates = {
        "do1": None,
        "do2": None,
        "do3": None,
    }
    
    for year in range(2013, 2026):
        year_data = results.get(year, {})
        for month in [1, 4, 7, 10]:
            if month in year_data:
                for section in ["do1", "do2", "do3"]:
                    if first_dates[section] is None and year_data[month][section] > 0:
                        d = find_first_tuesday_of_month(year, month)
                        first_dates[section] = (year, month, d, year_data[month][section])
    
    for section, info in first_dates.items():
        if info:
            year, month, d, count = info
            print(f"  {section.upper()}: First content in {year}-{month:02d} ({d}) - {count} docs")
        else:
            print(f"  {section.upper()}: No content found")
    
    print("\n" + "="*70)


if __name__ == "__main__":
    main()
