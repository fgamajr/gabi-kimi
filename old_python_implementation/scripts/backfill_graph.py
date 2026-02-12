#!/usr/bin/env python3
"""Backfill graph database with existing documents.

This script processes existing documents from PostgreSQL and populates
the Neo4j graph database with their entities and relationships.

Usage:
    python scripts/backfill_graph.py --batch-size 100 --limit 1000
"""

import asyncio
import argparse
import logging
import sys
from datetime import datetime
from typing import Optional

# Add src to path
sys.path.insert(0, '/home/fgamajr/dev/gabi-kimi/src')

from gabi.db import get_session
from gabi.graphrag.pipeline import GraphConstructionPipeline
from gabi.models.chunk import DocumentChunk
from gabi.models.document import Document

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def backfill_documents(
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    batch_size: int = 100,
    limit: Optional[int] = None,
    offset: int = 0,
    source_filter: Optional[str] = None,
):
    """Backfill graph for existing documents.
    
    Args:
        neo4j_uri: Neo4j connection URI
        neo4j_user: Neo4j username
        neo4j_password: Neo4j password
        batch_size: Number of documents to process per batch
        limit: Maximum number of documents to process
        offset: Number of documents to skip
        source_filter: Filter by source_id
    """
    pipeline = GraphConstructionPipeline(
        neo4j_uri=neo4j_uri,
        neo4j_user=neo4j_user,
        neo4j_password=neo4j_password,
    )
    
    # Initialize schema
    logger.info("Initializing Neo4j schema...")
    await pipeline.initialize_schema()
    
    stats = {
        'processed': 0,
        'successful': 0,
        'failed': 0,
        'nodes_created': 0,
        'relationships_created': 0,
    }
    
    try:
        async with get_session() as session:
            # Build query
            query = """
                SELECT d.id, d.document_id, d.title, d.source_id, 
                       d.ingested_at, d.fingerprint
                FROM documents d
                WHERE d.is_deleted = false
            """
            
            if source_filter:
                query += f" AND d.source_id = '{source_filter}'"
            
            query += " ORDER BY d.ingested_at DESC"
            
            if limit:
                query += f" LIMIT {limit}"
            
            if offset:
                query += f" OFFSET {offset}"
            
            # Get documents
            result = await session.execute(query)
            documents = result.all()
            
            total = len(documents)
            logger.info(f"Found {total} documents to process")
            
            # Process in batches
            for i in range(0, len(documents), batch_size):
                batch = documents[i:i+batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(documents) + batch_size - 1) // batch_size
                
                logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} documents)")
                
                for doc_row in batch:
                    try:
                        # Create document object
                        doc = Document(
                            id=doc_row.id,
                            document_id=doc_row.document_id,
                            title=doc_row.title,
                            source_id=doc_row.source_id,
                        )
                        doc.ingested_at = doc_row.ingested_at
                        doc.fingerprint = doc_row.fingerprint
                        
                        # Get chunks for this document
                        chunks_result = await session.execute("""
                            SELECT chunk_text, chunk_index
                            FROM document_chunks
                            WHERE document_id = :doc_id
                            ORDER BY chunk_index
                        """, {'doc_id': doc_row.document_id})
                        
                        chunks = chunks_result.all()
                        
                        if not chunks:
                            logger.warning(f"No chunks found for {doc_row.document_id}")
                            continue
                        
                        # Process document
                        result = await pipeline.process_document(doc, chunks)
                        
                        stats['processed'] += 1
                        if not result.errors:
                            stats['successful'] += 1
                            stats['nodes_created'] += result.nodes_created
                            stats['relationships_created'] += result.relationships_created
                        else:
                            stats['failed'] += 1
                            logger.warning(
                                f"Failed to process {doc_row.document_id}: {result.errors}"
                            )
                        
                    except Exception as e:
                        stats['failed'] += 1
                        logger.error(f"Error processing {doc_row.document_id}: {e}")
                
                # Log progress
                logger.info(
                    f"Progress: {stats['processed']}/{total} "
                    f"(successful: {stats['successful']}, failed: {stats['failed']})"
                )
                
                # Optional: commit progress to tracking table
                await session.commit()
        
    finally:
        await pipeline.close()
    
    # Print final stats
    logger.info("=" * 50)
    logger.info("Backfill completed!")
    logger.info(f"Total processed: {stats['processed']}")
    logger.info(f"Successful: {stats['successful']}")
    logger.info(f"Failed: {stats['failed']}")
    logger.info(f"Nodes created: {stats['nodes_created']}")
    logger.info(f"Relationships created: {stats['relationships_created']}")


def main():
    parser = argparse.ArgumentParser(
        description="Backfill Neo4j graph with existing documents"
    )
    parser.add_argument(
        "--neo4j-uri",
        default="bolt://localhost:7687",
        help="Neo4j connection URI"
    )
    parser.add_argument(
        "--neo4j-user",
        default="neo4j",
        help="Neo4j username"
    )
    parser.add_argument(
        "--neo4j-password",
        required=True,
        help="Neo4j password"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of documents per batch"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of documents to process"
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Number of documents to skip"
    )
    parser.add_argument(
        "--source",
        help="Filter by source_id"
    )
    
    args = parser.parse_args()
    
    asyncio.run(backfill_documents(
        neo4j_uri=args.neo4j_uri,
        neo4j_user=args.neo4j_user,
        neo4j_password=args.neo4j_password,
        batch_size=args.batch_size,
        limit=args.limit,
        offset=args.offset,
        source_filter=args.source,
    ))


if __name__ == "__main__":
    main()
