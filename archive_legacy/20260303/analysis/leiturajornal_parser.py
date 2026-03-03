#!/usr/bin/env python3
"""
Leiturajornal HTML Parser

Parses HTML from https://www.in.gov.br/leiturajornal containing embedded JSON
data with Brazilian Official Gazette (DOU) article listings.

Usage:
    from leiturajornal_parser import parse_leiturajornal, fetch_and_parse
    
    # Parse local HTML file
    with open('page.html', 'r', encoding='utf-8') as f:
        result = parse_leiturajornal(f.read())
    
    # Fetch and parse from URL
    result = fetch_and_parse('28-02-2025', 'do1')
"""

from __future__ import annotations

import json
import gzip
import re
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime
from enum import Enum


class Section(Enum):
    """Valid section identifiers."""
    DO1 = "do1"
    DO2 = "do2"
    DO3 = "do3"
    DO1E = "do1e"
    DO2E = "do2e"
    DO3E = "do3e"
    DO1A = "do1a"
    DO1ESP = "do1esp"
    DO2ESP = "do2esp"


class ParseError(Exception):
    """Raised when HTML parsing fails."""
    pass


class ValidationError(Exception):
    """Raised when data validation fails."""
    pass


@dataclass(frozen=True, slots=True)
class TypeNormDay:
    """Flags indicating available special editions."""
    do1e: bool = False
    do2e: bool = False
    do3e: bool = False
    do1a: bool = False
    do1esp: bool = False
    do2esp: bool = False
    
    @classmethod
    def from_dict(cls, data: dict[str, bool]) -> TypeNormDay:
        """Create from dictionary with case-insensitive keys."""
        return cls(
            do1e=data.get('DO1E', False),
            do2e=data.get('DO2E', False),
            do3e=data.get('DO3E', False),
            do1a=data.get('DO1A', False),
            do1esp=data.get('DO1ESP', False),
            do2esp=data.get('DO2ESP', False),
        )


@dataclass(frozen=True, slots=True)
class Article:
    """Single article from the DOU."""
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
    hierarchy_list: tuple[str, ...] = field(default_factory=tuple)
    
    @property
    def art_type_normalized(self) -> str:
        """Return normalized (title case) article type."""
        return self.art_type.strip().title()
    
    @property
    def is_truncated(self) -> bool:
        """Check if content field is truncated."""
        return self.content.endswith('...')
    
    @property
    def detail_url(self) -> str:
        """Construct detail URL for this article."""
        return f"https://www.in.gov.br/en/web/dou/-/artigo/{self.url_title}"
    
    @property
    def pub_date_iso(self) -> str:
        """Convert pubDate from DD/MM/YYYY to ISO format (YYYY-MM-DD)."""
        try:
            dt = datetime.strptime(self.pub_date, "%d/%m/%Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return self.pub_date
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Article:
        """Create Article from dictionary."""
        # Validate required fields
        required = ['pubName', 'urlTitle', 'numberPage', 'title', 'pubDate', 
                   'content', 'editionNumber', 'hierarchyLevelSize', 'artType', 
                   'pubOrder', 'hierarchyStr']
        missing = [f for f in required if f not in data]
        if missing:
            raise ValidationError(f"Missing required fields: {missing}")
        
        # Convert hierarchyList to tuple for immutability
        hierarchy_list = tuple(data.get('hierarchyList', []))
        
        return cls(
            pub_name=data['pubName'],
            url_title=data['urlTitle'],
            number_page=data['numberPage'],
            sub_titulo=data.get('subTitulo', ''),
            titulo=data.get('titulo', ''),
            title=data['title'],
            pub_date=data['pubDate'],
            content=data['content'],
            edition_number=data['editionNumber'],
            hierarchy_level_size=data['hierarchyLevelSize'],
            art_type=data['artType'],
            pub_order=data['pubOrder'],
            hierarchy_str=data['hierarchyStr'],
            hierarchy_list=hierarchy_list,
        )


@dataclass(frozen=True, slots=True)
class LeiturajornalData:
    """Complete parsed data from leiturajornal page."""
    type_norm_day: TypeNormDay
    id_portlet_instance: str
    date_url: str
    section: str
    sections: tuple[str, ...]  # Split comma-separated sections
    articles: tuple[Article, ...]
    raw_json: dict[str, Any]  # Original parsed JSON
    
    @property
    def is_empty(self) -> bool:
        """Check if no articles found."""
        return len(self.articles) == 0
    
    @property
    def article_count(self) -> int:
        """Total number of articles."""
        return len(self.articles)
    
    @property
    def is_extra_edition(self) -> bool:
        """Check if this is an extra edition (has multiple sections)."""
        return len(self.sections) > 1
    
    def get_by_art_type(self, art_type: str, case_sensitive: bool = False) -> list[Article]:
        """Filter articles by type."""
        if case_sensitive:
            return [a for a in self.articles if a.art_type == art_type]
        return [a for a in self.articles if a.art_type.lower() == art_type.lower()]
    
    def get_by_pub_name(self, pub_name: str) -> list[Article]:
        """Filter articles by publication name (for extra editions)."""
        return [a for a in self.articles if a.pub_name == pub_name]
    
    def get_by_hierarchy(self, hierarchy_prefix: str) -> list[Article]:
        """Filter articles by hierarchy path prefix."""
        return [a for a in self.articles 
                if a.hierarchy_str.startswith(hierarchy_prefix)]
    
    def get_art_types(self) -> set[str]:
        """Get all unique article types."""
        return set(a.art_type for a in self.articles)
    
    def get_pub_names(self) -> set[str]:
        """Get all unique publication names."""
        return set(a.pub_name for a in self.articles)


def extract_json_from_html(html: str) -> dict[str, Any]:
    """
    Extract and parse JSON from the <script id="params"> tag.
    
    Args:
        html: Raw HTML content
        
    Returns:
        Parsed JSON dictionary
        
    Raises:
        ParseError: If script tag not found or JSON invalid
    """
    # Handle both CRLF and LF line endings
    html = html.replace('\r\n', '\n').replace('\r', '\n')
    
    # Find the script tag with id="params"
    # Use non-greedy match and handle potential whitespace
    pattern = r'<script\s+id=["\']params["\'][^>]*>(.*?)<\/script>'
    match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
    
    if not match:
        raise ParseError("Could not find <script id='params'> tag in HTML")
    
    json_content = match.group(1).strip()
    
    if not json_content:
        raise ParseError("Script tag with id='params' is empty")
    
    try:
        return json.loads(json_content)
    except json.JSONDecodeError as e:
        # Provide context around the error
        error_pos = e.pos if hasattr(e, 'pos') else 0
        context_start = max(0, error_pos - 50)
        context_end = min(len(json_content), error_pos + 50)
        context = json_content[context_start:context_end]
        raise ParseError(f"Invalid JSON in params script: {e}\nContext: ...{context}...")


def validate_article_data(data: dict[str, Any]) -> None:
    """Validate article data structure."""
    required_fields = ['pubName', 'urlTitle', 'title', 'pubDate', 
                      'content', 'artType', 'pubOrder']
    
    for field in required_fields:
        if field not in data:
            raise ValidationError(f"Article missing required field: {field}")
        if not isinstance(data[field], str):
            raise ValidationError(f"Article field {field} must be string, got {type(data[field])}")
    
    # Validate pubDate format
    try:
        datetime.strptime(data['pubDate'], "%d/%m/%Y")
    except ValueError:
        raise ValidationError(f"Invalid pubDate format: {data['pubDate']}")


def parse_leiturajornal(html: str) -> LeiturajornalData:
    """
    Parse leiturajornal HTML and return structured data.
    
    Args:
        html: Raw HTML content from leiturajornal endpoint
        
    Returns:
        LeiturajornalData object with parsed articles
        
    Raises:
        ParseError: If HTML structure is invalid
        ValidationError: If data validation fails
    """
    # Extract JSON from HTML
    raw_data = extract_json_from_html(html)
    
    # Validate root structure
    if not isinstance(raw_data, dict):
        raise ParseError(f"Expected JSON object, got {type(raw_data).__name__}")
    
    required_root = ['typeNormDay', 'dateUrl', 'section', 'jsonArray']
    missing = [f for f in required_root if f not in raw_data]
    if missing:
        raise ParseError(f"Missing required root fields: {missing}")
    
    # Parse TypeNormDay
    try:
        type_norm_day = TypeNormDay.from_dict(raw_data.get('typeNormDay', {}))
    except Exception as e:
        raise ValidationError(f"Invalid typeNormDay structure: {e}")
    
    # Parse articles
    raw_articles = raw_data.get('jsonArray', [])
    if not isinstance(raw_articles, list):
        raise ParseError(f"jsonArray must be list, got {type(raw_articles).__name__}")
    
    articles: list[Article] = []
    for idx, raw_article in enumerate(raw_articles):
        if not isinstance(raw_article, dict):
            raise ValidationError(f"Article at index {idx} is not an object")
        try:
            validate_article_data(raw_article)
            articles.append(Article.from_dict(raw_article))
        except ValidationError as e:
            raise ValidationError(f"Article at index {idx}: {e}")
    
    # Handle section (may be comma-separated for extra editions)
    section_str = raw_data.get('section', '')
    sections = tuple(s.strip() for s in section_str.split(',')) if section_str else ()
    
    return LeiturajornalData(
        type_norm_day=type_norm_day,
        id_portlet_instance=raw_data.get('idPortletInstance', ''),
        date_url=raw_data['dateUrl'],
        section=section_str,
        sections=sections,
        articles=tuple(articles),
        raw_json=raw_data,
    )


def fetch_and_parse(
    date: str, 
    section: str | Section,
    base_url: str = "https://www.in.gov.br/leiturajornal",
    timeout: int = 60,
    use_gzip: bool = True,
) -> LeiturajornalData:
    """
    Fetch leiturajornal page and parse it.
    
    Args:
        date: Date in DD-MM-YYYY format
        section: Section identifier (use Section enum or string)
        base_url: Base URL for the endpoint
        timeout: Request timeout in seconds
        use_gzip: Request gzip compression
        
    Returns:
        LeiturajornalData object
        
    Raises:
        urllib.error.URLError: If network request fails
        ParseError: If parsing fails
    """
    # Build URL
    sec = section.value if isinstance(section, Section) else section
    url = f"{base_url}?data={date}&secao={sec}"
    
    # Build request headers
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
    }
    
    if use_gzip:
        headers['Accept-Encoding'] = 'gzip, deflate'
    
    request = urllib.request.Request(url, headers=headers)
    
    # Fetch with timeout
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content = response.read()
        
        # Handle gzip decompression
        encoding = response.headers.get('Content-Encoding', '')
        if 'gzip' in encoding:
            content = gzip.decompress(content)
        
        html = content.decode('utf-8')
    
    return parse_leiturajornal(html)


def parse_file(filepath: str) -> LeiturajornalData:
    """
    Parse a local HTML file.
    
    Args:
        filepath: Path to HTML file
        
    Returns:
        LeiturajornalData object
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        return parse_leiturajornal(f.read())


# --- CLI Interface ---

if __name__ == "__main__":
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Parse leiturajornal HTML files"
    )
    parser.add_argument(
        "input",
        help="HTML file to parse, or 'fetch' to download"
    )
    parser.add_argument(
        "--date",
        help="Date for fetch mode (DD-MM-YYYY)"
    )
    parser.add_argument(
        "--section",
        help="Section for fetch mode (do1, do2, do3, do1e, etc.)"
    )
    parser.add_argument(
        "--format",
        choices=["summary", "json", "csv"],
        default="summary",
        help="Output format"
    )
    parser.add_argument(
        "--filter-type",
        help="Filter by article type"
    )
    
    args = parser.parse_args()
    
    try:
        if args.input == "fetch":
            if not args.date or not args.section:
                print("Error: --date and --section required for fetch mode")
                sys.exit(1)
            data = fetch_and_parse(args.date, args.section)
        else:
            data = parse_file(args.input)
        
        # Apply filters
        articles = list(data.articles)
        if args.filter_type:
            articles = [a for a in articles 
                       if args.filter_type.lower() in a.art_type.lower()]
        
        # Output
        if args.format == "summary":
            print(f"Date: {data.date_url}")
            print(f"Section: {data.section}")
            print(f"Is Extra Edition: {data.is_extra_edition}")
            print(f"Total Articles: {len(articles)}")
            print(f"\nArticle Types:")
            for art_type in sorted(set(a.art_type for a in articles)):
                count = sum(1 for a in articles if a.art_type == art_type)
                print(f"  {art_type}: {count}")
            print(f"\nPublication Names:")
            for pub_name in sorted(set(a.pub_name for a in articles)):
                count = sum(1 for a in articles if a.pub_name == pub_name)
                print(f"  {pub_name}: {count}")
                
        elif args.format == "json":
            output = {
                "date_url": data.date_url,
                "section": data.section,
                "article_count": len(articles),
                "articles": [
                    {
                        "pub_name": a.pub_name,
                        "art_type": a.art_type,
                        "title": a.title,
                        "pub_date": a.pub_date,
                        "url": a.detail_url,
                    }
                    for a in articles[:100]  # Limit output
                ]
            }
            print(json.dumps(output, indent=2, ensure_ascii=False))
            
        elif args.format == "csv":
            print("pub_name,art_type,title,pub_date,page,hierarchy")
            for a in articles:
                hierarchy = a.hierarchy_str.replace('"', '""')
                print(f'"{a.pub_name}","{a.art_type}","{a.title}",{a.pub_date},{a.number_page},"{hierarchy}"')
                
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
