#!/usr/bin/env python3
"""
GABI Migration - Phase 4: Elasticsearch Migration

This script reindexes documents from PostgreSQL to Elasticsearch.
We reindex from PG rather than snapshot/restore to ensure consistency
with the migrated PostgreSQL data.
"""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Configuration
SOURCE_PG_URL = os.getenv("SOURCE_PG_URL", "postgresql+asyncpg://localhost:5432/gabi")
TARGET_PG_URL = os.getenv("TARGET_PG_URL", "")
TARGET_ES_URL = os.getenv("TARGET_ES_URL", "")
ES_INDEX = os.getenv("ES_INDEX", "gabi_documents_v1")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "1000"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "4"))


@dataclass
class MigrationStats:
    total_documents: int = 0
    indexed: int = 0
    errors: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    @property
    def duration_seconds(self) -> float:
        if not self.start_time:
            return 0
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds()
    
    @property
    def rate(self) -> float:
        if self.duration_seconds == 0:
            return 0
        return self.indexed / self.duration_seconds


class ElasticsearchMigrator:
    """Migrates documents from PostgreSQL to Elasticsearch."""
    
    def __init__(
        self,
        source_pg_url: str,
        target_pg_url: str,
        target_es_url: str,
        index_name: str,
        batch_size: int = 1000,
    ):
        self.source_pg_url = source_pg_url
        self.target_pg_url = target_pg_url
        self.target_es_url = target_es_url
        self.index_name = index_name
        self.batch_size = batch_size
        self.stats = MigrationStats()
        
    @asynccontextmanager
    async def _get_source_db(self) -> AsyncGenerator[Any, None]:
        """Get source database connection."""
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text
        
        engine = create_async_engine(self.source_pg_url, echo=False)
        try:
            async with engine.connect() as conn:
                yield conn
        finally:
            await engine.dispose()
    
    @asynccontextmanager
    async def _get_es_client(self) -> AsyncGenerator[Any, None]:
        """Get Elasticsearch client."""
        from elasticsearch import AsyncElasticsearch
        
        client = AsyncElasticsearch([self.target_es_url])
        try:
            yield client
        finally:
            await client.close()
    
    async def create_index(self, es_client: Any) -> bool:
        """Create Elasticsearch index with proper mappings."""
        try:
            # Check if index exists
            exists = await es_client.indices.exists(index=self.index_name)
            if exists:
                logger.info(f"Index '{self.index_name}' already exists")
                return True
            
            # Import and use GABI's index setup
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../..", "src"))
            from gabi.services.elasticsearch_setup import (
                INDEX_MAPPINGS,
                INDEX_SETTINGS,
            )
            
            await es_client.indices.create(
                index=self.index_name,
                mappings=INDEX_MAPPINGS,
                settings=INDEX_SETTINGS,
            )
            logger.info(f"Index '{self.index_name}' created successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create index: {e}")
            return False
    
    async def get_total_count(self) -> int:
        """Get total document count from source."""
        from sqlalchemy import text
        
        async with self._get_source_db() as conn:
            result = await conn.execute(
                text("SELECT COUNT(*) FROM documents WHERE is_deleted = false")
            )
            return result.scalar()
    
    async def get_document_batch(
        self, offset: int, limit: int
    ) -> List[Dict[str, Any]]:
        """Fetch batch of documents from PostgreSQL."""
        from sqlalchemy import text
        
        async with self._get_source_db() as conn:
            query = text("""
                SELECT 
                    d.document_id,
                    d.title,
                    d.content_preview as content,
                    d.doc_metadata as metadata,
                    d.source_id as source,
                    d.ingested_at as created_at,
                    d.updated_at,
                    d.url,
                    d.fingerprint,
                    d.status,
                    d.version,
                    d.language,
                    d.chunks_count,
                    (
                        SELECT array_agg(
                            dc.embedding::text
                            ORDER BY dc.chunk_index
                        ) FILTER (WHERE dc.embedding IS NOT NULL)
                        FROM document_chunks dc
                        WHERE dc.document_id = d.document_id
                    ) as embeddings
                FROM documents d
                WHERE d.is_deleted = false
                ORDER BY d.ingested_at
                OFFSET :offset
                LIMIT :limit
            """)
            
            result = await conn.execute(query, {"offset": offset, "limit": limit})
            rows = result.mappings().all()
            return [dict(row) for row in rows]
    
    def _compute_avg_embedding(self, embeddings: Optional[List[str]]) -> Optional[List[float]]:
        """Compute average embedding from chunk embeddings."""
        if not embeddings:
            return None
        
        import ast
        vectors = []
        
        for emb_str in embeddings:
            try:
                # Parse the vector string representation
                vec = ast.literal_eval(emb_str)
                if isinstance(vec, list) and len(vec) == 384:
                    vectors.append(vec)
            except (ValueError, SyntaxError):
                continue
        
        if not vectors:
            return None
        
        # Compute average vector
        avg_vector = [
            sum(v[i] for v in vectors) / len(vectors)
            for i in range(len(vectors[0]))
        ]
        
        return avg_vector
    
    async def index_batch(
        self,
        es_client: Any,
        documents: List[Dict[str, Any]],
    ) -> tuple[int, int]:
        """Index batch of documents to Elasticsearch."""
        from elasticsearch.helpers import async_bulk
        
        def doc_generator():
            for doc in documents:
                avg_vector = self._compute_avg_embedding(doc.get("embeddings"))
                
                metadata = doc.get("metadata") or {}
                
                yield {
                    "_index": self.index_name,
                    "_id": doc["document_id"],
                    "_source": {
                        "id": doc["document_id"],
                        "title": doc["title"] or "",
                        "content": doc["content"] or "",
                        "content_vector": avg_vector,
                        "source": doc["source"],
                        "source_type": metadata.get("source_type", "unknown"),
                        "url": doc["url"],
                        "fingerprint": doc.get("fingerprint"),
                        "status": doc.get("status"),
                        "version": doc.get("version"),
                        "language": doc.get("language", "pt-BR"),
                        "created_at": (
                            doc["created_at"].isoformat() if doc["created_at"] else None
                        ),
                        "updated_at": (
                            doc["updated_at"].isoformat() if doc["updated_at"] else None
                        ),
                        "metadata": metadata,
                    }
                }
        
        try:
            success, errors = await async_bulk(
                es_client,
                doc_generator(),
                raise_on_error=False,
                max_retries=3,
                initial_backoff=2,
            )
            
            if errors:
                logger.warning(f"Batch had {len(errors)} errors")
                
            return success, len(errors)
            
        except Exception as e:
            logger.error(f"Bulk indexing failed: {e}")
            return 0, len(documents)
    
    async def migrate(self) -> MigrationStats:
        """Run full migration."""
        self.stats.start_time = datetime.now()
        
        logger.info("Starting Elasticsearch migration...")
        logger.info(f"Target ES: {self.target_es_url}")
        logger.info(f"Index: {self.index_name}")
        logger.info(f"Batch size: {self.batch_size}")
        
        # Get total count
        self.stats.total_documents = await self.get_total_count()
        logger.info(f"Total documents to migrate: {self.stats.total_documents}")
        
        async with self._get_es_client() as es_client:
            # Test connection
            try:
                info = await es_client.info()
                logger.info(f"Connected to ES: {info['version']['number']}")
            except Exception as e:
                logger.error(f"Failed to connect to ES: {e}")
                return self.stats
            
            # Create index
            if not await self.create_index(es_client):
                logger.error("Failed to create index, aborting")
                return self.stats
            
            # Migrate in batches
            offset = 0
            batch_num = 0
            last_progress_time = datetime.now()
            
            while offset < self.stats.total_documents:
                batch_num += 1
                documents = await self.get_document_batch(offset, self.batch_size)
                
                if not documents:
                    logger.warning(f"No documents returned at offset {offset}")
                    break
                
                # Index batch
                indexed, errors = await self.index_batch(es_client, documents)
                self.stats.indexed += indexed
                self.stats.errors += errors
                offset += len(documents)
                
                # Progress report every 10 seconds or every 10 batches
                now = datetime.now()
                if batch_num % 10 == 0 or (now - last_progress_time).seconds >= 10:
                    progress = (offset / self.stats.total_documents) * 100
                    elapsed = self.stats.duration_seconds
                    rate = self.stats.rate
                    eta = (self.stats.total_documents - self.stats.indexed) / rate if rate > 0 else 0
                    
                    logger.info(
                        f"Progress: {progress:.1f}% ({offset}/{self.stats.total_documents}) | "
                        f"Indexed: {self.stats.indexed} | "
                        f"Errors: {self.stats.errors} | "
                        f"Rate: {rate:.1f} docs/sec | "
                        f"ETA: {eta/60:.1f} min"
                    )
                    last_progress_time = now
        
        self.stats.end_time = datetime.now()
        
        # Final summary
        logger.info("=" * 60)
        logger.info("Migration Complete")
        logger.info("=" * 60)
        logger.info(f"Total documents: {self.stats.total_documents}")
        logger.info(f"Indexed: {self.stats.indexed}")
        logger.info(f"Errors: {self.stats.errors}")
        logger.info(f"Duration: {self.stats.duration_seconds/60:.1f} minutes")
        logger.info(f"Rate: {self.stats.rate:.1f} docs/sec")
        
        return self.stats


async def main():
    """Main entry point."""
    # Validate configuration
    if not TARGET_ES_URL:
        print("Error: TARGET_ES_URL environment variable required")
        print("Usage: TARGET_ES_URL=https://es.fly.dev python 04_migrate_elasticsearch.py")
        sys.exit(1)
    
    # Use target PG as source if specified, otherwise use local
    pg_url = TARGET_PG_URL or SOURCE_PG_URL
    
    migrator = ElasticsearchMigrator(
        source_pg_url=pg_url,
        target_pg_url=pg_url,
        target_es_url=TARGET_ES_URL,
        index_name=ES_INDEX,
        batch_size=BATCH_SIZE,
    )
    
    stats = await migrator.migrate()
    
    # Exit with error if not all documents indexed
    if stats.indexed < stats.total_documents * 0.99:  # Allow 1% tolerance
        logger.error(f"Not all documents indexed ({stats.indexed}/{stats.total_documents})")
        sys.exit(1)
    
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
