#!/usr/bin/env python3
"""Explore leiturajornal HTML/JSON data source for DOU."""

from __future__ import annotations

import json
import subprocess
import re
from dataclasses import dataclass
from datetime import datetime


@dataclass
class DateResult:
    date: str
    url: str
    status_code: int
    has_json_array: bool
    article_count: int
    error_message: str | None
    raw_json_size: int


def fetch_with_curl(url: str) -> tuple[int, str]:
    """Fetch page using curl with proper headers."""
    cmd = [
        "curl", "-s", "-w", "\nHTTP_CODE: %{http_code}\n",
        "-H", "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "-H", "Accept-Language: en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7",
        "--compressed",
        url
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = result.stdout
        
        # Extract HTTP code from last line
        lines = output.split("\n")
        http_code_line = None
        for line in reversed(lines):
            if line.startswith("HTTP_CODE:"):
                http_code_line = line
                break
        
        if http_code_line:
            status_code = int(http_code_line.replace("HTTP_CODE:", "").strip())
            # Remove the HTTP_CODE line from content
            content = output.replace(http_code_line, "").rstrip()
            return status_code, content
        else:
            return 0, output
    except Exception as e:
        return 0, str(e)


def extract_json_array(html: str) -> tuple[bool, int, str | None]:
    """Extract and parse jsonArray from HTML."""
    pattern = r'<script id="params" type="application/json">(.*?)</script>'
    match = re.search(pattern, html, re.DOTALL)
    
    if not match:
        return False, 0, "No <script id='params'> tag found"
    
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        return False, 0, f"JSON parse error: {e}"
    
    # Check for jsonArray
    json_array = data.get("jsonArray", [])
    if json_array is None:
        return False, 0, "jsonArray is null"
    
    if not isinstance(json_array, list):
        return False, 0, f"jsonArray is not a list: {type(json_array)}"
    
    return True, len(json_array), None


def check_date(date_str: str) -> DateResult:
    """Check a single date."""
    # Convert YYYY-MM-DD to DD-MM-YYYY
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    formatted_date = dt.strftime("%d-%m-%Y")
    
    url = f"https://www.in.gov.br/leiturajornal?data={formatted_date}&secao=do1"
    
    print(f"\n{'='*60}")
    print(f"Date: {date_str} ({formatted_date})")
    print(f"URL: {url}")
    print(f"{'='*60}")
    
    status, html = fetch_with_curl(url)
    print(f"HTTP Status: {status}")
    print(f"HTML Size: {len(html)} bytes")
    
    if status != 200:
        return DateResult(
            date=date_str,
            url=url,
            status_code=status,
            has_json_array=False,
            article_count=0,
            error_message=f"HTTP {status}",
            raw_json_size=0
        )
    
    has_array, count, error = extract_json_array(html)
    
    # Try to extract raw JSON size
    raw_size = 0
    pattern = r'<script id="params" type="application/json">(.*?)</script>'
    match = re.search(pattern, html, re.DOTALL)
    if match:
        raw_size = len(match.group(1))
    
    print(f"Has jsonArray: {has_array}")
    print(f"Article count: {count}")
    if error:
        print(f"Error: {error}")
    print(f"Raw JSON size: {raw_size} bytes")
    
    # Look for specific error messages in the page
    if "Não foram encontrados" in html:
        print("Note: Page contains 'Não foram encontrados' (Not found)")
    if "não existe" in html.lower():
        print("Note: Page contains 'não existe' (does not exist)")
    
    return DateResult(
        date=date_str,
        url=url,
        status_code=status,
        has_json_array=has_array,
        article_count=count,
        error_message=error,
        raw_json_size=raw_size
    )


def main():
    """Run exploration."""
    dates = [
        # First days
        "2016-01-01", "2016-01-02", "2016-01-03",
        # Mid-year check
        "2016-06-01", "2016-07-01",
        # Year end
        "2016-12-29", "2016-12-30", "2016-12-31"
    ]
    
    results = []
    for date in dates:
        result = check_date(date)
        results.append(result)
    
    # Summary report
    print("\n" + "="*60)
    print("SUMMARY REPORT")
    print("="*60)
    
    for r in results:
        status = "✓ CONTENT" if r.article_count > 0 else "✗ EMPTY"
        print(f"{r.date}: {status} - {r.article_count} articles (HTTP {r.status_code})")
    
    print("\n--- Detailed Results ---")
    for r in results:
        print(f"\n{r.date}:")
        print(f"  URL: {r.url}")
        print(f"  HTTP Status: {r.status_code}")
        print(f"  Has jsonArray: {r.has_json_array}")
        print(f"  Article count: {r.article_count}")
        if r.error_message:
            print(f"  Error: {r.error_message}")
        print(f"  Raw JSON size: {r.raw_json_size} bytes")


if __name__ == "__main__":
    main()
