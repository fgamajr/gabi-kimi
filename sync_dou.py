#!/usr/bin/env python3
"""
GABI DOU Sync Script (v2.0)
---------------------------
Orchestrator for downloading and ingesting DOU data into MongoDB Atlas.
"""

import sys
import os
import shutil
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
            
    # Cleanup Logic:
    # 1. We keep the raw ZIPs in iCloud (Source of Truth)
    # 2. We DELETE the extracted XMLs from iCloud/Linux to save space/inodes
    pass

def archive_and_cleanup(zip_path: str, extract_base: str, zip_filename: str):
    """
    Archive ZIP to iCloud (verified copy), then delete from VM.
    If archival fails, ZIP stays on VM. Extracted XMLs always deleted.
    """
    icloud_base = settings.ICLOUD_DATA_PATH

    # Always clean extracted XMLs first (regenerable from ZIP)
    if extract_base and zip_filename:
        zip_name_no_ext = os.path.splitext(zip_filename)[0]
        target_dir = os.path.join(extract_base, zip_name_no_ext)
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir, ignore_errors=True)
            logger.info(f"Cleaned extracted XMLs: {target_dir}")

    # If no iCloud path configured, just delete the ZIP too
    if not icloud_base:
        if zip_path and os.path.exists(zip_path):
            os.unlink(zip_path)
        return

    if not zip_path or not os.path.exists(zip_path):
        return

    icloud_dest = os.path.join(icloud_base, "raw", zip_filename)

    try:
        os.makedirs(os.path.dirname(icloud_dest), exist_ok=True)
        shutil.copy2(zip_path, icloud_dest)

        # Verify: size match
        src_size = os.path.getsize(zip_path)
        dst_size = os.path.getsize(icloud_dest)
        if src_size != dst_size:
            raise IOError(f"Size mismatch: source={src_size} dest={dst_size}")

        # Verified — safe to delete from VM
        os.unlink(zip_path)
        logger.info(f"Archived {zip_filename} to iCloud ({src_size} bytes), deleted from VM")

    except Exception as e:
        logger.warning(f"iCloud archive failed for {zip_filename}: {e}")
        logger.warning(f"ZIP kept at {zip_path} for manual retry")


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

            # Disk space pre-check
            free_gb = shutil.disk_usage("/tmp").free / (1024**3)
            if free_gb < 2:
                logger.error(f"VM disk critical: {free_gb:.1f}GB free. Stopping.")
                return

            logger.info(f"Downloading {filename}...")

            # Download to LOCAL temp (fast), then archive to iCloud after ingestion
            tmp_base = settings.PIPELINE_TMP
            save_path = os.path.join(tmp_base, "raw", filename)
            extract_to = os.path.join(tmp_base, "extracted")

            zip_content = downloader.download_file(str(folder_id), filename, save_path=save_path)

            if not zip_content:
                logger.error(f"Failed to download {filename}")
                continue

            logger.info(f"Processing {filename}...")
            documents = processor.process_zip(zip_content, filename, extract_to=extract_to)

            logger.info(f"Extracted {len(documents)} documents from {filename}")
            ingest_documents(documents)

            # Archive ZIP to iCloud (verified) + cleanup extracted XMLs
            archive_and_cleanup(save_path, extract_to, filename)

    # Incremental ES indexing — picks up only new docs via cursor
    logger.info("Running ES incremental sync...")
    try:
        from src.backend.ingest.es_indexer import ESClient, _run_sync, _DEFAULT_CURSOR_PATH
        _run_sync(reset_cursor=False, recreate_index=False, batch_size=2000, cursor_path=_DEFAULT_CURSOR_PATH)
    except Exception as e:
        logger.warning(f"ES sync failed (non-fatal): {e}")

    logger.info("Sync complete.")

if __name__ == "__main__":
    main()
