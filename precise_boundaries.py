#!/usr/bin/env python3
"""Precise boundary testing for DO1 and DO2 start dates."""

from __future__ import annotations

import json
import re
import time
from datetime import date, timedelta
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
    print("PRECISE BOUNDARY DETERMINATION")
    print("="*70)
    
    # 1. DO1 exact start - check if Jan 1, 2013 has content
    print("\n1. DO1 BOUNDARY - Early January 2013")
    print("-" * 50)
    
    # Jan 1, 2013 was a Tuesday
    for day in range(1, 10):
        try:
            d = date(2013, 1, day)
            count = test(d, "do1", rot)
            time.sleep(0.3)
            dow = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d.weekday()]
            marker = " <-- FIRST" if count > 0 else ""
            print(f"  2013-01-{day:02d} ({dow}): {count:>3} docs{marker}")
        except ValueError:
            break
    
    # Check late 2012 to confirm no DO1
    print("\n  Confirming no DO1 in late 2012...")
    for d in [date(2012, 12, 3), date(2012, 12, 10), date(2012, 12, 17), date(2012, 12, 26)]:
        count = test(d, "do1", rot)
        time.sleep(0.3)
        dow = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d.weekday()]
        print(f"    {d} ({dow}): {count} docs")
    
    # 2. DO2 exact start - narrow down from Nov to Dec 2017
    print("\n2. DO2 BOUNDARY - November/December 2017")
    print("-" * 50)
    
    # Check all Tuesdays in Nov and Dec 2017
    print("  Checking Tuesdays in Nov-Dec 2017:")
    
    # Nov 2017 - first Tuesday is Nov 7
    for week in range(0, 5):
        d = date(2017, 11, 7) + timedelta(days=7*week)
        if d.month > 11:
            break
        count = test(d, "do2", rot)
        time.sleep(0.3)
        print(f"    {d}: {count:>4} docs")
    
    # Dec 2017
    for week in range(0, 5):
        d = date(2017, 12, 5) + timedelta(days=7*(week-2))  # Dec 5 is first Tuesday
        if d.month != 12:
            continue
        count = test(d, "do2", rot)
        time.sleep(0.3)
        marker = " <-- FIRST" if count > 0 else ""
        print(f"    {d}: {count:>4} docs{marker}")
    
    # Narrow down to specific dates in late Nov 2017
    print("\n  Narrowing down DO2 start in late November...")
    for day in range(20, 31):
        try:
            d = date(2017, 11, day)
            if d.weekday() >= 5:  # Skip weekends
                continue
            count = test(d, "do2", rot)
            time.sleep(0.3)
            dow = ["Mon", "Tue", "Wed", "Thu", "Fri"][d.weekday()]
            marker = " <--" if count > 0 else ""
            print(f"    2017-11-{day:02d} ({dow}): {count:>4} docs{marker}")
        except ValueError:
            break
    
    # 3. DO3 exact start in 2018
    print("\n3. DO3 BOUNDARY - Early 2018")
    print("-" * 50)
    
    print("  Checking January 2018:")
    for day in range(1, 15):
        try:
            d = date(2018, 1, day)
            if d.weekday() >= 5:
                continue
            count = test(d, "do3", rot)
            time.sleep(0.3)
            dow = ["Mon", "Tue", "Wed", "Thu", "Fri"][d.weekday()]
            marker = " <-- FIRST" if count > 0 else ""
            print(f"    2018-01-{day:02d} ({dow}): {count:>4} docs{marker}")
        except ValueError:
            break
    
    print("\n  Checking February 2018:")
    for day in range(1, 15):
        try:
            d = date(2018, 2, day)
            if d.weekday() >= 5:
                continue
            count = test(d, "do3", rot)
            time.sleep(0.3)
            dow = ["Mon", "Tue", "Wed", "Thu", "Fri"][d.weekday()]
            marker = " <-- FIRST" if count > 0 else ""
            print(f"    2018-02-{day:02d} ({dow}): {count:>4} docs{marker}")
            if count > 0:
                break
        except ValueError:
            break
    
    print("\n  Checking March 2018:")
    for day in range(1, 10):
        try:
            d = date(2018, 3, day)
            if d.weekday() >= 5:
                continue
            count = test(d, "do3", rot)
            time.sleep(0.3)
            dow = ["Mon", "Tue", "Wed", "Thu", "Fri"][d.weekday()]
            print(f"    2018-03-{day:02d} ({dow}): {count:>4} docs")
        except ValueError:
            break
    
    print("\n" + "="*70)


if __name__ == "__main__":
    main()
