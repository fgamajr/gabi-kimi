#!/usr/bin/env python3
"""
CLI script to create Elasticsearch index for GABI.
"""

import argparse
import sys

from elasticsearch import Elasticsearch


def create_index(host: str = "localhost", port: int = 9200, force: bool = False) -> int:
    """
    Create the gabi_documents Elasticsearch index.
    
    Args:
        host: Elasticsearch host
        port: Elasticsearch port
        force: If True, delete existing index before creating
        
    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        # Import here to avoid dependency issues if elasticsearch not installed
        from src.gabi.services.elasticsearch_setup import (
            INDEX_NAME,
            create_index as setup_index,
            delete_index,
        )
    except ImportError:
        # Try relative import when running from project root
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from src.gabi.services.elasticsearch_setup import (
            INDEX_NAME,
            create_index as setup_index,
            delete_index,
        )
    
    es = Elasticsearch([f"http://{host}:{port}"])
    
    if not es.ping():
        print(f"❌ Cannot connect to Elasticsearch at {host}:{port}", file=sys.stderr)
        return 1
    
    print(f"✓ Connected to Elasticsearch at {host}:{port}")
    
    if force and es.indices.exists(index=INDEX_NAME):
        print(f"⚠️  Force flag set, deleting existing index '{INDEX_NAME}'...")
        if not delete_index(es):
            print(f"❌ Failed to delete index '{INDEX_NAME}'", file=sys.stderr)
            return 1
        print(f"✓ Deleted index '{INDEX_NAME}'")
    
    if es.indices.exists(index=INDEX_NAME):
        print(f"✓ Index '{INDEX_NAME}' already exists (skipping)")
        return 0
    
    print(f"📦 Creating index '{INDEX_NAME}'...")
    
    if setup_index(es):
        print(f"✓ Index '{INDEX_NAME}' created successfully")
        return 0
    else:
        print(f"❌ Failed to create index '{INDEX_NAME}'", file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Create Elasticsearch index for GABI documents"
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Elasticsearch host (default: localhost)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9200,
        help="Elasticsearch port (default: 9200)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete existing index before creating"
    )
    
    args = parser.parse_args()
    sys.exit(create_index(args.host, args.port, args.force))


if __name__ == "__main__":
    main()
