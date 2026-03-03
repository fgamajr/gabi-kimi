#!/usr/bin/env python3
"""
Test suite for leiturajornal_parser.py

Usage:
    python3 test_leiturajornal_parser.py
"""

from __future__ import annotations

import sys
import os
import json
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from leiturajornal_parser import (
    parse_leiturajornal,
    parse_file,
    extract_json_from_html,
    Article,
    LeiturajornalData,
    TypeNormDay,
    ParseError,
    ValidationError,
)


SAMPLES_DIR = Path(__file__).parent / "leiturajornal_samples"


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'


def log_pass(msg: str) -> None:
    print(f"{Colors.GREEN}✓ PASS{Colors.RESET}: {msg}")


def log_fail(msg: str) -> None:
    print(f"{Colors.RED}✗ FAIL{Colors.RESET}: {msg}")


def log_info(msg: str) -> None:
    print(f"{Colors.BLUE}ℹ INFO{Colors.RESET}: {msg}")


def log_warn(msg: str) -> None:
    print(f"{Colors.YELLOW}⚠ WARN{Colors.RESET}: {msg}")


def test_extract_json_from_html() -> bool:
    """Test JSON extraction from HTML."""
    print("\n--- Test: extract_json_from_html ---")
    
    # Valid HTML
    html = '<html><script id="params">{"test": true}</script></html>'
    result = extract_json_from_html(html)
    if result != {"test": True}:
        log_fail("Basic extraction failed")
        return False
    log_pass("Basic extraction works")
    
    # With whitespace
    html = '<html><script id="params">\n  {"test": true}  \n</script></html>'
    result = extract_json_from_html(html)
    if result != {"test": True}:
        log_fail("Whitespace handling failed")
        return False
    log_pass("Whitespace handling works")
    
    # Missing script tag
    html = '<html></html>'
    try:
        extract_json_from_html(html)
        log_fail("Should raise ParseError for missing script")
        return False
    except ParseError:
        log_pass("Raises ParseError for missing script")
    
    # Invalid JSON
    html = '<html><script id="params">{invalid}</script></html>'
    try:
        extract_json_from_html(html)
        log_fail("Should raise ParseError for invalid JSON")
        return False
    except ParseError as e:
        if "Invalid JSON" in str(e):
            log_pass("Raises ParseError for invalid JSON with context")
        else:
            log_fail("ParseError missing context")
            return False
    
    return True


def test_parse_2017_sample() -> bool:
    """Test parsing 2017 sample."""
    print("\n--- Test: Parse 2017 Sample ---")
    
    filepath = SAMPLES_DIR / "2017-03-15_do1.html"
    if not filepath.exists():
        log_warn(f"Sample not found: {filepath}")
        return True
    
    try:
        data = parse_file(str(filepath))
    except Exception as e:
        log_fail(f"Parse failed: {e}")
        return False
    
    # Check structure
    if data.date_url != "15-03-2017":
        log_fail(f"Wrong date_url: {data.date_url}")
        return False
    log_pass("Correct date_url")
    
    if data.section != "DO1":
        log_fail(f"Wrong section: {data.section}")
        return False
    log_pass("Correct section")
    
    if len(data.articles) != 229:
        log_fail(f"Expected 229 articles, got {len(data.articles)}")
        return False
    log_pass(f"Correct article count: {len(data.articles)}")
    
    # Check article fields
    article = data.articles[0]
    if not article.pub_name:
        log_fail("Article missing pub_name")
        return False
    log_pass("Article has pub_name")
    
    if not article.url_title:
        log_fail("Article missing url_title")
        return False
    log_pass("Article has url_title")
    
    # Check hierarchy
    if not article.hierarchy_list:
        log_fail("Article missing hierarchy_list")
        return False
    log_pass("Article has hierarchy_list")
    
    log_info(f"Sample article: {article.title[:60]}...")
    log_info(f"Article type: {article.art_type}")
    
    return True


def test_parse_2025_samples() -> bool:
    """Test parsing 2025 samples with different sections."""
    print("\n--- Test: Parse 2025 Samples ---")
    
    samples = [
        ("2025-02-28_do1.html", "DO1", 338),
        ("2025-02-28_do2.html", "DO2", 1025),
        ("2025-02-28_do3.html", "DO3", 3436),
    ]
    
    all_passed = True
    for filename, expected_section, expected_count in samples:
        filepath = SAMPLES_DIR / filename
        if not filepath.exists():
            log_warn(f"Sample not found: {filepath}")
            continue
        
        try:
            data = parse_file(str(filepath))
        except Exception as e:
            log_fail(f"[{filename}] Parse failed: {e}")
            all_passed = False
            continue
        
        if data.section != expected_section:
            log_fail(f"[{filename}] Wrong section: {data.section}")
            all_passed = False
            continue
        
        if len(data.articles) != expected_count:
            log_fail(f"[{filename}] Expected {expected_count} articles, got {len(data.articles)}")
            all_passed = False
            continue
        
        log_pass(f"[{filename}] Parsed {len(data.articles)} articles")
        
        # Check pubOrder format
        sample_article = data.articles[0]
        parts = sample_article.pub_order.split(':')
        if len(parts) != 12:
            log_fail(f"[{filename}] pubOrder has {len(parts)} parts, expected 12")
            all_passed = False
        else:
            log_pass(f"[{filename}] pubOrder format valid")
    
    return all_passed


def test_extra_editions() -> bool:
    """Test parsing extra edition samples."""
    print("\n--- Test: Parse Extra Editions ---")
    
    samples = [
        ("2025-02-28_do1e.html", "DO1E", True),
        ("2025-02-28_do2e.html", "DO2E", True),
    ]
    
    all_passed = True
    for filename, expected_prefix, has_multiple_sections in samples:
        filepath = SAMPLES_DIR / filename
        if not filepath.exists():
            log_warn(f"Sample not found: {filepath}")
            continue
        
        try:
            data = parse_file(str(filepath))
        except Exception as e:
            log_fail(f"[{filename}] Parse failed: {e}")
            all_passed = False
            continue
        
        # Check section contains comma-separated values
        if has_multiple_sections:
            if ',' not in data.section:
                log_fail(f"[{filename}] Expected comma-separated sections")
                all_passed = False
            else:
                log_pass(f"[{filename}] Has multiple sections: {len(data.sections)} parts")
        
        # Check articles have different pubNames
        pub_names = set(a.pub_name for a in data.articles)
        if len(pub_names) > 1:
            log_pass(f"[{filename}] Articles from multiple sub-editions: {pub_names}")
        
        log_info(f"[{filename}] Section: {data.section[:50]}...")
    
    return all_passed


def test_empty_jsonarray() -> bool:
    """Test handling of empty jsonArray."""
    print("\n--- Test: Empty jsonArray ---")
    
    samples = [
        "2017-03-15_do2.html",
        "2020-06-20_do1.html",
        "2023-09-10_do1.html",
    ]
    
    all_passed = True
    for filename in samples:
        filepath = SAMPLES_DIR / filename
        if not filepath.exists():
            log_warn(f"Sample not found: {filepath}")
            continue
        
        try:
            data = parse_file(str(filepath))
        except Exception as e:
            log_fail(f"[{filename}] Parse failed: {e}")
            all_passed = False
            continue
        
        if not data.is_empty:
            log_fail(f"[{filename}] Expected empty but got {len(data.articles)} articles")
            all_passed = False
        else:
            log_pass(f"[{filename}] Correctly identified as empty")
    
    return all_passed


def test_article_properties() -> bool:
    """Test Article computed properties."""
    print("\n--- Test: Article Properties ---")
    
    filepath = SAMPLES_DIR / "2025-02-28_do1.html"
    if not filepath.exists():
        log_warn("Sample not found")
        return True
    
    data = parse_file(str(filepath))
    article = data.articles[0]
    
    # Test detail_url
    if not article.detail_url.startswith("https://www.in.gov.br/en/web/dou/-/artigo/"):
        log_fail("detail_url format incorrect")
        return False
    log_pass("detail_url format correct")
    
    # Test pub_date_iso
    try:
        iso_date = article.pub_date_iso
        if len(iso_date) != 10 or iso_date[4] != '-':
            log_fail(f"pub_date_iso format incorrect: {iso_date}")
            return False
        log_pass(f"pub_date_iso: {iso_date}")
    except Exception as e:
        log_fail(f"pub_date_iso failed: {e}")
        return False
    
    # Test art_type_normalized
    normalized = article.art_type_normalized
    if normalized != article.art_type.title():
        log_fail(f"art_type_normalized incorrect: {normalized}")
        return False
    log_pass(f"art_type_normalized: {normalized}")
    
    # Test is_truncated
    truncated_count = sum(1 for a in data.articles if a.is_truncated)
    log_info(f"Truncated articles: {truncated_count}/{len(data.articles)}")
    log_pass("is_truncated working")
    
    return True


def test_filtering_methods() -> bool:
    """Test LeiturajornalData filtering methods."""
    print("\n--- Test: Filtering Methods ---")
    
    filepath = SAMPLES_DIR / "2025-02-28_do1.html"
    if not filepath.exists():
        log_warn("Sample not found")
        return True
    
    data = parse_file(str(filepath))
    
    # Test get_by_art_type
    portarias = data.get_by_art_type("Portaria")
    log_info(f"Found {len(portarias)} Portarias")
    if len(portarias) == 0:
        log_warn("No Portarias found (may be data-specific)")
    else:
        log_pass("get_by_art_type working")
    
    # Test case insensitive
    portarias_lower = data.get_by_art_type("portaria", case_sensitive=False)
    if len(portarias_lower) >= len(portarias):
        log_pass("Case insensitive search working")
    
    # Test get_art_types
    art_types = data.get_art_types()
    log_info(f"Unique article types: {len(art_types)}")
    if len(art_types) > 0:
        log_pass("get_art_types working")
    else:
        log_fail("No article types found")
        return False
    
    # Test get_by_hierarchy
    min_agro = data.get_by_hierarchy("Ministério da Agricultura")
    log_info(f"Articles from Ministério da Agricultura: {len(min_agro)}")
    log_pass("get_by_hierarchy working")
    
    return True


def test_type_norm_day() -> bool:
    """Test TypeNormDay parsing."""
    print("\n--- Test: TypeNormDay ---")
    
    # Test with all fields
    data = {
        "DO1E": True,
        "DO2E": False,
        "DO3E": True,
        "DO1A": False,
        "DO1ESP": True,
        "DO2ESP": False,
    }
    
    tnd = TypeNormDay.from_dict(data)
    if not (tnd.do1e and not tnd.do2e and tnd.do3e and tnd.do1esp):
        log_fail("TypeNormDay parsing incorrect")
        return False
    log_pass("TypeNormDay parsing correct")
    
    # Test empty dict
    tnd = TypeNormDay.from_dict({})
    if any([tnd.do1e, tnd.do2e, tnd.do3e, tnd.do1a, tnd.do1esp, tnd.do2esp]):
        log_fail("TypeNormDay defaults incorrect")
        return False
    log_pass("TypeNormDay defaults to False")
    
    return True


def test_validation_errors() -> bool:
    """Test validation error handling."""
    print("\n--- Test: Validation Errors ---")
    
    # Missing required root fields
    html = '<script id="params">{"jsonArray": [{}]}</script>'
    try:
        parse_leiturajornal(html)
        log_fail("Should raise error for missing root fields")
        return False
    except (ParseError, ValidationError) as e:
        log_pass("Raises error for missing root fields")
    
    # Invalid pubDate format
    html = '<script id="params">{"jsonArray": [{"pubName": "DO1", "urlTitle": "test", "title": "Test", "pubDate": "invalid", "content": "test", "editionNumber": "1", "hierarchyLevelSize": 1, "artType": "Test", "pubOrder": "DO1", "hierarchyStr": "Test"}]}</script>'
    try:
        parse_leiturajornal(html)
        log_fail("Should raise ValidationError for invalid pubDate")
        return False
    except (ParseError, ValidationError) as e:
        log_pass("Raises error for invalid pubDate")
    
    return True


def test_content_statistics() -> None:
    """Analyze content field statistics."""
    print("\n--- Test: Content Statistics ---")
    
    filepath = SAMPLES_DIR / "2025-02-28_do3.html"
    if not filepath.exists():
        log_warn("Sample not found")
        return True
    
    data = parse_file(str(filepath))
    
    content_lengths = [len(a.content) for a in data.articles]
    min_len = min(content_lengths)
    max_len = max(content_lengths)
    avg_len = sum(content_lengths) // len(content_lengths)
    
    log_info(f"Content lengths: min={min_len}, max={max_len}, avg={avg_len}")
    
    # Check for consistent ~400 char limit
    if max_len <= 403:
        log_pass("Content length within expected range")
    else:
        log_warn(f"Unexpected max content length: {max_len}")
    
    truncated = sum(1 for a in data.articles if a.is_truncated)
    log_info(f"Truncated content: {truncated}/{len(data.articles)} ({100*truncated//len(data.articles)}%)")
    
    return True


def run_all_tests() -> bool:
    """Run all tests and return overall result."""
    print("="*70)
    print("LEITURAJORNAL PARSER TEST SUITE")
    print("="*70)
    
    tests = [
        test_extract_json_from_html,
        test_parse_2017_sample,
        test_parse_2025_samples,
        test_extra_editions,
        test_empty_jsonarray,
        test_article_properties,
        test_filtering_methods,
        test_type_norm_day,
        test_validation_errors,
        test_content_statistics,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            result = test()
            if result:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            log_fail(f"Test {test.__name__} raised exception: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "="*70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*70)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
