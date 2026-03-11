#!/usr/bin/env python3
"""
GABI DOU Raw Downloader
-----------------------
Downloads raw DOU ZIP files and organizes them locally for manual transfer/import.
Can optionally extract the ZIPs into folders.

Usage:
    python ops/download_local.py --year 2002 --extract
"""

import sys
import os
import logging
import argparse
import zipfile
from pathlib import Path
from src.backend.ingest.downloader import DouDownloader

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Download raw DOU data locally")
    parser.add_argument("--year", type=int, default=2002, help="Year to download")
    parser.add_argument("--month", type=int, help="Specific month (optional)")
    parser.add_argument("--output-dir", type=str, default="ops/data/raw_export", help="Output directory")
    parser.add_argument("--extract", action="store_true", help="Extract ZIPs into folders")
    args = parser.parse_args()

    base_path = Path(args.output_dir)
    base_path.mkdir(parents=True, exist_ok=True)
    
    downloader = DouDownloader()
    months = [args.month] if args.month else range(1, 13)
    
    logger.info(f"Starting Local Download for {args.year} -> {base_path}")

    for month in months:
        month_str = f"{args.year}-{month:02d}"
        logger.info(f"Checking {month_str}...")
        
        data = downloader.get_month_data(args.year, month)
        if not data:
            logger.warning(f"No data found for {month_str}")
            continue
            
        folder_id = data["folder_id"]
        files = data["files"]
        
        # Create month directory
        month_dir = base_path / str(args.year) / f"{month:02d}"
        month_dir.mkdir(parents=True, exist_ok=True)
        
        for filename in files:
            if not filename.lower().endswith(".zip"):
                continue
                
            file_path = month_dir / filename
            
            # Skip if already exists
            if file_path.exists():
                logger.info(f"  Skipping {filename} (already exists)")
            else:
                logger.info(f"  Downloading {filename}...")
                content = downloader.download_file(str(folder_id), filename)
                if content:
                    with open(file_path, "wb") as f:
                        f.write(content)
                else:
                    logger.error(f"  Failed to download {filename}")
                    continue

            # Extract if requested
            if args.extract:
                extract_dir = month_dir / filename.replace('.zip', '')
                if not extract_dir.exists():
                    logger.info(f"    Extracting to {extract_dir}...")
                    try:
                        with zipfile.ZipFile(file_path, 'r') as z:
                            z.extractall(extract_dir)
                    except Exception as e:
                        logger.error(f"    Extraction failed: {e}")

    logger.info(f"\nDownload complete!")
    logger.info(f"Files are located in: {base_path.resolve()}")
    if args.extract:
        logger.info("Files have been unzipped into corresponding folders.")

if __name__ == "__main__":
    main()
