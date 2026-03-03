#!/usr/bin/env python3
"""
Detailed XML structure analysis for INLabs DOU files.
Extracts and documents the complete XML schema.
"""
from __future__ import annotations

import os
import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from dataclasses import dataclass, field
from collections import defaultdict
import re

DOWNLOAD_DIR = Path("downloads")
ANALYSIS_DIR = Path("analysis")


def extract_full_xml_structure(xml_content: bytes, filename: str) -> dict:
    """Extract detailed XML structure with recursive tag analysis."""
    try:
        root = ET.fromstring(xml_content)
        
        def analyze_element(elem, depth=0):
            tag_name = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            result = {
                "tag": tag_name,
                "depth": depth,
                "attributes": dict(elem.attrib),
                "text_preview": (elem.text or "")[:200].strip() if elem.text else "",
                "tail_preview": (elem.tail or "")[:100].strip() if elem.tail else "",
                "children": []
            }
            
            # Limit recursion for very deep structures
            if depth < 10:
                for child in elem:
                    result["children"].append(analyze_element(child, depth + 1))
            
            return result
        
        structure = {
            "filename": filename,
            "root_tag": root.tag.split('}')[-1] if '}' in root.tag else root.tag,
            "tree": analyze_element(root),
            "is_valid": True
        }
        
        # Extract all unique paths
        paths = set()
        def collect_paths(elem, current_path=""):
            tag_name = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            new_path = f"{current_path}/{tag_name}" if current_path else tag_name
            paths.add(new_path)
            for child in elem:
                collect_paths(child, new_path)
        
        collect_paths(root)
        structure["all_paths"] = sorted(list(paths))
        
        return structure
        
    except Exception as e:
        return {
            "filename": filename,
            "error": str(e),
            "is_valid": False
        }


def analyze_naming_patterns(filenames: list[str]) -> dict:
    """Analyze XML file naming conventions."""
    patterns = {
        "standard_format": 0,  # XXX_YYYYMMDD_NNNNNNN.xml
        "with_suffix": 0,      # XXX_YYYYMMDD_NNNNNNN-N.xml
        "other": 0
    }
    
    details = []
    
    for filename in filenames:
        # Remove extension
        name = filename.replace('.xml', '')
        
        # Check pattern
        standard_match = re.match(r'^(\d+)_(\d{8})_(\d+)\.xml$', filename)
        suffix_match = re.match(r'^(\d+)_(\d{8})_(\d+)-(\d+)\.xml$', filename)
        
        if standard_match:
            patterns["standard_format"] += 1
            details.append({
                "filename": filename,
                "type": "standard",
                "section_code": standard_match.group(1),
                "date": standard_match.group(2),
                "document_id": standard_match.group(3)
            })
        elif suffix_match:
            patterns["with_suffix"] += 1
            details.append({
                "filename": filename,
                "type": "with_suffix",
                "section_code": suffix_match.group(1),
                "date": suffix_match.group(2),
                "document_id": suffix_match.group(3),
                "suffix": suffix_match.group(4)
            })
        else:
            patterns["other"] += 1
            details.append({
                "filename": filename,
                "type": "other"
            })
    
    return {
        "counts": patterns,
        "details": details
    }


def extract_sample_xmls():
    """Extract sample XML files from downloaded ZIPs for detailed analysis."""
    samples = []
    
    for date_dir in DOWNLOAD_DIR.iterdir():
        if not date_dir.is_dir():
            continue
            
        for zip_file in date_dir.glob("*.zip"):
            print(f"Processing {zip_file.name}...")
            
            try:
                with zipfile.ZipFile(zip_file, 'r') as zf:
                    xml_files = [f for f in zf.namelist() if f.endswith('.xml')]
                    
                    # Sample different types of files
                    sampled = 0
                    for xml_name in xml_files:
                        # Sample files with different naming patterns
                        if sampled >= 10:  # Max 10 per ZIP
                            break
                            
                        try:
                            content = zf.read(xml_name)
                            structure = extract_full_xml_structure(content, xml_name)
                            
                            # Also save raw content for first few samples
                            if sampled < 3:
                                raw_path = ANALYSIS_DIR / "samples" / f"{zip_file.stem}_{xml_name}"
                                raw_path.parent.mkdir(parents=True, exist_ok=True)
                                with open(raw_path, 'wb') as f:
                                    f.write(content)
                                structure["raw_saved_to"] = str(raw_path)
                            
                            samples.append(structure)
                            sampled += 1
                            
                        except Exception as e:
                            print(f"  Error processing {xml_name}: {e}")
                            
            except Exception as e:
                print(f"  Error opening {zip_file}: {e}")
    
    return samples


def analyze_all_downloads():
    """Comprehensive analysis of all downloaded ZIP files."""
    all_xml_files = []
    all_image_files = []
    section_stats = defaultdict(lambda: {"xml_count": 0, "image_count": 0, "zip_count": 0, "sizes": []})
    
    for date_dir in DOWNLOAD_DIR.iterdir():
        if not date_dir.is_dir():
            continue
            
        for zip_file in date_dir.glob("*.zip"):
            # Extract section from filename
            section_match = re.search(r'-(DO\dE?)\.zip$', zip_file.name)
            section = section_match.group(1) if section_match else "unknown"
            
            try:
                with zipfile.ZipFile(zip_file, 'r') as zf:
                    for info in zf.infolist():
                        if info.filename.endswith('.xml'):
                            all_xml_files.append({
                                "name": info.filename,
                                "size": info.file_size,
                                "section": section,
                                "date": date_dir.name
                            })
                            section_stats[section]["xml_count"] += 1
                        elif any(info.filename.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                            all_image_files.append({
                                "name": info.filename,
                                "size": info.file_size,
                                "section": section,
                                "date": date_dir.name
                            })
                            section_stats[section]["image_count"] += 1
                    
                    section_stats[section]["zip_count"] += 1
                    section_stats[section]["sizes"].append(zip_file.stat().st_size)
                    
            except Exception as e:
                print(f"Error analyzing {zip_file}: {e}")
    
    # Calculate statistics
    stats = {
        "total_xml_files": len(all_xml_files),
        "total_image_files": len(all_image_files),
        "xml_size_stats": calculate_size_stats([f["size"] for f in all_xml_files]),
        "image_size_stats": calculate_size_stats([f["size"] for f in all_image_files]),
        "by_section": {},
        "naming_analysis": analyze_naming_patterns([f["name"] for f in all_xml_files])
    }
    
    for section, data in section_stats.items():
        stats["by_section"][section] = {
            "zip_count": data["zip_count"],
            "xml_count": data["xml_count"],
            "image_count": data["image_count"],
            "avg_zip_size_mb": sum(data["sizes"]) / len(data["sizes"]) / (1024*1024) if data["sizes"] else 0
        }
    
    return stats, all_xml_files, all_image_files


def calculate_size_stats(sizes: list[int]) -> dict:
    """Calculate size statistics."""
    if not sizes:
        return {"count": 0, "avg_bytes": 0, "min_bytes": 0, "max_bytes": 0}
    
    sizes.sort()
    n = len(sizes)
    
    return {
        "count": n,
        "avg_bytes": sum(sizes) / n,
        "avg_kb": sum(sizes) / n / 1024,
        "min_bytes": min(sizes),
        "max_bytes": max(sizes),
        "median_bytes": sizes[n // 2],
        "p95_bytes": sizes[int(n * 0.95)] if n > 20 else sizes[-1]
    }


def check_pdf_signatures():
    """Check if PDF signature files are included in the ZIPs."""
    pdf_files = []
    signature_files = []
    
    for date_dir in DOWNLOAD_DIR.iterdir():
        if not date_dir.is_dir():
            continue
            
        for zip_file in date_dir.glob("*.zip"):
            try:
                with zipfile.ZipFile(zip_file, 'r') as zf:
                    for name in zf.namelist():
                        lower_name = name.lower()
                        if lower_name.endswith('.pdf'):
                            pdf_files.append({
                                "zip": zip_file.name,
                                "file": name
                            })
                        elif any(sig in lower_name for sig in ['assinatura', 'signature', 'pades', 'cades', '.p7s', '.sig']):
                            signature_files.append({
                                "zip": zip_file.name,
                                "file": name
                            })
            except Exception as e:
                print(f"Error checking {zip_file}: {e}")
    
    return {
        "pdf_files_found": pdf_files,
        "signature_files_found": signature_files,
        "has_pdf": len(pdf_files) > 0,
        "has_signatures": len(signature_files) > 0
    }


def main():
    """Run detailed analysis."""
    ANALYSIS_DIR.mkdir(exist_ok=True)
    
    print("="*80)
    print("DETAILED INLabs XML Structure Analysis")
    print("="*80)
    
    # 1. Extract and analyze XML structures
    print("\n1. Extracting sample XML structures...")
    samples = extract_sample_xmls()
    
    samples_path = ANALYSIS_DIR / "detailed_xml_structures.json"
    with open(samples_path, 'w') as f:
        json.dump(samples, f, indent=2, default=str)
    print(f"   Saved to: {samples_path}")
    
    # 2. Analyze all downloads
    print("\n2. Analyzing all downloaded files...")
    stats, xml_files, image_files = analyze_all_downloads()
    
    stats_path = ANALYSIS_DIR / "comprehensive_stats.json"
    with open(stats_path, 'w') as f:
        json.dump(stats, f, indent=2, default=str)
    print(f"   Saved to: {stats_path}")
    
    # 3. Check for PDF signatures
    print("\n3. Checking for PDF signatures...")
    pdf_info = check_pdf_signatures()
    
    pdf_path = ANALYSIS_DIR / "pdf_signatures.json"
    with open(pdf_path, 'w') as f:
        json.dump(pdf_info, f, indent=2, default=str)
    print(f"   Saved to: {pdf_path}")
    
    # Print summary
    print("\n" + "="*80)
    print("ANALYSIS SUMMARY")
    print("="*80)
    
    print(f"\nTotal XML files analyzed: {stats['total_xml_files']}")
    print(f"Total image files analyzed: {stats['total_image_files']}")
    
    print("\nXML Size Statistics:")
    xml_stats = stats['xml_size_stats']
    print(f"  Count: {xml_stats['count']}")
    print(f"  Average: {xml_stats['avg_kb']:.2f} KB")
    print(f"  Min: {xml_stats['min_bytes']/1024:.2f} KB")
    print(f"  Max: {xml_stats['max_bytes']/1024:.2f} KB")
    print(f"  Median: {xml_stats['median_bytes']/1024:.2f} KB")
    
    print("\nImage Size Statistics:")
    img_stats = stats['image_size_stats']
    print(f"  Count: {img_stats['count']}")
    print(f"  Average: {img_stats['avg_kb']:.2f} KB")
    print(f"  Min: {img_stats['min_bytes']/1024:.2f} KB")
    print(f"  Max: {img_stats['max_bytes']/1024:.2f} KB")
    
    print("\nBy Section:")
    for section, data in sorted(stats['by_section'].items()):
        print(f"  {section}:")
        print(f"    ZIPs: {data['zip_count']}")
        print(f"    XMLs: {data['xml_count']}")
        print(f"    Images: {data['image_count']}")
        print(f"    Avg ZIP size: {data['avg_zip_size_mb']:.2f} MB")
    
    print("\nNaming Patterns:")
    naming = stats['naming_analysis']['counts']
    print(f"  Standard format (XXX_YYYYMMDD_NNNNNNN.xml): {naming['standard_format']}")
    print(f"  With suffix (-N.xml): {naming['with_suffix']}")
    print(f"  Other patterns: {naming['other']}")
    
    print("\nPDF Signatures:")
    print(f"  PDF files found: {len(pdf_info['pdf_files_found'])}")
    print(f"  Signature files found: {len(pdf_info['signature_files_found'])}")
    
    # Save full summary
    summary = {
        "stats": stats,
        "pdf_signatures": pdf_info,
        "sample_structures": samples[:5]  # First 5 samples
    }
    
    summary_path = ANALYSIS_DIR / "full_analysis_summary.json"
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nFull summary saved to: {summary_path}")


if __name__ == "__main__":
    main()
