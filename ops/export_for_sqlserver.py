#!/usr/bin/env python3
"""
GABI DOU Exporter for SQL Server (v1.0)
---------------------------------------
Exports DOU data from the ingest pipeline into CSV/TSV format compatible with
SQL Server Import Wizard or Bulk Insert.

Usage:
    python ops/export_for_sqlserver.py --year 2002 --output dou_2002.csv
"""

import sys
import os
import csv
import json
import logging
import argparse
from typing import List, Dict, Any
from datetime import date, datetime

from src.backend.ingest.downloader import DouDownloader
from src.backend.ingest.dou_processor import DouProcessor
from src.backend.data.models.document import DouDocument

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def clean_text(text: str) -> str:
    """Clean text for CSV export."""
    if not text:
        return ""
    # Replace newlines with spaces or keep them if quoted correctly
    # For SQL Server import, replacing newlines with \n or just spaces is safer
    return text.replace('\0', '') # Remove null bytes

def serialize_json(obj: Any) -> str:
    """Serialize object to JSON string."""
    if not obj:
        return "{}"
    if hasattr(obj, 'model_dump'):
        return json.dumps(obj.model_dump(exclude_none=True), ensure_ascii=False)
    if isinstance(obj, (list, dict)):
        return json.dumps(obj, ensure_ascii=False)
    return "{}"

def write_batch(writer, documents: List[DouDocument]):
    """Write a batch of documents to the CSV writer."""
    for doc in documents:
        row = [
            doc.id,
            doc.source_id,
            doc.pub_date.strftime("%Y-%m-%d"),
            doc.section,
            doc.edition or "",
            doc.page or "",
            doc.art_type or "",
            doc.orgao or "",
            clean_text(doc.identifica),
            clean_text(doc.ementa),
            clean_text(doc.texto),
            clean_text(doc.data_text),
            serialize_json(doc.metadata),
            serialize_json(doc.enrichment),
            serialize_json(doc.references),
            serialize_json(doc.images)
        ]
        writer.writerow(row)

def main():
    parser = argparse.ArgumentParser(description="Export DOU data for SQL Server")
    parser.add_argument("--year", type=int, default=2002, help="Year to export")
    parser.add_argument("--month", type=int, help="Specific month (optional)")
    parser.add_argument("--output", type=str, default="dou_export.csv", help="Output CSV file")
    args = parser.parse_args()

    logger.info(f"Starting Export for {args.year} -> {args.output}")

    # CSV Headers matching SQL Schema
    headers = [
        "Id", "SourceId", "PubDate", "Section", "Edition", "Page", "ArtType", 
        "Orgao", "Identifica", "Ementa", "Texto", "DataText", 
        "MetadataJson", "EnrichmentJson", "ReferencesJson", "ImagesJson"
    ]

    # Open CSV file
    with open(args.output, 'w', newline='', encoding='utf-8-sig') as csvfile:
        # Use tab delimiter to avoid issues with commas in text
        writer = csv.writer(csvfile, delimiter='\t', quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)

        downloader = DouDownloader()
        processor = DouProcessor()
        
        months = [args.month] if args.month else range(1, 13)
        total_exported = 0

        for month in months:
            logger.info(f"Processing {args.year}-{month:02d}...")
            
            data = downloader.get_month_data(args.year, month)
            if not data:
                logger.warning(f"No data found for {args.year}-{month:02d}")
                continue
                
            folder_id = data["folder_id"]
            files = data["files"]
            
            for filename in files:
                if not filename.lower().endswith(".zip"):
                    continue
                    
                # Download (or check cache ideally)
                zip_content = downloader.download_file(str(folder_id), filename)
                if not zip_content:
                    continue
                    
                documents = processor.process_zip(zip_content, filename)
                if documents:
                    write_batch(writer, documents)
                    total_exported += len(documents)
                    logger.info(f"  Exported {len(documents)} docs from {filename}")

    logger.info(f"Export complete. Total records: {total_exported}")
    logger.info(f"File saved to: {os.path.abspath(args.output)}")

if __name__ == "__main__":
    main()
