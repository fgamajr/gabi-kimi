#!/usr/bin/env python3
"""Final focused boundary test for key dates only."""

from __future__ import annotations

import json
import re
import time
from datetime import date
from urllib.request import Request, urlopen

from crawler.user_agent_rotator import create_default_rotator


def fetch(url: str, rot) -> list[dict]:
    try:
        req = Request(
            url=url,
            headers={"User-Agent": rot.next(), "Accept": "text/html,*/*;q=0.8"},
            method="GET",
        )
        with urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        pattern = r'<script\s+id="params"\s+type="application/json">\s*(\{.*?\})\s*</script>'
        match = re.search(pattern, html, flags=re.S)
        if match:
            return json.loads(match.group(1)).get("jsonArray", [])
    except Exception:
        pass
    return []


def url(d: date, sec: str) -> str:
    ds = d.strftime("%d-%m-%Y")
    return f"https://www.in.gov.br/leiturajornal?data={ds}" + (f"&secao={sec}" if sec != "do1" else "")


def test(d: date, sec: str, rot) -> int:
    return len(fetch(url(d, sec), rot))


def main():
    rot = create_default_rotator()
    
    print("="*70)
    print("FINAL BOUNDARY TEST - KEY DATES ONLY")
    print("="*70)
    
    # Key dates to test (Tuesdays/Weekdays only)
    key_dates = [
        # DO1 boundary (expected 2013)
        (date(2012, 6, 5), "2012-mid", "Pre-boundary"),
        (date(2012, 12, 4), "2012-end", "Pre-boundary"),
        (date(2013, 1, 2), "2013-start", "DO1 start candidate"),
        (date(2013, 6, 4), "2013-mid", "DO1 confirmed"),
        
        # DO2 boundary (expected 2018)
        (date(2017, 6, 6), "2017-mid", "Pre-DO2"),
        (date(2017, 12, 5), "2017-end", "Pre-DO2"),
        (date(2018, 1, 2), "2018-start", "DO2 start candidate"),
        (date(2018, 6, 5), "2018-mid", "All sections"),
        
        # DO3 boundary (expected 2018)
        (date(2018, 1, 2), "2018-start", "DO3 check"),
        (date(2018, 3, 6), "2018-q1", "DO3 check"),
        
        # Later verification
        (date(2019, 1, 8), "2019-start", "Full era"),
        (date(2020, 7, 7), "2020-mid", "Full era"),
        (date(2022, 6, 7), "2022-mid", "Full era"),
        (date(2024, 9, 3), "2024-mid", "Full era"),
        (date(2025, 1, 7), "2025-start", "Full era"),
    ]
    
    print("\nTesting key boundary dates:")
    print("-" * 70)
    print(f"{'Date':<12} {'Label':<15} {'DO1':>8} {'DO2':>8} {'DO3':>8} {'Notes'}")
    print("-" * 70)
    
    for d, label, note in key_dates:
        do1 = test(d, "do1", rot)
        time.sleep(0.3)
        do2 = test(d, "do2", rot)
        time.sleep(0.3)
        do3 = test(d, "do3", rot)
        time.sleep(0.3)
        
        print(f"{d.isoformat():<12} {label:<15} {do1:>8} {do2:>8} {do3:>8}  {note}")
    
    # Additional: Check consecutive early 2013 dates for DO1
    print("\n" + "="*70)
    print("DO1 START DATE VERIFICATION (early 2013)")
    print("="*70)
    
    test_2013_dates = [
        date(2013, 1, 2),
        date(2013, 1, 3),
        date(2013, 1, 4),
        date(2013, 1, 7),
        date(2013, 1, 8),
        date(2013, 1, 9),
    ]
    
    for d in test_2013_dates:
        count = test(d, "do1", rot)
        time.sleep(0.3)
        dow = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d.weekday()]
        print(f"  {d} ({dow}): {count} docs")
    
    # Check DO2 in late 2017
    print("\n" + "="*70)
    print("DO2 START DATE VERIFICATION (late 2017/early 2018)")
    print("="*70)
    
    test_do2_dates = [
        (date(2017, 11, 7), "Nov 2017"),
        (date(2017, 12, 1), "Dec 2017"),
        (date(2017, 12, 5), "Dec 2017"),
        (date(2018, 1, 2), "Jan 2018"),
        (date(2018, 1, 3), "Jan 2018"),
    ]
    
    for d, label in test_do2_dates:
        count = test(d, "do2", rot)
        time.sleep(0.3)
        print(f"  {d} ({label}): {count} docs")
    
    print("\n" + "="*70)


if __name__ == "__main__":
    main()
