#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════════════════
# GABI - Reindex PostgreSQL to Elasticsearch
# Script para indexar documentos do PostgreSQL no Elasticsearch
# Uso: ./scripts/reindex_to_es.py [--source SOURCE] [--batch-size N] [--dry-run]
# ═══════════════════════════════════════════════════════════════════════════════

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from typing import Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add src to path
sys.path.insert(0, 'src')

from gabi.config import settings
from gabi.db import async_session_factory, init_db
from gabi.pipeline.indexer import create_indexer, IndexingStatus
from gabi.services.indexing_service import IndexingService, DocumentContent
from gabi.pipeline.embedder import Embedder
from sqlalchemy import select, func
from gabi.models.document import Document
from gabi.models.chunk import DocumentChunk


async def get_document_count(source_id: Optional[str] = None) -> int:
    """Get total document count from PostgreSQL."""
    async with async_session_factory() as session:
        query = select(func.count()).select_from(Document).where(Document.is_deleted == False)
        if source_id:
            query = query.where(Document.source_id == source_id)
        result = await session.execute(query)
        return result.scalar()


async def get_documents_batch(offset: int, limit: int, source_id: Optional[str] = None):
    """Get a batch of documents from PostgreSQL."""
    async with async_session_factory() as session:
        query = (
            select(Document)
            .where(Document.is_deleted == False)
            .where(Document.es_indexed == False)  # Only unindexed
            .offset(offset)
            .limit(limit)
        )
        if source_id:
            query = query.where(Document.source_id == source_id)
        
        result = await session.execute(query)
        return result.scalars().all()


async def get_document_chunks(session, document_id: str):
    """Get chunks for a document."""
    result = await session.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .where(DocumentChunk.is_deleted == False)
        .order_by(DocumentChunk.chunk_index)
    )
    return result.scalars().all()


async def reindex_document(
    document: Document,
    indexer,
    embedder: Optional[Embedder] = None
) -> bool:
    """Reindex a single document to Elasticsearch.
    
    Returns True if successful.
    """
    try:
        async with async_session_factory() as session:
            # Get chunks
            chunks = await get_document_chunks(session, document.document_id)
            
            if not chunks:
                logger.warning(f"No chunks found for document {document.document_id}")
                # Mark as indexed anyway to avoid retry
                document.es_indexed = True
                document.es_indexed_at = datetime.utcnow()
                await session.commit()
                return True
            
            # Create chunk data for indexer
            from gabi.pipeline.indexer import ChunkData
            
            chunk_data_list = []
            for chunk in chunks:
                embedding = None
                if chunk.embedding is not None:
                    # Parse embedding from string or numpy array
                    if isinstance(chunk.embedding, str):
                        import json
                        try:
                            embedding = json.loads(chunk.embedding)
                        except json.JSONDecodeError:
                            embedding = None
                    elif hasattr(chunk.embedding, 'tolist'):  # numpy array
                        embedding = chunk.embedding.tolist()
                    else:
                        embedding = chunk.embedding
                
                chunk_data = ChunkData(
                    chunk_index=chunk.chunk_index,
                    text=chunk.chunk_text,
                    token_count=chunk.token_count or 0,
                    char_count=chunk.char_count or len(chunk.chunk_text),
                    embedding=embedding,
                    metadata=chunk.chunk_metadata or {},
                    section_type=chunk.section_type,
                )
                chunk_data_list.append(chunk_data)
            
            # Index to Elasticsearch
            indexing_result = await indexer.index_document(
                document=document,
                chunks=chunk_data_list,
                source_id=document.source_id,
            )
            
            # Check result
            if indexing_result.status in (IndexingStatus.SUCCESS, IndexingStatus.PARTIAL):
                # Mark as indexed in PG
                document.es_indexed = True
                document.es_indexed_at = datetime.utcnow()
                await session.commit()
                
                if indexing_result.status == IndexingStatus.PARTIAL:
                    logger.warning(
                        f"Document {document.document_id} partially indexed (ES may have failed)"
                    )
                
                return True
            else:
                logger.error(
                    f"Failed to index document {document.document_id}: {indexing_result.errors}"
                )
                return False
                
    except Exception as e:
        logger.exception(f"Error reindexing document {document.document_id}: {e}")
        return False


async def reindex_all(
    source_id: Optional[str] = None,
    batch_size: int = 100,
    dry_run: bool = False,
    max_docs: Optional[int] = None,
):
    """Main reindexing loop."""
    
    # Initialize database
    await init_db()
    
    # Get document count
    total_docs = await get_document_count(source_id)
    logger.info(f"Found {total_docs} documents to index")
    
    if dry_run:
        logger.info("DRY RUN - No changes will be made")
        return
    
    if total_docs == 0:
        logger.info("No documents to index")
        return
    
    # Create indexer
    indexer = await create_indexer(
        es_url=settings.elasticsearch_url,
        es_index=settings.elasticsearch_index,
    )
    
    # Create embedder (not used if chunks already have embeddings)
    embedder = None
    
    # Statistics
    stats = {
        "total": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0,
    }
    
    # Process in batches
    offset = 0
    actual_limit = min(max_docs or float('inf'), total_docs)
    
    while offset < actual_limit:
        batch_limit = min(batch_size, actual_limit - offset)
        documents = await get_documents_batch(offset, batch_limit, source_id)
        
        if not documents:
            break
        
        logger.info(f"Processing batch: {offset+1}-{offset+len(documents)} of {total_docs}")
        
        for doc in documents:
            stats["total"] += 1
            
            success = await reindex_document(doc, indexer, embedder)
            
            if success:
                stats["success"] += 1
            else:
                stats["failed"] += 1
            
            # Progress report every 10 docs
            if stats["total"] % 10 == 0:
                progress = (stats["total"] / total_docs) * 100
                logger.info(
                    f"Progress: {stats['total']}/{total_docs} ({progress:.1f}%) - "
                    f"Success: {stats['success']}, Failed: {stats['failed']}"
                )
        
        offset += len(documents)
    
    # Final report
    logger.info("═══════════════════════════════════════════════════")
    logger.info("Reindexing Complete!")
    logger.info(f"  Total processed: {stats['total']}")
    logger.info(f"  Successful: {stats['success']}")
    logger.info(f"  Failed: {stats['failed']}")
    logger.info("═══════════════════════════════════════════════════")
    
    # Verify Elasticsearch count
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{settings.elasticsearch_url}/{settings.elasticsearch_index}/_count"
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    es_count = data.get('count', 0)
                    logger.info(f"Documents in Elasticsearch: {es_count}")
    except Exception as e:
        logger.warning(f"Could not verify ES count: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Reindex PostgreSQL documents to Elasticsearch"
    )
    parser.add_argument(
        "--source",
        help="Source ID to filter documents (default: all sources)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Batch size for processing (default: 100)",
    )
    parser.add_argument(
        "--max-docs",
        type=int,
        help="Maximum documents to process (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    
    args = parser.parse_args()
    
    asyncio.run(reindex_all(
        source_id=args.source,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        max_docs=args.max_docs,
    ))


if __name__ == "__main__":
    main()
