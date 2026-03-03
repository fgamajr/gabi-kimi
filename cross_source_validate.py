#!/usr/bin/env python3
"""
Sample Cross-Source Validation for DOU Data

This script demonstrates the cross-source validation framework
by comparing available data sources for a test date.
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from validation.cross_source_validator import (
    CrossSourceValidator,
    DiscrepancyType,
    FingerprintEngine,
    ReconciliationStrategy,
    SourceDocument,
    SourceType,
    load_from_extraction_results,
    write_validation_report,
)


# ============================================================================
# INLabs Data Loader
# ============================================================================

def parse_inlabs_xml(xml_content: str) -> list[dict[str, Any]]:
    """Parse INLabs XML content to extract documents."""
    documents = []
    
    # Find all article elements
    article_pattern = r'<article[^>]*>(.*?)</article>'
    articles = re.findall(article_pattern, xml_content, re.DOTALL)
    
    for article in articles:
        doc = {}
        
        # Extract fields using regex
        fields = {
            'title': r'<title[^>]*>(.*?)</title>',
            'identifica': r'<identifica[^>]*>(.*?)</identifica>',
            'data': r'<data[^>]*>(.*?)</data>',
            'ementa': r'<ementa[^>]*>(.*?)</ementa>',
            'texto': r'<texto[^>]*>(.*?)</texto>',
            'autoridade': r'<autoridade[^>]*>(.*?)</autoridade>',
            'orgao': r'<orgao[^>]*>(.*?)</orgao>',
            'secao': r'<secao[^>]*>(.*?)</secao>',
            'edicao': r'<edicao[^>]*>(.*?)</edicao>',
            'pagina': r'<pagina[^>]*>(.*?)</pagina>',
        }
        
        for field, pattern in fields.items():
            match = re.search(pattern, article, re.DOTALL | re.IGNORECASE)
            if match:
                # Clean CDATA and HTML tags
                value = match.group(1)
                value = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', value, flags=re.DOTALL)
                value = re.sub(r'<[^>]+>', '', value)
                value = value.strip()
                doc[field] = value
        
        if doc.get('title') or doc.get('identifica'):
            documents.append(doc)
    
    return documents


def load_inlabs_from_zip(zip_path: Path) -> list[SourceDocument]:
    """Load documents from INLabs ZIP file."""
    documents = []
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for name in zf.namelist():
                if name.endswith('.xml'):
                    content = zf.read(name).decode('utf-8', errors='ignore')
                    xml_docs = parse_inlabs_xml(content)
                    
                    for xml_doc in xml_docs:
                        # Create fingerprint
                        doc_type = FingerprintEngine.normalize_doc_type(
                            xml_doc.get('identifica', xml_doc.get('title', ''))
                        )
                        title = xml_doc.get('identifica') or xml_doc.get('title', '')
                        
                        # Extract number and year
                        doc_number = FingerprintEngine.extract_doc_number(title)
                        doc_year = FingerprintEngine.extract_year(title)
                        
                        # Parse date
                        pub_date = xml_doc.get('data', '')
                        if pub_date:
                            # Convert from DD/MM/YYYY to ISO
                            try:
                                dt = datetime.strptime(pub_date, '%d/%m/%Y')
                                pub_date = dt.strftime('%Y-%m-%d')
                            except ValueError:
                                pass
                        
                        # Body text
                        body = xml_doc.get('texto', '')
                        if xml_doc.get('ementa'):
                            body = f"Ementa: {xml_doc['ementa']}\n\n{body}"
                        
                        fingerprint = FingerprintEngine.from_extraction_result(
                            SourceType.INLABS,
                            {
                                "document": {
                                    "document_type": doc_type,
                                    "document_number": doc_number,
                                    "document_year": doc_year,
                                    "title": title,
                                    "body_text": body,
                                    "issuing_organ": xml_doc.get('orgao', ''),
                                    "issuing_authority": xml_doc.get('autoridade', ''),
                                },
                                "publication_issue": {
                                    "publication_date": pub_date,
                                    "edition_number": xml_doc.get('edicao', ''),
                                    "edition_section": xml_doc.get('secao', ''),
                                    "page_number": xml_doc.get('pagina', ''),
                                }
                            }
                        )
                        
                        # Track fields
                        fields_present = {'document_type', 'title', 'body_text'}
                        if doc_number:
                            fields_present.add('document_number')
                        if doc_year:
                            fields_present.add('document_year')
                        if xml_doc.get('orgao'):
                            fields_present.add('issuing_organ')
                        
                        doc = SourceDocument(
                            source=SourceType.INLABS,
                            fingerprint=fingerprint,
                            raw_data={
                                "document": {
                                    "document_type": doc_type,
                                    "document_number": doc_number,
                                    "document_year": doc_year,
                                    "title": title,
                                    "body_text": body,
                                    "issuing_organ": xml_doc.get('orgao'),
                                    "issuing_authority": xml_doc.get('autoridade'),
                                },
                                "publication_issue": {
                                    "publication_date": pub_date,
                                    "edition_number": xml_doc.get('edicao'),
                                    "edition_section": xml_doc.get('secao'),
                                }
                            },
                            source_url=f"inlabs://{name}",
                            extracted_at=datetime.now(),
                            extraction_version="1.0",
                            fields_present=fields_present,
                            fields_missing=set(),
                        )
                        documents.append(doc)
    
    except Exception as e:
        print(f"Warning: Failed to load INLabs ZIP {zip_path}: {e}")
    
    return documents


# ============================================================================
# Web/LeituraJornal Loader
# ============================================================================

def load_web_dou_data(html_dir: Path) -> list[SourceDocument]:
    """Load documents from web-scraped HTML data."""
    documents = []
    
    # Use existing extraction infrastructure
    from validation.rules import load_rules
    from validation.extractor import ExtractionHarness
    
    rules = load_rules("sources_v3.yaml", source_id="dou")
    harness = ExtractionHarness(rules)
    
    for html_file in sorted(html_dir.glob("*.html")):
        try:
            result = harness.run_file(html_file)
            
            for doc_data in result.parsed.get("documents", []):
                fingerprint = FingerprintEngine.from_extraction_result(
                    SourceType.LEITURAJORNAL, doc_data
                )
                
                raw_doc = doc_data.get("document", {})
                fields_present = set()
                for field in ["document_type", "document_number", "document_year", 
                             "title", "body_text", "issuing_organ", "issuing_authority"]:
                    if raw_doc.get(field):
                        fields_present.add(field)
                
                doc = SourceDocument(
                    source=SourceType.LEITURAJORNAL,
                    fingerprint=fingerprint,
                    raw_data=doc_data,
                    source_url=result.page_url or str(html_file),
                    extracted_at=datetime.fromtimestamp(html_file.stat().st_mtime),
                    extraction_version="1.0",
                    fields_present=fields_present,
                    fields_missing=set(),
                )
                documents.append(doc)
        
        except Exception as e:
            print(f"Warning: Failed to process {html_file}: {e}")
    
    return documents


# ============================================================================
# Simulated Second Source Generator
# ============================================================================

def simulate_alternative_source(
    base_documents: list[SourceDocument], 
    source_type: SourceType,
    completeness: float = 0.95,
    noise_rate: float = 0.02
) -> list[SourceDocument]:
    """
    Simulate an alternative source for testing purposes.
    
    This creates a synthetic second source by:
    - Removing random documents (simulating incompleteness)
    - Adding slight variations to metadata (simulating extraction noise)
    """
    import random
    import copy
    
    simulated = []
    random.seed(42)  # Reproducible
    
    for doc in base_documents:
        # Skip some documents based on completeness
        if random.random() > completeness:
            continue
        
        # Deep copy the document
        new_doc = copy.deepcopy(doc)
        new_doc.source = source_type
        
        # Add noise to some documents
        if random.random() < noise_rate:
            # Slightly alter the title
            if new_doc.fingerprint.title_normalized:
                # Add/remove a word
                words = new_doc.fingerprint.title_normalized.split()
                if words and random.random() < 0.5:
                    words.pop(random.randrange(len(words)))
                new_doc.fingerprint.title_normalized = " ".join(words)
        
        simulated.append(new_doc)
    
    return simulated


# ============================================================================
# Main Validation Runner
# ============================================================================

def run_validation(
    data_paths: dict[SourceType, Path],
    out_dir: Path,
    reconciliation_strategy: ReconciliationStrategy = ReconciliationStrategy.SOURCE_HIERARCHY,
    simulate_secondary: bool = False,
) -> dict[str, Any]:
    """Run cross-source validation."""
    
    print("=" * 60)
    print("CROSS-SOURCE VALIDATION FOR DOU DATA")
    print("=" * 60)
    
    documents_by_source: dict[SourceType, list[SourceDocument]] = {}
    
    # Load data from each source
    for source_type, path in data_paths.items():
        print(f"\n📥 Loading {source_type.value} from {path}...")
        
        if source_type == SourceType.INLABS and path.suffix == '.zip':
            docs = load_inlabs_from_zip(path)
        elif source_type == SourceType.LEITURAJORNAL and path.is_dir():
            docs = load_web_dou_data(path)
        elif source_type == SourceType.WEB_DOU and path.is_dir():
            docs = load_web_dou_data(path)
        else:
            # Try to load from extraction results
            docs = load_from_extraction_results(source_type, path)
        
        documents_by_source[source_type] = docs
        print(f"   ✓ Loaded {len(docs)} documents")
    
    # If requested, simulate a secondary source for testing
    if simulate_secondary and len(documents_by_source) == 1:
        base_source = list(documents_by_source.keys())[0]
        base_docs = documents_by_source[base_source]
        
        print(f"\n🎲 Simulating alternative source (INLABS)...")
        simulated = simulate_alternative_source(
            base_docs, SourceType.INLABS, completeness=0.92, noise_rate=0.03
        )
        documents_by_source[SourceType.INLABS] = simulated
        print(f"   ✓ Simulated {len(simulated)} documents (92% completeness)")
    
    # Run validation
    print("\n🔍 Running cross-source validation...")
    validator = CrossSourceValidator(
        reconciliation_strategy=reconciliation_strategy,
        source_hierarchy=[SourceType.INLABS, SourceType.LEITURAJORNAL, SourceType.WEB_DOU]
    )
    
    report = validator.validate(documents_by_source)
    
    # Write report
    print(f"\n📝 Writing validation report to {out_dir}...")
    write_validation_report(report, out_dir)
    
    # Print summary
    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)
    
    print(f"\n📊 Documents by Source:")
    for source, docs in documents_by_source.items():
        metrics = report.per_source_metrics.get(source)
        if metrics:
            print(f"   • {source.value:20s}: {len(docs):4d} docs (completeness: {metrics.completeness_score():.1%})")
    
    print(f"\n🔗 Cross-Source Matching:")
    print(f"   • Perfect matches:   {len(report.cross_match.perfect_matches)}")
    print(f"   • Probable matches:  {len(report.cross_match.probable_matches)}")
    print(f"   • Unique per source:")
    for source, docs in report.cross_match.unique_to_source.items():
        print(f"     - {source.value}: {len(docs)}")
    
    print(f"\n⚠️  Discrepancies Found: {len(report.discrepancies)}")
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for d in report.discrepancies:
        by_type[d.type.value] = by_type.get(d.type.value, 0) + 1
        by_severity[d.severity] = by_severity.get(d.severity, 0) + 1
    
    for dtype, count in sorted(by_type.items()):
        print(f"   • {dtype}: {count}")
    
    print(f"\n📈 Overall Quality:")
    print(f"   • Completeness:    {report.overall_completeness:.1%}")
    print(f"   • Consensus Rate:  {report.consensus_rate:.1%}")
    print(f"   • Critical Issues: {by_severity.get('critical', 0)}")
    print(f"   • Warnings:        {by_severity.get('warning', 0)}")
    
    # Sample reconciliations
    print(f"\n🔄 Sample Reconciliations (first 3 perfect matches):")
    for i, match_group in enumerate(report.cross_match.perfect_matches[:3], 1):
        authoritative, meta = validator.reconciler.reconcile(match_group)
        print(f"\n   Match {i}:")
        print(f"   • Sources: {', '.join(d.source.value for d in match_group)}")
        print(f"   • Selected: {authoritative.source.value} ({meta['reconciliation_strategy']})")
        print(f"   • Document: {authoritative.fingerprint.title_normalized[:60]}...")
    
    print(f"\n✅ Validation complete. Report saved to: {out_dir}/")
    
    return report.to_dict()


def main():
    parser = argparse.ArgumentParser(description="Cross-source validation for DOU data")
    parser.add_argument(
        "--inlabs-zip",
        type=Path,
        help="Path to INLabs ZIP file"
    )
    parser.add_argument(
        "--web-dir",
        type=Path,
        help="Path to web-scraped HTML directory"
    )
    parser.add_argument(
        "--parsed-dir",
        type=Path,
        help="Path to parsed JSON directory"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("cross_validation_report"),
        help="Output directory for validation report"
    )
    parser.add_argument(
        "--reconciliation",
        choices=["hierarchy", "complete", "recent", "consensus"],
        default="hierarchy",
        help="Reconciliation strategy"
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Simulate a secondary source for testing"
    )
    
    args = parser.parse_args()
    
    # Map reconciliation strategy
    strategy_map = {
        "hierarchy": ReconciliationStrategy.SOURCE_HIERARCHY,
        "complete": ReconciliationStrategy.MOST_COMPLETE,
        "recent": ReconciliationStrategy.MOST_RECENT,
        "consensus": ReconciliationStrategy.CONSENSUS,
    }
    
    # Build data paths
    data_paths: dict[SourceType, Path] = {}
    
    if args.inlabs_zip:
        data_paths[SourceType.INLABS] = args.inlabs_zip
    if args.web_dir:
        data_paths[SourceType.LEITURAJORNAL] = args.web_dir
    if args.parsed_dir:
        if SourceType.LEITURAJORNAL not in data_paths:
            data_paths[SourceType.LEITURAJORNAL] = args.parsed_dir
    
    # If no paths provided, use test data
    if not data_paths:
        print("No data paths provided, using available test data...")
        
        # Try to find test data
        test_data_dir = Path("data/phase0/2023-01-probe/2023-01-02")
        inlabs_zip = Path("data/phase0/inlabs-probe/2026-02-27-DO1.zip")
        
        if test_data_dir.exists():
            data_paths[SourceType.LEITURAJORNAL] = test_data_dir
            print(f"Using test data: {test_data_dir}")
        
        if inlabs_zip.exists():
            data_paths[SourceType.INLABS] = inlabs_zip
            print(f"Using INLabs data: {inlabs_zip}")
        
        if not data_paths:
            print("Error: No test data found. Please provide --web-dir or --inlabs-zip")
            return 1
    
    # Run validation
    result = run_validation(
        data_paths=data_paths,
        out_dir=args.out,
        reconciliation_strategy=strategy_map[args.reconciliation],
        simulate_secondary=args.simulate and len(data_paths) == 1,
    )
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
