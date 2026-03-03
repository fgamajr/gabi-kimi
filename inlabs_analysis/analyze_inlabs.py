#!/usr/bin/env python3
"""
INLabs ZIP File Structure Analyzer for DOU Data
Analyzes ZIP downloads from https://inlabs.in.gov.br/
"""
from __future__ import annotations

import os
import sys
import re
import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime
from collections import defaultdict
import subprocess

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configuration
INLABS_BASE = "https://inlabs.in.gov.br/index.php"
USERNAME = "fgamajr@gmail.com"
PASSWORD = "kqg8YDZ2eya3exq_wev"

SECTIONS = ["DO1", "DO2", "DO3", "DO1E", "DO2E", "DO3E"]
DATES = ["2026-02-26", "2026-02-27", "2026-02-28", "2026-03-01", "2026-03-02"]

DOWNLOAD_DIR = Path("downloads")
ANALYSIS_DIR = Path("analysis")


@dataclass
class FileInfo:
    name: str
    size_bytes: int
    extension: str


@dataclass
class ZipAnalysis:
    date: str
    section: str
    zip_path: Path
    zip_size_bytes: int
    files: list[FileInfo] = field(default_factory=list)
    xml_files: list[FileInfo] = field(default_factory=list)
    image_files: list[FileInfo] = field(default_factory=list)
    other_files: list[FileInfo] = field(default_factory=list)
    xml_structures: list[dict] = field(default_factory=list)
    
    @property
    def total_files(self) -> int:
        return len(self.files)
    
    @property
    def xml_count(self) -> int:
        return len(self.xml_files)
    
    @property
    def image_count(self) -> int:
        return len(self.image_files)
    
    @property
    def avg_xml_size(self) -> float:
        if not self.xml_files:
            return 0.0
        return sum(f.size_bytes for f in self.xml_files) / len(self.xml_files)
    
    @property
    def avg_image_size(self) -> float:
        if not self.image_files:
            return 0.0
        return sum(f.size_bytes for f in self.image_files) / len(self.image_files)


class INLabsSession:
    """Manages INLabs login session."""
    
    def __init__(self):
        self.session = requests.Session()
        retry = Retry(connect=3, backoff_factor=0.5)
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self.logged_in = False
        
    def login(self) -> bool:
        """Login to INLabs and store session."""
        print(f"Logging into INLabs as {USERNAME}...")
        
        # First, get the login page to extract any CSRF token
        login_url = "https://inlabs.in.gov.br/logar.php"
        
        login_data = {
            "email": USERNAME,
            "password": PASSWORD
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "Origin": "https://inlabs.in.gov.br",
            "Referer": "https://inlabs.in.gov.br/",
        }
        
        try:
            response = self.session.post(
                login_url, 
                data=login_data, 
                headers=headers,
                timeout=30,
                allow_redirects=True
            )
            
            # Check if login was successful
            if "inlabs" in response.url or response.status_code == 200:
                # Check for logout link or dashboard indicator
                if "sair" in response.text.lower() or "logout" in response.text.lower() or "minha conta" in response.text.lower():
                    print("Login successful!")
                    self.logged_in = True
                    return True
                # Also check if we got redirected to index with session
                if "phpsessid" in str(self.session.cookies).lower() or len(self.session.cookies) > 0:
                    print(f"Login successful! Cookies: {dict(self.session.cookies)}")
                    self.logged_in = True
                    return True
            
            print(f"Login response URL: {response.url}")
            print(f"Login response status: {response.status_code}")
            print(f"Response contains 'sair': {'sair' in response.text.lower()}")
            print(f"Response contains 'logout': {'logout' in response.text.lower()}")
            
            # Try alternative login check
            test_response = self.session.get(INLABS_BASE, timeout=30)
            if any(x in test_response.text.lower() for x in ["sair", "logout", "minha conta", "download"]):
                print("Login verified via alternative check!")
                self.logged_in = True
                return True
                
            print("Login may have failed - unexpected response")
            return False
            
        except Exception as e:
            print(f"Login failed: {e}")
            return False
    
    def download_zip(self, date: str, section: str) -> Path | None:
        """Download a ZIP file for a specific date and section."""
        if not self.logged_in:
            print("Not logged in, cannot download")
            return None
            
        zip_filename = f"{date}-{section}.zip"
        download_url = f"{INLABS_BASE}?p={date}&dl={zip_filename}"
        output_path = DOWNLOAD_DIR / date / zip_filename
        
        if output_path.exists():
            print(f"  Already exists: {output_path}")
            return output_path
            
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        print(f"  Downloading {zip_filename}...")
        
        try:
            response = self.session.get(download_url, timeout=120, stream=True)
            
            if response.status_code == 200:
                content_type = response.headers.get('Content-Type', '')
                content_length = response.headers.get('Content-Length')
                
                # Check if it's actually a ZIP
                if 'zip' in content_type.lower() or content_length:
                    with open(output_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    size_mb = output_path.stat().st_size / (1024 * 1024)
                    print(f"    Downloaded: {size_mb:.2f} MB")
                    return output_path
                else:
                    print(f"    Not a ZIP file (Content-Type: {content_type})")
                    # Save response for debugging
                    debug_path = output_path.with_suffix('.html')
                    with open(debug_path, 'w') as f:
                        f.write(response.text[:5000])
                    return None
            else:
                print(f"    HTTP {response.status_code}")
                return None
                
        except Exception as e:
            print(f"    Download error: {e}")
            return None


def analyze_xml_structure(xml_content: bytes, filename: str) -> dict:
    """Analyze the structure of an XML file."""
    try:
        root = ET.fromstring(xml_content)
        
        structure = {
            "filename": filename,
            "root_tag": root.tag,
            "root_attributes": dict(root.attrib),
            "child_tags": [],
            "all_tags": set(),
            "text_preview": "",
            "has_images": False,
            "image_references": []
        }
        
        # Get unique child tags
        for child in root:
            tag_name = child.tag.split('}')[-1] if '}' in child.tag else child.tag
            if tag_name not in structure["child_tags"]:
                structure["child_tags"].append(tag_name)
        
        # Collect all tags recursively
        def collect_tags(elem, tags):
            tag_name = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            tags.add(tag_name)
            for child in elem:
                collect_tags(child, tags)
        
        collect_tags(root, structure["all_tags"])
        structure["all_tags"] = sorted(list(structure["all_tags"]))
        
        # Get text preview (first 500 chars of text content)
        text_content = ''.join(root.itertext())
        structure["text_preview"] = text_content[:500].replace('\n', ' ').replace('\r', '')
        
        # Check for image references
        xml_str = xml_content.decode('utf-8', errors='ignore')
        img_patterns = [
            r'<img[^>]+src="([^"]+)"',
            r'<Imagem[^>]*>([^<]+)',
            r'arquivo="([^"]+\.(?:jpg|jpeg|png|gif|bmp))"',
            r'href="([^"]+\.(?:jpg|jpeg|png|gif|bmp))"'
        ]
        for pattern in img_patterns:
            matches = re.findall(pattern, xml_str, re.IGNORECASE)
            if matches:
                structure["has_images"] = True
                structure["image_references"].extend(matches[:5])  # First 5 matches
        
        return structure
        
    except ET.ParseError as e:
        return {
            "filename": filename,
            "error": str(e),
            "is_valid_xml": False
        }
    except Exception as e:
        return {
            "filename": filename,
            "error": str(e),
            "is_valid_xml": False
        }


def analyze_zip_file(zip_path: Path, date: str, section: str) -> ZipAnalysis:
    """Analyze a single ZIP file."""
    analysis = ZipAnalysis(
        date=date,
        section=section,
        zip_path=zip_path,
        zip_size_bytes=zip_path.stat().st_size
    )
    
    print(f"  Analyzing {zip_path.name}...")
    
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for info in zf.infolist():
            filename = info.filename
            size = info.file_size
            ext = Path(filename).suffix.lower()
            
            file_info = FileInfo(name=filename, size_bytes=size, extension=ext)
            analysis.files.append(file_info)
            
            if ext == '.xml':
                analysis.xml_files.append(file_info)
                # Analyze XML structure for a sample
                if len(analysis.xml_structures) < 3:  # Sample first 3 XMLs
                    try:
                        content = zf.read(filename)
                        structure = analyze_xml_structure(content, filename)
                        analysis.xml_structures.append(structure)
                    except Exception as e:
                        print(f"    Error analyzing {filename}: {e}")
                        
            elif ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tif', '.tiff']:
                analysis.image_files.append(file_info)
            else:
                analysis.other_files.append(file_info)
    
    return analysis


def generate_report(analyses: list[ZipAnalysis]) -> dict:
    """Generate comprehensive statistics report."""
    report = {
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total_zips_analyzed": len(analyses),
            "total_zip_size_mb": sum(a.zip_size_bytes for a in analyses) / (1024 * 1024),
            "total_xml_files": sum(a.xml_count for a in analyses),
            "total_image_files": sum(a.image_count for a in analyses),
        },
        "by_section": {},
        "by_date": {},
        "xml_schema_analysis": {
            "common_root_tags": set(),
            "common_child_tags": set(),
            "all_unique_tags": set(),
            "sample_structures": []
        },
        "naming_conventions": {
            "xml_patterns": [],
            "image_patterns": []
        }
    }
    
    # Collect statistics by section
    section_stats = defaultdict(lambda: {"count": 0, "total_size": 0, "xml_count": 0, "image_count": 0})
    date_stats = defaultdict(lambda: {"count": 0, "total_size": 0, "xml_count": 0, "image_count": 0})
    
    xml_patterns = defaultdict(int)
    image_patterns = defaultdict(int)
    
    for analysis in analyses:
        sec = analysis.section
        date = analysis.date
        
        section_stats[sec]["count"] += 1
        section_stats[sec]["total_size"] += analysis.zip_size_bytes
        section_stats[sec]["xml_count"] += analysis.xml_count
        section_stats[sec]["image_count"] += analysis.image_count
        
        date_stats[date]["count"] += 1
        date_stats[date]["total_size"] += analysis.zip_size_bytes
        date_stats[date]["xml_count"] += analysis.xml_count
        date_stats[date]["image_count"] += analysis.image_count
        
        # Analyze naming patterns
        for xml in analysis.xml_files:
            # Extract pattern (remove date/numbers)
            pattern = re.sub(r'\d+', '#', xml.name)
            xml_patterns[pattern] += 1
            
        for img in analysis.image_files:
            pattern = re.sub(r'\d+', '#', img.name)
            image_patterns[pattern] += 1
        
        # Collect XML schema info
        for struct in analysis.xml_structures:
            if "root_tag" in struct:
                report["xml_schema_analysis"]["common_root_tags"].add(struct["root_tag"])
            if "child_tags" in struct:
                report["xml_schema_analysis"]["common_child_tags"].update(struct["child_tags"])
            if "all_tags" in struct:
                report["xml_schema_analysis"]["all_unique_tags"].update(struct["all_tags"])
            report["xml_schema_analysis"]["sample_structures"].append(struct)
    
    # Convert sets to lists for JSON serialization
    report["xml_schema_analysis"]["common_root_tags"] = sorted(list(report["xml_schema_analysis"]["common_root_tags"]))
    report["xml_schema_analysis"]["common_child_tags"] = sorted(list(report["xml_schema_analysis"]["common_child_tags"]))
    report["xml_schema_analysis"]["all_unique_tags"] = sorted(list(report["xml_schema_analysis"]["all_unique_tags"]))
    
    # Calculate averages by section
    for sec, stats in section_stats.items():
        report["by_section"][sec] = {
            "zip_count": stats["count"],
            "avg_zip_size_mb": round(stats["total_size"] / stats["count"] / (1024 * 1024), 2) if stats["count"] > 0 else 0,
            "total_xml_files": stats["xml_count"],
            "total_image_files": stats["image_count"],
            "avg_xml_per_zip": round(stats["xml_count"] / stats["count"], 1) if stats["count"] > 0 else 0,
            "avg_images_per_zip": round(stats["image_count"] / stats["count"], 1) if stats["count"] > 0 else 0
        }
    
    for date, stats in date_stats.items():
        report["by_date"][date] = {
            "zip_count": stats["count"],
            "total_size_mb": round(stats["total_size"] / (1024 * 1024), 2),
            "total_xml_files": stats["xml_count"],
            "total_image_files": stats["image_count"]
        }
    
    # Top naming patterns
    report["naming_conventions"]["xml_patterns"] = sorted(xml_patterns.items(), key=lambda x: -x[1])[:10]
    report["naming_conventions"]["image_patterns"] = sorted(image_patterns.items(), key=lambda x: -x[1])[:10]
    
    return report


def print_report(report: dict, analyses: list[ZipAnalysis]):
    """Print formatted report."""
    print("\n" + "="*80)
    print("INLabs ZIP File Structure Analysis Report")
    print("="*80)
    print(f"Generated: {report['generated_at']}")
    print(f"\n{'='*80}")
    print("SUMMARY")
    print("="*80)
    print(f"Total ZIPs analyzed: {report['summary']['total_zips_analyzed']}")
    print(f"Total ZIP size: {report['summary']['total_zip_size_mb']:.2f} MB")
    print(f"Total XML files: {report['summary']['total_xml_files']}")
    print(f"Total image files: {report['summary']['total_image_files']}")
    
    print(f"\n{'='*80}")
    print("BY SECTION STATISTICS")
    print("="*80)
    for sec, stats in sorted(report['by_section'].items()):
        print(f"\n{sec}:")
        print(f"  ZIP files: {stats['zip_count']}")
        print(f"  Avg ZIP size: {stats['avg_zip_size_mb']:.2f} MB")
        print(f"  Total XML files: {stats['total_xml_files']}")
        print(f"  Total image files: {stats['total_image_files']}")
        print(f"  Avg XML per ZIP: {stats['avg_xml_per_zip']}")
        print(f"  Avg images per ZIP: {stats['avg_images_per_zip']}")
    
    print(f"\n{'='*80}")
    print("BY DATE STATISTICS")
    print("="*80)
    for date, stats in sorted(report['by_date'].items()):
        print(f"\n{date}:")
        print(f"  ZIP files: {stats['zip_count']}")
        print(f"  Total size: {stats['total_size_mb']:.2f} MB")
        print(f"  XML files: {stats['total_xml_files']}")
        print(f"  Image files: {stats['total_image_files']}")
    
    print(f"\n{'='*80}")
    print("XML SCHEMA ANALYSIS")
    print("="*80)
    schema = report['xml_schema_analysis']
    print(f"\nCommon root tags: {schema['common_root_tags']}")
    print(f"Common child tags: {schema['common_child_tags']}")
    print(f"\nAll unique tags found ({len(schema['all_unique_tags'])}):")
    for tag in schema['all_unique_tags']:
        print(f"  - {tag}")
    
    print(f"\n{'='*80}")
    print("XML NAMING CONVENTIONS")
    print("="*80)
    print("\nTop patterns:")
    for pattern, count in report['naming_conventions']['xml_patterns']:
        print(f"  {pattern}: {count} occurrences")
    
    print(f"\n{'='*80}")
    print("IMAGE NAMING CONVENTIONS")
    print("="*80)
    print("\nTop patterns:")
    for pattern, count in report['naming_conventions']['image_patterns']:
        print(f"  {pattern}: {count} occurrences")
    
    print(f"\n{'='*80}")
    print("DETAILED FILE LISTINGS")
    print("="*80)
    for analysis in analyses:
        print(f"\n{analysis.date}-{analysis.section}:")
        print(f"  ZIP size: {analysis.zip_size_bytes / (1024*1024):.2f} MB")
        print(f"  Total files: {analysis.total_files}")
        print(f"  XML files: {analysis.xml_count} (avg size: {analysis.avg_xml_size/1024:.1f} KB)")
        print(f"  Image files: {analysis.image_count} (avg size: {analysis.avg_image_size/1024:.1f} KB)")
        
        if analysis.xml_files[:5]:
            print("  Sample XML files:")
            for xml in analysis.xml_files[:5]:
                print(f"    - {xml.name} ({xml.size_bytes/1024:.1f} KB)")
        
        if analysis.image_files[:5]:
            print("  Sample image files:")
            for img in analysis.image_files[:5]:
                print(f"    - {img.name} ({img.size_bytes/1024:.1f} KB)")
    
    print(f"\n{'='*80}")
    print("SAMPLE XML STRUCTURES")
    print("="*80)
    for analysis in analyses:
        for struct in analysis.xml_structures[:2]:  # Show 2 per ZIP
            print(f"\nFile: {struct.get('filename', 'N/A')}")
            if 'root_tag' in struct:
                print(f"  Root: {struct['root_tag']}")
                print(f"  Root attrs: {struct['root_attributes']}")
                print(f"  Children: {struct['child_tags']}")
                print(f"  Has images: {struct['has_images']}")
                if struct['image_references']:
                    print(f"  Image refs: {struct['image_references'][:3]}")
                print(f"  Text preview: {struct['text_preview'][:200]}...")


def main():
    """Main analysis workflow."""
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    ANALYSIS_DIR.mkdir(exist_ok=True)
    
    # Create INLabs session and login
    session = INLabsSession()
    if not session.login():
        print("Failed to login to INLabs")
        sys.exit(1)
    
    analyses: list[ZipAnalysis] = []
    
    # Download and analyze ZIPs
    for date in DATES:
        print(f"\nProcessing date: {date}")
        for section in SECTIONS:
            zip_path = session.download_zip(date, section)
            if zip_path and zip_path.exists():
                analysis = analyze_zip_file(zip_path, date, section)
                analyses.append(analysis)
    
    if not analyses:
        print("No ZIP files were successfully downloaded or analyzed")
        sys.exit(1)
    
    # Generate report
    report = generate_report(analyses)
    
    # Save JSON report
    report_path = ANALYSIS_DIR / "inlabs_analysis_report.json"
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nJSON report saved to: {report_path}")
    
    # Save detailed structures
    structures_path = ANALYSIS_DIR / "xml_structures.json"
    all_structures = []
    for a in analyses:
        all_structures.extend(a.xml_structures)
    with open(structures_path, 'w') as f:
        json.dump(all_structures, f, indent=2, default=str)
    print(f"XML structures saved to: {structures_path}")
    
    # Print formatted report
    print_report(report, analyses)
    
    # Save text report
    text_report_path = ANALYSIS_DIR / "inlabs_analysis_report.txt"
    import io
    import contextlib
    
    # Redirect stdout to capture print_report output
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        print_report(report, analyses)
    
    with open(text_report_path, 'w') as f:
        f.write(buffer.getvalue())
    print(f"\nText report saved to: {text_report_path}")


if __name__ == "__main__":
    main()
