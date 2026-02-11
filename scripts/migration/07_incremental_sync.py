#!/usr/bin/env python3
"""
GABI Migration - Phase 7: Incremental Sync (Post-Migration)

Handles ongoing synchronization of new/changed documents after
the main migration is complete.
"""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, AsyncGenerator, List, Optional

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
SYNC_INTERVAL = int(os.getenv("SYNC_INTERVAL", "300"))  # 5 minutes default
WATERMARK_FILE = os.getenv("WATERMARK_FILE", ".sync_watermark")

# Use target PG as the primary source after migration
ACTIVE_PG_URL = TARGET_PG_URL or SOURCE_PG_URL


class IncrementalSynchronizer:
    """Synchronizes changes from source to target after migration."""
    
    def __init__(
        self,
        source_pg_url: str,
        target_pg_url: str,
        target_es_url: str,
        watermark_file: str,
    ):
        self.source_pg_url = source_pg_url
        self.target_pg_url = target_pg_url
        self.target_es_url = target_es_url
        self.watermark_file = watermark_file
        self.watermark: Optional[datetime] = None
        
    def load_watermark(self) -> Optional[datetime]:
        """Load last sync watermark from file."""
        try:
            if os.path.exists(self.watermark_file):
                with open(self.watermark_file, "r") as f:
                    timestamp = f.read().strip()
                    return datetime.fromisoformat(timestamp)
        except Exception as e:
            logger.warning(f"Failed to load watermark: {e}")
        return None
    
    def save_watermark(self, watermark: datetime) -> None:
        """Save watermark to file."""
        try:
            with open(self.watermark_file, "w") as f:
                f.write(watermark.isoformat())
        except Exception as e:
            logger.error(f"Failed to save watermark: {e}")
    
    @asynccontextmanager
    async def _get_db(self, url: str) -> AsyncGenerator[Any, None]:
        """Get database connection."""
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text
        
        engine = create_async_engine(url, echo=False)
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
    
    async def get_changed_documents(
        self, since: datetime
    ) -> List[dict]:
        """Get documents changed since watermark."""
        from sqlalchemy import text
        
        async with self._get_db(self.source_pg_url) as conn:
            result = await conn.execute(
                text("""
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
                        d.is_deleted,
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
                    WHERE d.updated_at > :since
                    OR d.created_at > :since
                    ORDER BY d.updated_at
                """),
                {"since": since},
            )
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
                vec = ast.literal_eval(emb_str)
                if isinstance(vec, list) and len(vec) == 384:
                    vectors.append(vec)
            except (ValueError, SyntaxError):
                continue
        
        if not vectors:
            return None
        
        avg_vector = [
            sum(v[i] for v in vectors) / len(vectors)
            for i in range(len(vectors[0]))
        ]
        
        return avg_vector
    
    async def sync_to_postgresql(self, documents: List[dict]) -> int:
        """Sync documents to target PostgreSQL."""
        from sqlalchemy import text
        
        synced = 0
        
        async with self._get_db(self.target_pg_url) as conn:
            for doc in documents:
                try:
                    # Upsert document
                    await conn.execute(
                        text("""
                            INSERT INTO documents (
                                document_id, source_id, fingerprint, title,
                                content_preview, doc_metadata, status,
                                url, ingested_at, updated_at, is_deleted
                            ) VALUES (
                                :document_id, :source, :fingerprint, :title,
                                :content, :metadata, :status,
                                :url, :created_at, :updated_at, :is_deleted
                            )
                            ON CONFLICT (document_id) DO UPDATE SET
                                source_id = EXCLUDED.source_id,
                                fingerprint = EXCLUDED.fingerprint,
                                title = EXCLUDED.title,
                                content_preview = EXCLUDED.content_preview,
                                doc_metadata = EXCLUDED.doc_metadata,
                                status = EXCLUDED.status,
                                url = EXCLUDED.url,
                                updated_at = EXCLUDED.updated_at,
                                is_deleted = EXCLUDED.is_deleted
                        """),
                        {
                            "document_id": doc["document_id"],
                            "source": doc["source"],
                            "fingerprint": doc["fingerprint"],
                            "title": doc["title"],
                            "content": doc["content"],
                            "metadata": doc["metadata"],
                            "status": doc["status"],
                            "url": doc["url"],
                            "created_at": doc["created_at"],
                            "updated_at": doc["updated_at"],
                            "is_deleted": doc["is_deleted"],
                        },
                    )
                    synced += 1
                except Exception as e:
                    logger.error(f"Failed to sync document {doc['document_id']}: {e}")
            
            await conn.commit()
        
        return synced
    
    async def sync_to_elasticsearch(
        self, es_client: Any, documents: List[dict]
    ) -> int:
        """Sync documents to Elasticsearch."""
        from elasticsearch.helpers import async_bulk
        
        def doc_generator():
            for doc in documents:
                avg_vector = self._compute_avg_embedding(doc.get("embeddings"))
                metadata = doc.get("metadata") or {}
                
                if doc.get("is_deleted"):
                    # Handle deletions
                    yield {
                        "_op_type": "delete",
                        "_index": ES_INDEX,
                        "_id": doc["document_id"],
                    }
                else:
                    yield {
                        "_op_type": "index",
                        "_index": ES_INDEX,
                        "_id": doc["document_id"],
                        "_source": {
                            "id": doc["document_id"],
                            "title": doc["title"] or "",
                            "content": doc["content"] or "",
                            "content_vector": avg_vector,
                            "source": doc["source"],
                            "source_type": metadata.get("source_type", "unknown"),
                            "url": doc["url"],
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
                max_retries=2,
            )
            
            if errors:
                logger.warning(f"ES sync had {len(errors)} errors")
            
            return success
        except Exception as e:
            logger.error(f"ES bulk sync failed: {e}")
            return 0
    
    async def run_sync_cycle(self) -> dict:
        """Run a single sync cycle."""
        start_time = datetime.now()
        
        # Load watermark
        if self.watermark is None:
            self.watermark = self.load_watermark()
        
        if self.watermark is None:
            # Default to 24 hours ago if no watermark
            self.watermark = start_time - timedelta(hours=24)
            logger.info(f"No watermark found, starting from {self.watermark}")
        
        # Get changes
        changes = await self.get_changed_documents(self.watermark)
        
        if not changes:
            logger.info("No changes to sync")
            return {"synced": 0, "duration": 0}
        
        logger.info(f"Found {len(changes)} changed documents")
        
        # Sync to PostgreSQL
        pg_synced = await self.sync_to_postgresql(changes)
        logger.info(f"Synced {pg_synced} documents to PostgreSQL")
        
        # Sync to Elasticsearch
        if self.target_es_url:
            async with self._get_es_client() as es_client:
                es_synced = await self.sync_to_elasticsearch(es_client, changes)
                logger.info(f"Synced {es_synced} documents to Elasticsearch")
        else:
            es_synced = 0
        
        # Update watermark
        new_watermark = max(
            (doc["updated_at"] for doc in changes if doc["updated_at"]),
            default=start_time,
        )
        self.watermark = new_watermark
        self.save_watermark(new_watermark)
        
        duration = (datetime.now() - start_time).total_seconds()
        
        return {
            "changes_found": len(changes),
            "pg_synced": pg_synced,
            "es_synced": es_synced,
            "duration": duration,
            "new_watermark": new_watermark.isoformat(),
        }
    
    async def run_continuous(self) -> None:
        """Run continuous sync loop."""
        logger.info(f"Starting incremental sync (interval: {SYNC_INTERVAL}s)")
        
        while True:
            try:
                result = await self.run_sync_cycle()
                
                if result["changes_found"] > 0:
                    logger.info(
                        f"Sync complete: {result['changes_found']} changes, "
                        f"{result['pg_synced']} to PG, {result['es_synced']} to ES, "
                        f"took {result['duration']:.1f}s"
                    )
                
            except Exception as e:
                logger.error(f"Sync cycle failed: {e}")
            
            logger.debug(f"Sleeping for {SYNC_INTERVAL}s...")
            await asyncio.sleep(SYNC_INTERVAL)


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="GABI Incremental Sync")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run sync once and exit (default: continuous)",
    )
    parser.add_argument(
        "--watermark",
        type=str,
        help="Override watermark (ISO format datetime)",
    )
    
    args = parser.parse_args()
    
    # Validate configuration
    if not TARGET_PG_URL:
        logger.error("TARGET_PG_URL environment variable required")
        sys.exit(1)
    
    synchronizer = IncrementalSynchronizer(
        source_pg_url=ACTIVE_PG_URL,
        target_pg_url=TARGET_PG_URL,
        target_es_url=TARGET_ES_URL or "",
        watermark_file=WATERMARK_FILE,
    )
    
    # Override watermark if specified
    if args.watermark:
        synchronizer.watermark = datetime.fromisoformat(args.watermark)
        logger.info(f"Using override watermark: {synchronizer.watermark}")
    
    if args.once:
        result = await synchronizer.run_sync_cycle()
        print(f"\nSync result: {result}")
    else:
        await synchronizer.run_continuous()


if __name__ == "__main__":
    asyncio.run(main())
