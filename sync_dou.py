#!/usr/bin/env python3
"""
GABI DOU Sync Script (v2.0)
---------------------------
Orchestrator for downloading and ingesting DOU data into MongoDB Atlas.
"""

import sys
import os
import logging
import argparse
from typing import List
from pymongo import UpdateOne
from src.backend.core.config import settings
from src.backend.data.db import MongoDB
from src.backend.ingest.downloader import DouDownloader
from src.backend.ingest.dou_processor import DouProcessor
from src.backend.data.models.document import DouDocument

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def ingest_documents(documents: List[DouDocument]):
    """Bulk upsert documents to MongoDB."""
    if not documents:
        return

    db = MongoDB.get_db()
    collection = db["documents"]
    
    operations = []
    for doc in documents:
        # Convert Pydantic model to dict, exclude None for cleaner DB
        doc_dict = doc.model_dump(by_alias=True, exclude_none=True)
        
        operations.append(
            UpdateOne(
                {"_id": doc.id},
                {"$set": doc_dict},
                upsert=True
            )
        )
    
    if operations:
        try:
            result = collection.bulk_write(operations)
            logger.info(f"Upserted {result.upserted_count + result.modified_count} documents (Matched: {result.matched_count})")
        except Exception as e:
            logger.error(f"Bulk write failed: {e}")

def main():
    parser = argparse.ArgumentParser(description="GABI DOU Sync")
    parser.add_argument("--year", type=int, default=2002, help="Year to sync")
    parser.add_argument("--month", type=int, help="Specific month to sync (optional)")
    args = parser.parse_args()

    logger.info(f"Starting GABI DOU Sync for {args.year}")
    
    # Initialize components
    MongoDB.connect()
    downloader = DouDownloader()
    processor = DouProcessor()
    
    # Determine months to process
    months = [args.month] if args.month else range(1, 13)
    
    for month in months:
        logger.info(f"Processing {args.year}-{month:02d}...")
        
        data = downloader.get_month_data(args.year, month)
        if not data:
            logger.warning(f"No data found for {args.year}-{month:02d}")
            continue
            
        folder_id = data["folder_id"]
        files = data["files"]
        
        logger.info(f"Found {len(files)} files for {args.year}-{month:02d}")
        
        for filename in files:
            if not filename.lower().endswith(".zip"):
                continue
                
            logger.info(f"Downloading {filename}...")
            zip_content = downloader.download_file(str(folder_id), filename)
            
            if not zip_content:
                logger.error(f"Failed to download {filename}")
                continue
                
            logger.info(f"Processing {filename}...")
            documents = processor.process_zip(zip_content, filename)
            
            logger.info(f"Extracted {len(documents)} documents from {filename}")
            ingest_documents(documents)

    logger.info("Sync complete.")

if __name__ == "__main__":
    main()
