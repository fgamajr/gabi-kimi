#!/usr/bin/env python3
"""Verify DO2 on Nov 30, 2017 and surrounding dates."""

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
    except Exception as e:
        print(f"    Error: {e}")
    return []


def url(d: date, sec: str) -> str:
    ds = d.strftime("%d-%m-%Y")
    return f"https://www.in.gov.br/leiturajornal?data={ds}" + (f"&secao={sec}" if sec != "do1" else "")


def test(d: date, sec: str, rot) -> int:
    return len(fetch(url(d, sec), rot))


def main():
    rot = create_default_rotator()
    
    print("DO2 Verification: Nov 29 - Dec 1, 2017")
    print("="*60)
    
    for day in [29, 30]:
        d = date(2017, 11, day)
        print(f"\n2017-11-{day} ({d.strftime('%A')}):")
        for sec in ["do1", "do2", "do3"]:
            count = test(d, sec, rot)
            time.sleep(0.5)
            print(f"  {sec.upper()}: {count} docs")
    
    for day in [1, 2, 3, 4, 5]:
        d = date(2017, 12, day)
        print(f"\n2017-12-{day:02d} ({d.strftime('%A')}):")
        for sec in ["do1", "do2", "do3"]:
            count = test(d, sec, rot)
            time.sleep(0.5)
            print(f"  {sec.upper()}: {count} docs")


if __name__ == "__main__":
    main()
