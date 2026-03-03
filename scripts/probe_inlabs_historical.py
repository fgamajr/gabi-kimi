#!/usr/bin/env python3
"""Test specific historical dates to find INLabs availability boundary."""

from __future__ import annotations

import gzip
import json
import os
import time
from datetime import date, timedelta
from urllib.request import Request, HTTPCookieProcessor, build_opener
import http.cookiejar


def load_with_auth(url: str, cookie_jar: http.cookiejar.CookieJar, timeout: int = 30) -> tuple[int, str]:
    """Load URL with existing cookie jar."""
    opener = build_opener(HTTPCookieProcessor(cookie_jar))
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }
    
    req = Request(url=url, headers=headers, method="GET")
    
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw_data = resp.read()
            # Handle gzip
            if raw_data[:2] == b'\x1f\x8b':
                html = gzip.decompress(raw_data).decode("utf-8", errors="ignore")
            else:
                html = raw_data.decode("utf-8", errors="ignore")
            return int(getattr(resp, "status", 200)), html
    except Exception as e:
        return 0, str(e)


def authenticate(username: str, password: str) -> http.cookiejar.CookieJar | None:
    """Authenticate and return cookie jar with session."""
    cookie_jar = http.cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookie_jar))
    
    login_url = "https://inlabs.in.gov.br/logar.php"
    
    # First get login page
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    
    try:
        req = Request(url=login_url, headers=headers, method="GET")
        with opener.open(req, timeout=30) as resp:
            raw = resp.read()
            login_html = gzip.decompress(raw).decode("utf-8", errors="ignore") if raw[:2] == b'\x1f\x8b' else raw.decode("utf-8", errors="ignore")
        
        # Post login
        from urllib.parse import urlencode
        post_data = urlencode({
            "email": username,
            "password": password,
        }).encode("utf-8")
        
        post_req = Request(
            url=login_url,
            data=post_data,
            headers={
                **headers,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": login_url,
            },
            method="POST"
        )
        
        with opener.open(post_req, timeout=30) as resp:
            raw = resp.read()
            response = gzip.decompress(raw).decode("utf-8", errors="ignore") if raw[:2] == b'\x1f\x8b' else raw.decode("utf-8", errors="ignore")
            final_url = resp.geturl()
        
        # Check if authenticated
        if "login" not in final_url.lower() and "senha" not in response.lower():
            print(f"Authenticated successfully as {username}")
            return cookie_jar
        else:
            print("Authentication failed")
            return None
            
    except Exception as e:
        print(f"Authentication error: {e}")
        return None


def check_date(target_date: date, cookie_jar: http.cookiejar.CookieJar) -> dict:
    """Check a specific date."""
    url = f"https://inlabs.in.gov.br/index.php?p={target_date.isoformat()}"
    code, html = load_with_auth(url, cookie_jar)
    
    html_lower = html.lower()
    
    # Check for content indicators
    has_pdf = ".pdf" in html_lower
    has_dou = "diário oficial" in html_lower or "dou" in html_lower or "assinado" in html_lower
    is_empty = "nenhum documento" in html_lower or html.count("<tr>") < 3
    is_login = "senha" in html_lower and "email" in html_lower
    
    # Count PDFs
    pdf_count = html_lower.count(".pdf")
    
    return {
        "date": target_date.isoformat(),
        "url": url,
        "http_code": code,
        "has_pdf": has_pdf,
        "has_dou": has_dou,
        "is_empty": is_empty,
        "is_login": is_login,
        "pdf_count": pdf_count,
        "available": has_pdf and not is_empty and not is_login,
        "html_snippet": html[:1000] if is_login or not has_pdf else None,
    }


def main():
    username = os.environ.get("INLABS_USER")
    password = os.environ.get("INLABS_PWD")
    
    if not username or not password:
        print("Error: Set INLABS_USER and INLABS_PWD")
        return 1
    
    # Authenticate once
    cookie_jar = authenticate(username, password)
    if not cookie_jar:
        return 1
    
    print("\nTesting historical dates...")
    print("="*60)
    
    # Test specific dates going back
    today = date.today()
    test_offsets = [
        0, 1, 7, 14, 21, 30, 45, 60, 75, 90,  # Recent
        105, 120, 135, 150, 165, 180,  # 3-6 months
        210, 240, 270, 300, 330, 365,  # 7-12 months
        400, 450, 500, 550, 600, 700, 800,  # 1-2 years
    ]
    
    results = []
    
    for offset in test_offsets:
        test_date = today - timedelta(days=offset)
        result = check_date(test_date, cookie_jar)
        results.append(result)
        
        marker = "✓" if result["available"] else "✗"
        print(f"{marker} {test_date} (-{offset:3d} days): {result['pdf_count']:2d} PDFs, available={result['available']}")
        
        if not result["available"]:
            print(f"  Reason: empty={result['is_empty']}, login={result['is_login']}, has_pdf={result['has_pdf']}")
        
        time.sleep(0.5)
    
    # Find cutoff
    print("\n" + "="*60)
    print("AVAILABILITY SUMMARY")
    print("="*60)
    
    available = [r for r in results if r["available"]]
    unavailable = [r for r in results if not r["available"]]
    
    if available:
        oldest = min(available, key=lambda r: r["date"])
        print(f"Oldest available date: {oldest['date']} ({oldest['date']})")
        print(f"Total available in sample: {len(available)}/{len(results)}")
    
    if unavailable:
        first_unavailable = unavailable[0]
        print(f"\nFirst unavailable in sample: {first_unavailable['date']}")
    
    # Save results
    with open("reports/inlabs_historical_probe.json", "w") as f:
        json.dump({
            "test_date": today.isoformat(),
            "results": results,
            "summary": {
                "available_count": len(available),
                "unavailable_count": len(unavailable),
                "oldest_available": min(available, key=lambda r: r["date"])["date"] if available else None,
            }
        }, f, indent=2, default=str)
    
    print("\nResults saved to reports/inlabs_historical_probe.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
