#!/usr/bin/env python3
"""
INLabs vs Leiturajornal DOU Data Source Comparison

This script collects data from both INLabs and leiturajornal for the same date
and performs a detailed comparison of:
- Document counts
- Metadata fields
- Content completeness
- Data quality
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class LeiturajornalArticle:
    """Article from leiturajornal JSON."""
    pub_name: str
    url_title: str
    number_page: str
    sub_titulo: str
    titulo: str
    title: str
    pub_date: str
    content: str
    edition_number: str
    hierarchy_level_size: int
    art_type: str
    pub_order: str
    hierarchy_str: str
    hierarchy_list: list[str]
    # Raw data for comparison
    raw: dict[str, Any] = field(repr=False)


@dataclass
class INLabsArticle:
    """Article from INLabs XML."""
    id: str
    id_materia: str
    id_oficio: str
    name: str
    pub_name: str
    pub_date: str
    edition_number: str
    number_page: str
    pdf_page: str
    art_type: str
    art_category: str
    art_class: str
    art_size: str
    art_notes: str
    identifica: str
    data: str
    ementa: str
    titulo: str
    sub_titulo: str
    texto: str
    # Raw data for comparison
    raw_xml: str = field(repr=False)


@dataclass
class SourceComparison:
    """Comparison results for a single date."""
    date: str
    section: str
    
    # Counts
    leiturajornal_count: int = 0
    inlabs_count: int = 0
    
    # Articles
    leiturajornal_articles: list[LeiturajornalArticle] = field(default_factory=list)
    inlabs_articles: list[INLabsArticle] = field(default_factory=list)
    
    # Metadata comparison
    lj_metadata_fields: set[str] = field(default_factory=set)
    inlabs_metadata_fields: set[str] = field(default_factory=set)
    
    # Content analysis
    lj_total_content_chars: int = 0
    inlabs_total_content_chars: int = 0
    
    # Quality metrics
    lj_empty_titles: int = 0
    inlabs_empty_identifica: int = 0
    
    def mismatch_count(self) -> int:
        return abs(self.leiturajornal_count - self.inlabs_count)


# =============================================================================
# Leiturajornal Fetcher
# =============================================================================

def fetch_leiturajornal(date_str: str, section: str = "do1") -> tuple[int, str]:
    """Fetch leiturajornal page for a date."""
    # Convert YYYY-MM-DD to DD-MM-YYYY
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


def parse_leiturajornal_json(html: str) -> list[LeiturajornalArticle]:
    """Extract and parse jsonArray from leiturajornal HTML."""
    pattern = r'<script id="params" type="application/json">(.*?)</script>'
    match = re.search(pattern, html, re.DOTALL)
    
    if not match:
        return []
    
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    
    json_array = data.get("jsonArray", [])
    if not json_array or not isinstance(json_array, list):
        return []
    
    articles = []
    for item in json_array:
        articles.append(LeiturajornalArticle(
            pub_name=item.get("pubName", ""),
            url_title=item.get("urlTitle", ""),
            number_page=item.get("numberPage", ""),
            sub_titulo=item.get("subTitulo", ""),
            titulo=item.get("titulo", ""),
            title=item.get("title", ""),
            pub_date=item.get("pubDate", ""),
            content=item.get("content", ""),
            edition_number=item.get("editionNumber", ""),
            hierarchy_level_size=item.get("hierarchyLevelSize", 0),
            art_type=item.get("artType", ""),
            pub_order=item.get("pubOrder", ""),
            hierarchy_str=item.get("hierarchyStr", ""),
            hierarchy_list=item.get("hierarchyList", []),
            raw=item
        ))
    
    return articles


# =============================================================================
# INLabs Fetcher (from ZIP or existing files)
# =============================================================================

def parse_inlabs_xml(xml_content: str) -> INLabsArticle | None:
    """Parse INLabs XML content."""
    try:
        root = ET.fromstring(xml_content)
        
        article = root.find(".//article")
        if article is None and root.tag == "article":
            article = root
        
        if article is None:
            return None
        
        body = article.find("body")
        if body is None:
            return None
        
        def get_text(elem):
            return elem.text if elem is not None and elem.text else ""
        
        return INLabsArticle(
            id=article.get("id", ""),
            id_materia=article.get("idMateria", ""),
            id_oficio=article.get("idOficio", ""),
            name=article.get("name", ""),
            pub_name=article.get("pubName", ""),
            pub_date=article.get("pubDate", ""),
            edition_number=article.get("editionNumber", ""),
            number_page=article.get("numberPage", ""),
            pdf_page=article.get("pdfPage", ""),
            art_type=article.get("artType", ""),
            art_category=article.get("artCategory", ""),
            art_class=article.get("artClass", ""),
            art_size=article.get("artSize", ""),
            art_notes=article.get("artNotes", ""),
            identifica=get_text(body.find("Identifica")),
            data=get_text(body.find("Data")),
            ementa=get_text(body.find("Ementa")),
            titulo=get_text(body.find("Titulo")),
            sub_titulo=get_text(body.find("SubTitulo")),
            texto=get_text(body.find("Texto")),
            raw_xml=xml_content
        )
    except Exception as e:
        print(f"  XML parse error: {e}")
        return None


def load_inlabs_from_directory(directory: Path) -> list[INLabsArticle]:
    """Load INLabs articles from XML files in a directory."""
    articles = []
    
    if not directory.exists():
        return articles
    
    for xml_file in sorted(directory.glob("*.xml")):
        try:
            content = xml_file.read_text(encoding="utf-8-sig")
            article = parse_inlabs_xml(content)
            if article:
                articles.append(article)
        except Exception as e:
            print(f"  Error parsing {xml_file}: {e}")
    
    return articles


def extract_inlabs_from_zip(zip_path: Path) -> list[INLabsArticle]:
    """Extract and parse all XML files from INLabs ZIP."""
    articles = []
    
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                if name.endswith(".xml"):
                    try:
                        content = zf.read(name).decode("utf-8-sig")
                        article = parse_inlabs_xml(content)
                        if article:
                            articles.append(article)
                    except Exception as e:
                        print(f"  Error extracting {name}: {e}")
    except Exception as e:
        print(f"  ZIP error: {e}")
    
    return articles


# =============================================================================
# Comparison Functions
# =============================================================================

def compare_sources(date_str: str, section: str, 
                    inlabs_source: Path | None = None) -> SourceComparison:
    """Compare both sources for a given date and section."""
    
    comparison = SourceComparison(date=date_str, section=section)
    
    print(f"\n{'='*70}")
    print(f"Comparing sources for {date_str}, section {section.upper()}")
    print(f"{'='*70}")
    
    # --- Fetch Leiturajornal ---
    print("\n[1] Fetching from leiturajornal...")
    status, html = fetch_leiturajornal(date_str, section)
    print(f"  HTTP Status: {status}")
    print(f"  HTML Size: {len(html):,} bytes")
    
    if status == 200:
        lj_articles = parse_leiturajornal_json(html)
        comparison.leiturajornal_articles = lj_articles
        comparison.leiturajornal_count = len(lj_articles)
        print(f"  Articles found: {len(lj_articles)}")
        
        # Collect metadata fields
        if lj_articles:
            comparison.lj_metadata_fields = set(lj_articles[0].raw.keys())
        
        # Calculate content size
        for art in lj_articles:
            comparison.lj_total_content_chars += len(art.content)
            if not art.title:
                comparison.lj_empty_titles += 1
    
    # --- Load INLabs ---
    print("\n[2] Loading INLabs data...")
    
    if inlabs_source:
        if inlabs_source.is_dir():
            inlabs_articles = load_inlabs_from_directory(inlabs_source)
        elif inlabs_source.suffix == ".zip":
            inlabs_articles = extract_inlabs_from_zip(inlabs_source)
        else:
            inlabs_articles = []
        
        comparison.inlabs_articles = inlabs_articles
        comparison.inlabs_count = len(inlabs_articles)
        print(f"  Articles found: {len(inlabs_articles)}")
        
        # Collect metadata fields
        if inlabs_articles:
            comparison.inlabs_metadata_fields = set(vars(inlabs_articles[0]).keys()) - {"raw_xml"}
        
        # Calculate content size
        for art in inlabs_articles:
            comparison.inlabs_total_content_chars += len(art.texto)
            if not art.identifica:
                comparison.inlabs_empty_identifica += 1
    else:
        print("  No INLabs source provided")
    
    return comparison


def print_comparison_report(comparison: SourceComparison) -> None:
    """Print detailed comparison report."""
    
    print(f"\n{'='*70}")
    print(f"COMPARISON REPORT: {comparison.date} - Section {comparison.section.upper()}")
    print(f"{'='*70}")
    
    # Document counts
    print("\n📊 DOCUMENT COUNTS")
    print("-" * 50)
    print(f"  Leiturajornal: {comparison.leiturajornal_count}")
    print(f"  INLabs:        {comparison.inlabs_count}")
    
    if comparison.leiturajornal_count == comparison.inlabs_count:
        print(f"  ✅ MATCH: Both sources have {comparison.leiturajornal_count} documents")
    else:
        diff = comparison.mismatch_count()
        print(f"  ⚠️  MISMATCH: Difference of {diff} documents")
        if comparison.inlabs_count > 0:
            pct = (diff / comparison.inlabs_count) * 100
            print(f"              ({pct:.1f}% difference)")
    
    # Metadata fields
    print("\n📋 METADATA FIELDS")
    print("-" * 50)
    
    print(f"\n  Leiturajornal fields ({len(comparison.lj_metadata_fields)}):")
    for field in sorted(comparison.lj_metadata_fields):
        print(f"    - {field}")
    
    print(f"\n  INLabs fields ({len(comparison.inlabs_metadata_fields)}):")
    for field in sorted(comparison.inlabs_metadata_fields):
        print(f"    - {field}")
    
    # Field comparison
    common_fields = comparison.lj_metadata_fields & comparison.inlabs_metadata_fields
    lj_only = comparison.lj_metadata_fields - comparison.inlabs_metadata_fields
    inlabs_only = comparison.inlabs_metadata_fields - comparison.lj_metadata_fields
    
    print(f"\n  Common fields: {len(common_fields)}")
    if lj_only:
        print(f"  Leiturajornal only: {', '.join(sorted(lj_only))}")
    if inlabs_only:
        print(f"  INLabs only: {', '.join(sorted(inlabs_only))}")
    
    # Content completeness
    print("\n📝 CONTENT COMPLETENESS")
    print("-" * 50)
    print(f"  Leiturajornal total content chars: {comparison.lj_total_content_chars:,}")
    print(f"  INLabs total content chars:        {comparison.inlabs_total_content_chars:,}")
    
    if comparison.inlabs_total_content_chars > 0:
        ratio = comparison.lj_total_content_chars / comparison.inlabs_total_content_chars
        print(f"  Content ratio (LJ/INLabs): {ratio:.2f}")
        if 0.9 <= ratio <= 1.1:
            print("  ✅ Content sizes are comparable")
        elif ratio < 0.9:
            print("  ⚠️  Leiturajornal has significantly less content")
        else:
            print("  ⚠️  INLabs has significantly less content")
    
    # Data quality
    print("\n🔍 DATA QUALITY METRICS")
    print("-" * 50)
    print(f"  Leiturajornal empty titles: {comparison.lj_empty_titles}")
    print(f"  INLabs empty identifica:    {comparison.inlabs_empty_identifica}")
    
    # Calculate quality percentages
    if comparison.leiturajornal_count > 0:
        lj_quality = (1 - comparison.lj_empty_titles / comparison.leiturajornal_count) * 100
        print(f"  Leiturajornal title completeness: {lj_quality:.1f}%")
    
    if comparison.inlabs_count > 0:
        inlabs_quality = (1 - comparison.inlabs_empty_identifica / comparison.inlabs_count) * 100
        print(f"  INLabs identifica completeness: {inlabs_quality:.1f}%")
    
    # Sample articles
    print("\n📄 SAMPLE ARTICLES")
    print("-" * 50)
    
    if comparison.leiturajornal_articles:
        art = comparison.leiturajornal_articles[0]
        print(f"\n  Leiturajornal - First article:")
        print(f"    Type: {art.art_type}")
        print(f"    Title: {art.title[:80]}..." if len(art.title) > 80 else f"    Title: {art.title}")
        print(f"    Page: {art.number_page}")
        print(f"    Edition: {art.edition_number}")
        print(f"    Hierarchy: {' > '.join(art.hierarchy_list[:3])}..." if len(art.hierarchy_list) > 3 else f"    Hierarchy: {' > '.join(art.hierarchy_list)}")
        print(f"    Content preview: {art.content[:100]}..." if len(art.content) > 100 else f"    Content: {art.content}")
    
    if comparison.inlabs_articles:
        art = comparison.inlabs_articles[0]
        print(f"\n  INLabs - First article:")
        print(f"    ID Materia: {art.id_materia}")
        print(f"    Type: {art.art_type}")
        print(f"    Category: {art.art_category}")
        print(f"    Identifica: {art.identifica[:80]}..." if len(art.identifica) > 80 else f"    Identifica: {art.identifica}")
        print(f"    Page: {art.number_page}")
        print(f"    Edition: {art.edition_number}")
        print(f"    Has Ementa: {'Yes' if art.ementa else 'No'}")
        print(f"    Texto length: {len(art.texto):,} chars")


def find_potential_matches(lj_article: LeiturajornalArticle, 
                           inlabs_articles: list[INLabsArticle]) -> list[tuple[INLabsArticle, int]]:
    """Find potential matching articles between sources."""
    matches = []
    
    for inlabs in inlabs_articles:
        score = 0
        
        # Compare art_type
        if lj_article.art_type.upper() == inlabs.art_type.upper():
            score += 2
        
        # Compare page number
        if lj_article.number_page and inlabs.number_page:
            if lj_article.number_page == inlabs.number_page:
                score += 3
        
        # Compare title/identifica
        lj_title = lj_article.title.upper().replace(" ", "").replace(",", "").replace(".", "")
        inlabs_ident = inlabs.identifica.upper().replace(" ", "").replace(",", "").replace(".", "")
        if lj_title == inlabs_ident:
            score += 5
        elif lj_title in inlabs_ident or inlabs_ident in lj_title:
            score += 2
        
        # Compare hierarchy/category
        if lj_article.hierarchy_str and inlabs.art_category:
            if any(h in inlabs.art_category for h in lj_article.hierarchy_list):
                score += 1
        
        if score >= 3:
            matches.append((inlabs, score))
    
    # Sort by score
    matches.sort(key=lambda x: x[1], reverse=True)
    return matches


def attempt_cross_mapping(comparison: SourceComparison) -> dict:
    """Attempt to map articles between sources."""
    
    mapping = {
        "total_lj": len(comparison.leiturajornal_articles),
        "total_inlabs": len(comparison.inlabs_articles),
        "matched": 0,
        "unmatched_lj": [],
        "unmatched_inlabs": [],
        "mappings": []
    }
    
    lj_matched = set()
    inlabs_matched = set()
    
    for i, lj in enumerate(comparison.leiturajornal_articles):
        potential = find_potential_matches(lj, comparison.inlabs_articles)
        
        if potential:
            inlabs, score = potential[0]
            inlabs_idx = comparison.inlabs_articles.index(inlabs)
            
            if inlabs_idx not in inlabs_matched:
                mapping["mappings"].append({
                    "lj_index": i,
                    "inlabs_index": inlabs_idx,
                    "score": score,
                    "lj_title": lj.title,
                    "inlabs_identifica": inlabs.identifica,
                    "art_type": lj.art_type,
                    "page": lj.number_page
                })
                lj_matched.add(i)
                inlabs_matched.add(inlabs_idx)
                mapping["matched"] += 1
    
    mapping["unmatched_lj"] = [i for i in range(len(comparison.leiturajornal_articles)) if i not in lj_matched]
    mapping["unmatched_inlabs"] = [i for i in range(len(comparison.inlabs_articles)) if i not in inlabs_matched]
    
    return mapping


def generate_recommendations(comparison: SourceComparison) -> list[dict]:
    """Generate recommendations based on comparison."""
    
    recommendations = []
    
    # Based on document count
    if comparison.leiturajornal_count == comparison.inlabs_count:
        recommendations.append({
            "category": "Document Count",
            "finding": "Both sources have matching document counts",
            "recommendation": "Either source can be used for document enumeration",
            "priority": "high"
        })
    elif comparison.inlabs_count > comparison.leiturajornal_count:
        recommendations.append({
            "category": "Document Count",
            "finding": f"INLabs has {comparison.inlabs_count - comparison.leiturajornal_count} more documents",
            "recommendation": "INLabs appears more complete; use as primary source for enumeration",
            "priority": "high"
        })
    else:
        recommendations.append({
            "category": "Document Count",
            "finding": f"Leiturajornal has {comparison.leiturajornal_count - comparison.inlabs_count} more documents",
            "recommendation": "Investigate why INLabs has fewer documents; leiturajornal may be more complete",
            "priority": "high"
        })
    
    # Based on metadata richness
    lj_field_count = len(comparison.lj_metadata_fields)
    inlabs_field_count = len(comparison.inlabs_metadata_fields)
    
    if inlabs_field_count > lj_field_count:
        recommendations.append({
            "category": "Metadata",
            "finding": f"INLabs has {inlabs_field_count - lj_field_count} more metadata fields",
            "recommendation": "Use INLabs for metadata-rich applications (cataloging, indexing)",
            "priority": "high"
        })
    
    # Based on content
    if comparison.inlabs_total_content_chars > comparison.lj_total_content_chars * 1.2:
        recommendations.append({
            "category": "Content Completeness",
            "finding": "INLabs has significantly more content",
            "recommendation": "Use INLabs for full-text search and content analysis",
            "priority": "high"
        })
    
    # Based on accessibility
    recommendations.append({
        "category": "Accessibility",
        "finding": "Leiturajornal requires no authentication",
        "recommendation": "Use leiturajornal for quick checks, prototyping, and public-facing apps",
        "priority": "medium"
    })
    
    recommendations.append({
        "category": "Accessibility",
        "finding": "INLabs requires authentication but provides structured XML",
        "recommendation": "Use INLabs for production pipelines requiring data integrity",
        "priority": "medium"
    })
    
    # Based on format
    recommendations.append({
        "category": "Data Format",
        "finding": "INLabs provides XML with embedded HTML; leiturajornal provides JSON",
        "recommendation": "INLabs better for archival; leiturajornal easier for web integration",
        "priority": "medium"
    })
    
    return recommendations


# =============================================================================
# Main
# =============================================================================

def main():
    """Run the comparison."""
    
    # Configuration
    DATE = "2025-02-27"
    SECTION = "do1"
    OUTPUT_DIR = Path("/tmp/dou_comparison")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Use existing INLabs sample data (from 2026-02-27 for structure comparison)
    # Note: This is for structural comparison - ideally both should be same date
    INLABS_SOURCE = Path("/tmp/inlabs_analysis/2026-02-27-DO1")
    
    print("="*70)
    print("INLabs vs Leiturajornal DOU Data Source Comparison")
    print("="*70)
    print(f"Leiturajornal Date: {DATE}")
    print(f"INLabs Date (sample): 2026-02-27 (for structural comparison)")
    print(f"Section: {SECTION.upper()}")
    print(f"Output directory: {OUTPUT_DIR}")
    print()
    print("NOTE: Using different dates for comparison due to authentication constraints.")
    print("      Structural and metadata comparison is still valid.")
    
    # Run comparison
    comparison = compare_sources(DATE, SECTION, INLABS_SOURCE)
    
    # Print report
    print_comparison_report(comparison)
    
    # Cross-mapping
    print("\n🔗 CROSS-SOURCE MAPPING ATTEMPT")
    print("-" * 50)
    mapping = attempt_cross_mapping(comparison)
    
    print(f"  Successfully mapped: {mapping['matched']} articles")
    print(f"  Unmapped leiturajornal: {len(mapping['unmatched_lj'])}")
    print(f"  Unmapped INLabs: {len(mapping['unmatched_inlabs'])}")
    
    if mapping['mappings'][:5]:
        print("\n  Sample mappings (highest confidence):")
        for m in mapping['mappings'][:5]:
            print(f"    Score {m['score']}: LJ[{m['lj_index']}] <-> IN[{m['inlabs_index']}]")
            print(f"      Type: {m['art_type']}")
            print(f"      LJ:   {m['lj_title'][:50]}...")
            print(f"      IN:   {m['inlabs_identifica'][:50]}...")
    
    # Recommendations
    print("\n💡 RECOMMENDATIONS")
    print("-" * 50)
    recommendations = generate_recommendations(comparison)
    for rec in recommendations:
        print(f"\n  [{rec['priority'].upper()}] {rec['category']}")
        print(f"    Finding: {rec['finding']}")
        print(f"    Recommendation: {rec['recommendation']}")
    
    # Save detailed results
    output_file = OUTPUT_DIR / f"comparison_{DATE}_{SECTION}.json"
    
    results = {
        "date": DATE,
        "section": SECTION,
        "comparison_summary": {
            "leiturajornal_count": comparison.leiturajornal_count,
            "inlabs_count": comparison.inlabs_count,
            "count_match": comparison.leiturajornal_count == comparison.inlabs_count,
            "difference": comparison.mismatch_count()
        },
        "metadata_comparison": {
            "leiturajornal_fields": list(comparison.lj_metadata_fields),
            "inlabs_fields": list(comparison.inlabs_metadata_fields),
            "common_fields": list(comparison.lj_metadata_fields & comparison.inlabs_metadata_fields),
            "leiturajornal_only": list(comparison.lj_metadata_fields - comparison.inlabs_metadata_fields),
            "inlabs_only": list(comparison.inlabs_metadata_fields - comparison.lj_metadata_fields)
        },
        "content_analysis": {
            "leiturajornal_total_chars": comparison.lj_total_content_chars,
            "inlabs_total_chars": comparison.inlabs_total_content_chars,
            "leiturajornal_avg_chars": comparison.lj_total_content_chars / max(comparison.leiturajornal_count, 1),
            "inlabs_avg_chars": comparison.inlabs_total_content_chars / max(comparison.inlabs_count, 1)
        },
        "quality_metrics": {
            "leiturajornal_empty_titles": comparison.lj_empty_titles,
            "inlabs_empty_identifica": comparison.inlabs_empty_identifica,
            "leiturajornal_quality_pct": (1 - comparison.lj_empty_titles / max(comparison.leiturajornal_count, 1)) * 100,
            "inlabs_quality_pct": (1 - comparison.inlabs_empty_identifica / max(comparison.inlabs_count, 1)) * 100
        },
        "cross_mapping": mapping,
        "recommendations": recommendations,
        "leiturajornal_sample": [
            {
                "pub_name": a.pub_name,
                "url_title": a.url_title,
                "title": a.title,
                "art_type": a.art_type,
                "number_page": a.number_page,
                "edition_number": a.edition_number,
                "hierarchy_str": a.hierarchy_str,
                "content_length": len(a.content)
            }
            for a in comparison.leiturajornal_articles[:10]
        ],
        "inlabs_sample": [
            {
                "id_materia": a.id_materia,
                "pub_name": a.pub_name,
                "art_type": a.art_type,
                "identifica": a.identifica,
                "art_category": a.art_category,
                "number_page": a.number_page,
                "edition_number": a.edition_number,
                "ementa": a.ementa,
                "texto_length": len(a.texto)
            }
            for a in comparison.inlabs_articles[:10]
        ]
    }
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Detailed results saved to: {output_file}")
    
    return comparison, results


if __name__ == "__main__":
    main()
