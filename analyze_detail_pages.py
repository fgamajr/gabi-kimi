#!/usr/bin/env python3
"""Analyze leiturajornal article detail pages.

This script:
1. Collects urlTitles from leiturajornal listing pages via API
2. Constructs and fetches detail page URLs  
3. Analyzes detail page structure
4. Compares detail page content to listing pages and INLabs XML
5. Documents URL patterns and variations
6. Tests accessibility
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen
from html import unescape
import subprocess


@dataclass
class ArticleListing:
    """Article data from leiturajornal listing."""
    title: str
    url_title: str
    content: str  # Abstract/summary
    hierarchy: list[str]
    pub_date: str
    pub_name: str
    edition_number: str
    number_page: str
    art_type: str
    hierarchy_str: str
    raw: dict[str, Any] = field(repr=False)


@dataclass
class DetailPageAnalysis:
    """Analysis of a detail page."""
    url: str
    url_title: str
    listing_article: ArticleListing | None = None
    status_code: int | None = None
    error: str | None = None
    html_length: int = 0
    has_full_text: bool = False
    has_pdf_link: bool = False
    has_xml_link: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    content_preview: str = ""
    text_content_length: int = 0
    extracted_text: str = ""


def fetch_leiturajornal(date_str: str, section: str = "do1") -> tuple[int, str]:
    """Fetch leiturajornal page for a date."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    formatted_date = dt.strftime("%d-%m-%Y")
    
    url = f"https://www.in.gov.br/leiturajornal?data={formatted_date}&secao={section}"
    
    cmd = [
        "curl", "-s", "-w", "\nHTTP_CODE: %{http_code}\n",
        "-H", "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "-H", "Accept-Language: pt-BR,pt;q=0.9,en;q=0.8",
        "--compressed",
        url
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = result.stdout
        
        lines = output.split("\n")
        http_code_line = None
        for line in reversed(lines):
            if line.startswith("HTTP_CODE:"):
                http_code_line = line
                break
        
        if http_code_line:
            status_code = int(http_code_line.replace("HTTP_CODE:", "").strip())
            content = output.replace(http_code_line, "").rstrip()
            return status_code, content
        else:
            return 0, output
    except Exception as e:
        return 0, str(e)


def parse_leiturajornal_json(html: str) -> list[ArticleListing]:
    """Extract and parse jsonArray from leiturajornal HTML."""
    # Try different script IDs
    patterns = [
        r'<script id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params"[^>]*>(.*?)</script>',
        r'<script id="params"[^>]*>(.*?)</script>',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, html, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                json_array = data.get("jsonArray", [])
                if json_array:
                    break
            except json.JSONDecodeError:
                continue
    else:
        return []
    
    articles = []
    for item in json_array:
        title_parts = item.get("title", "").split("_")
        title = title_parts[0] if title_parts else ""
        
        articles.append(ArticleListing(
            title=title,
            url_title=item.get("urlTitle", ""),
            content=item.get("content", ""),
            hierarchy=item.get("hierarchyList", []),
            pub_date=item.get("pubDate", ""),
            pub_name=item.get("pubName", ""),
            edition_number=str(item.get("editionNumber", "")),
            number_page=str(item.get("numberPage", "")),
            art_type=item.get("artType", ""),
            hierarchy_str=item.get("hierarchyStr", ""),
            raw=item
        ))
    
    return articles


def fetch_detail_page(url_title: str, base_url: str = "https://www.in.gov.br") -> tuple[int | None, str, str | None]:
    """Fetch a detail page and return status, html, error."""
    url = f"{base_url}/web/dou/-/{url_title}"
    
    req = Request(
        url=url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    
    try:
        with urlopen(req, timeout=30) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            code = resp.getcode()
            return code, html, None
    except URLError as e:
        return None, "", str(e)
    except Exception as e:
        return None, "", str(e)


def strip_html(html: str) -> str:
    """Strip HTML tags and return text content."""
    # Remove scripts and styles
    html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', html)
    text = unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def analyze_detail_page(html: str, url: str, url_title: str, 
                        listing_article: ArticleListing | None = None) -> DetailPageAnalysis:
    """Analyze a detail page HTML."""
    analysis = DetailPageAnalysis(
        url=url, 
        url_title=url_title,
        listing_article=listing_article
    )
    analysis.html_length = len(html)
    
    # Check for PDF links
    pdf_patterns = [
        r'href="([^"]*\.pdf[^"]*)"',
        r'href="([^"]*/pdf/[^"]*)"',
        r'href="([^"]*/download[^"]*)"',
        r'href="([^"]*documento[^"]*\.pdf)"',
    ]
    for pattern in pdf_patterns:
        if re.search(pattern, html, re.IGNORECASE):
            analysis.has_pdf_link = True
            break
    
    # Check for XML links
    xml_patterns = [
        r'href="([^"]*\.xml[^"]*)"',
        r'href="([^"]*formato=xml[^"]*)"',
    ]
    for pattern in xml_patterns:
        if re.search(pattern, html, re.IGNORECASE):
            analysis.has_xml_link = True
            break
    
    # Extract metadata from meta tags
    meta_patterns = {
        'title': r'<meta[^>]*property="og:title"[^>]*content="([^"]*)"',
        'description': r'<meta[^>]*property="og:description"[^>]*content="([^"]*)"',
        'canonical': r'<link[^>]*rel="canonical"[^>]*href="([^"]*)"',
        'pub_date': r'<meta[^>]*name="publish-date"[^>]*content="([^"]*)"',
    }
    for key, pattern in meta_patterns.items():
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            analysis.metadata[key] = unescape(match.group(1))
    
    # Extract full text content
    # Look for main content containers
    text = strip_html(html)
    analysis.extracted_text = text
    analysis.text_content_length = len(text)
    analysis.content_preview = text[:500] if text else ""
    
    # Consider it has full text if substantial content found
    # (listing page abstracts are typically short)
    analysis.has_full_text = len(text) > 500
    
    return analysis


def compare_content(listing: ArticleListing, detail: DetailPageAnalysis) -> dict:
    """Compare listing page content to detail page content."""
    listing_content_len = len(listing.content) if listing.content else 0
    detail_content_len = detail.text_content_length
    
    return {
        "listing_content_length": listing_content_len,
        "detail_content_length": detail_content_len,
        "detail_has_more_content": detail_content_len > listing_content_len * 1.5,
        "content_ratio": detail_content_len / listing_content_len if listing_content_len > 0 else 0,
        "listing_preview": listing.content[:200] if listing.content else "",
        "detail_preview": detail.content_preview[:200] if detail.content_preview else "",
    }


def main():
    """Main analysis function."""
    print("=" * 80)
    print("LEITURAJORNAL ARTICLE DETAIL PAGE ANALYSIS")
    print("=" * 80)
    
    # Use recent date for analysis
    test_date = "2025-02-27"
    test_section = "do1"
    
    print(f"\nFetching leiturajornal listing for {test_date}, section {test_section}...")
    status, html = fetch_leiturajornal(test_date, test_section)
    
    if status != 200:
        print(f"ERROR: Failed to fetch listing page (HTTP {status})")
        return 1
    
    print(f"  HTML size: {len(html):,} bytes")
    
    # Parse articles
    articles = parse_leiturajornal_json(html)
    print(f"  Articles found: {len(articles)}")
    
    if not articles:
        print("ERROR: No articles found in listing!")
        return 1
    
    # Sample articles for detail page analysis
    sample_size = min(15, len(articles))
    sample_articles = articles[:sample_size]
    print(f"\nTesting {sample_size} detail pages...")
    
    # Analyze detail pages
    analyses: list[DetailPageAnalysis] = []
    accessible_count = 0
    error_count = 0
    
    for i, article in enumerate(sample_articles, 1):
        print(f"  [{i}/{sample_size}] {article.url_title[:60]}...", end=" ")
        
        status, html, error = fetch_detail_page(article.url_title)
        
        if error:
            print(f"ERROR: {error[:50]}")
            analysis = DetailPageAnalysis(
                url=f"https://www.in.gov.br/web/dou/-/{article.url_title}",
                url_title=article.url_title,
                listing_article=article,
                error=error
            )
            error_count += 1
        else:
            url = f"https://www.in.gov.br/web/dou/-/{article.url_title}"
            analysis = analyze_detail_page(html, url, article.url_title, article)
            analysis.status_code = status
            
            if status == 200:
                accessible_count += 1
                print(f"OK ({analysis.html_length:,} bytes, text: {analysis.text_content_length:,})")
            else:
                print(f"HTTP {status}")
                error_count += 1
        
        analyses.append(analysis)
    
    # Generate report
    print("\n" + "=" * 80)
    print("ANALYSIS RESULTS")
    print("=" * 80)
    
    print(f"\n📊 ACCESSIBILITY TEST:")
    print(f"  Total tested: {len(analyses)}")
    print(f"  Accessible (HTTP 200): {accessible_count}")
    print(f"  Errors: {error_count}")
    print(f"  Success rate: {accessible_count/len(analyses)*100:.1f}%")
    
    print(f"\n📄 CONTENT ANALYSIS:")
    with_full_text = sum(1 for a in analyses if a.has_full_text)
    with_pdf = sum(1 for a in analyses if a.has_pdf_link)
    with_xml = sum(1 for a in analyses if a.has_xml_link)
    
    avg_html_len = sum(a.html_length for a in analyses if a.status_code == 200) / max(accessible_count, 1)
    avg_text_len = sum(a.text_content_length for a in analyses if a.status_code == 200) / max(accessible_count, 1)
    
    print(f"  Pages with full text (>500 chars): {with_full_text}/{accessible_count} ({with_full_text/max(accessible_count,1)*100:.1f}%)")
    print(f"  Pages with PDF links: {with_pdf}/{accessible_count} ({with_pdf/max(accessible_count,1)*100:.1f}%)")
    print(f"  Pages with XML links: {with_xml}/{accessible_count} ({with_xml/max(accessible_count,1)*100:.1f}%)")
    print(f"  Average HTML length: {avg_html_len:,.0f} bytes")
    print(f"  Average text content length: {avg_text_len:,.0f} chars")
    
    # Compare listing vs detail content
    print(f"\n🔍 LISTING vs DETAIL COMPARISON:")
    comparisons = []
    for analysis in analyses:
        if analysis.listing_article and analysis.status_code == 200:
            comp = compare_content(analysis.listing_article, analysis)
            comparisons.append(comp)
    
    if comparisons:
        has_more_content = sum(1 for c in comparisons if c["detail_has_more_content"])
        avg_ratio = sum(c["content_ratio"] for c in comparisons) / len(comparisons)
        
        print(f"  Detail pages with significantly more content: {has_more_content}/{len(comparisons)}")
        print(f"  Average content ratio (detail/listing): {avg_ratio:.2f}x")
        
        if avg_ratio > 2:
            print(f"  ✅ Detail pages contain SUBSTANTIALLY MORE content than listings")
        elif avg_ratio > 1.5:
            print(f"  ✅ Detail pages contain MORE content than listings")
        else:
            print(f"  ⚠️ Detail pages have similar content to listings")
    
    print(f"\n🔗 URL PATTERN ANALYSIS:")
    print(f"  Base URL pattern: https://www.in.gov.br/web/dou/-/<urlTitle>")
    print(f"  Example: https://www.in.gov.br/web/dou/-/portaria-n-1.014-de-25-de-fevereiro-de-2025-618232076")
    
    # Analyze urlTitle patterns
    url_titles = [a.url_title for a in sample_articles]
    print(f"\n  Sample urlTitles:")
    for ut in url_titles[:5]:
        print(f"    - {ut}")
    
    # Pattern analysis
    has_numeric_suffix = sum(1 for ut in url_titles if re.search(r'-\d+$', ut))
    has_date_pattern = sum(1 for ut in url_titles if re.search(r'de-\d+-de', ut))
    print(f"\n  Pattern analysis ({len(url_titles)} samples):")
    print(f"    - Ends with numeric ID: {has_numeric_suffix}")
    print(f"    - Contains date pattern: {has_date_pattern}")
    
    # Sample detail page analysis
    print(f"\n📋 SAMPLE DETAIL PAGE ANALYSIS:")
    for analysis in analyses[:3]:
        if analysis.status_code == 200:
            print(f"\n  URL: {analysis.url}")
            print(f"  HTML length: {analysis.html_length:,} bytes")
            print(f"  Text content: {analysis.text_content_length:,} chars")
            print(f"  Has full text: {analysis.has_full_text}")
            print(f"  Has PDF link: {analysis.has_pdf_link}")
            print(f"  Has XML link: {analysis.has_xml_link}")
            if analysis.metadata:
                print(f"  Metadata:")
                for key, value in list(analysis.metadata.items())[:3]:
                    print(f"    {key}: {value[:80]}...")
            
            # Compare with listing
            if analysis.listing_article:
                listing_len = len(analysis.listing_article.content) if analysis.listing_article.content else 0
                print(f"  Listing content: {listing_len:,} chars")
                print(f"  Detail has more: {analysis.text_content_length > listing_len * 1.5}")
    
    # Error analysis
    errors = [a for a in analyses if a.error]
    if errors:
        print(f"\n❌ ERROR SAMPLES:")
        for analysis in errors[:3]:
            print(f"  {analysis.url_title}: {analysis.error[:80]}")
    
    # Final recommendation
    print("\n" + "=" * 80)
    print("📊 RECOMMENDATION")
    print("=" * 80)
    
    accessible_rate = accessible_count / len(analyses)
    full_text_rate = with_full_text / max(accessible_count, 1)
    
    if accessible_rate > 0.8:
        print("\n  ✅ Detail pages are ACCESSIBLE")
        print(f"     - {accessible_rate*100:.0f}% of URLs return HTTP 200")
        
        if full_text_rate > 0.7:
            print("\n  ✅ Detail pages contain FULL TEXT")
            print(f"     - {full_text_rate*100:.0f}% have substantial content (>500 chars)")
            print("\n  📌 RECOMMENDATION: Detail pages ARE worth scraping")
            print("     Use them for complete document extraction")
        else:
            print("\n  ⚠️ Detail pages have LIMITED CONTENT")
            print(f"     - Only {full_text_rate*100:.0f}% have substantial content")
            print("\n  📌 RECOMMENDATION: Verify extraction strategy")
            print("     Content may be loaded dynamically via JavaScript")
        
        if with_pdf / max(accessible_count, 1) > 0.3:
            print("\n  ✅ PDF links available")
            print("     Alternative source for official/certified text")
    else:
        print("\n  ❌ Detail pages have ACCESSIBILITY ISSUES")
        print(f"     - Only {accessible_rate*100:.0f}% of URLs are accessible")
        print("\n  📌 RECOMMENDATION: Detail pages NOT recommended for scraping")
        print("     Consider using INLabs API or listing page content instead")
    
    # Save detailed report
    report_path = Path("detail_page_analysis_report.json")
    report_data = {
        "summary": {
            "test_date": test_date,
            "test_section": test_section,
            "total_articles_in_listing": len(articles),
            "detail_pages_tested": len(analyses),
            "accessible": accessible_count,
            "errors": error_count,
            "with_full_text": with_full_text,
            "with_pdf_links": with_pdf,
            "with_xml_links": with_xml,
            "avg_html_length": avg_html_len,
            "avg_text_length": avg_text_len,
        },
        "url_pattern": {
            "base": "https://www.in.gov.br/web/dou/-/{urlTitle}",
            "example": "https://www.in.gov.br/web/dou/-/portaria-n-1.014-de-25-de-fevereiro-de-2025-618232076"
        },
        "articles": [
            {
                "title": a.title,
                "url_title": a.url_title,
                "content_preview": a.content[:200] if a.content else "",
                "pub_date": a.pub_date,
                "art_type": a.art_type,
                "page": a.number_page,
            }
            for a in sample_articles[:10]
        ],
        "detail_analyses": [
            {
                "url": a.url,
                "url_title": a.url_title,
                "status": a.status_code,
                "error": a.error,
                "html_length": a.html_length,
                "has_full_text": a.has_full_text,
                "has_pdf_link": a.has_pdf_link,
                "has_xml_link": a.has_xml_link,
                "text_length": a.text_content_length,
                "metadata": a.metadata,
                "listing_content_length": len(a.listing_article.content) if a.listing_article and a.listing_article.content else 0,
            }
            for a in analyses
        ],
        "recommendation": {
            "worth_scraping": accessible_rate > 0.8 and full_text_rate > 0.5,
            "accessible_rate": accessible_rate,
            "full_text_rate": full_text_rate,
        }
    }
    
    report_path.write_text(json.dumps(report_data, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"\n💾 Detailed report saved to: {report_path}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
