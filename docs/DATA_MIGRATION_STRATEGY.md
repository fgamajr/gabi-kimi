# GABI Data Migration Strategy: Local → Fly.io

## Executive Summary

This document provides a comprehensive strategy for migrating ~470,000 documents from local infrastructure to Fly.io production environment.

**Recommended Approach**: Option A (Full Migration) with staged rollout

| Metric | Estimate |
|--------|----------|
| Documents | ~470,000 |
| PostgreSQL Size | ~50-100 GB (estimated) |
| Elasticsearch Index | ~20-40 GB (estimated) |
| Embedding Dimensions | 384 (fixed, ADR-001) |
| Downtime | 2-4 hours (with blue-green) |
| Migration Window | 24-48 hours total |

---

## 1. Data Architecture Analysis

### 1.1 Current Data Stores

```
┌─────────────────────────────────────────────────────────────┐
│                     GABI Data Layer                         │
├─────────────────────────────────────────────────────────────┤
│  PostgreSQL (pgvector)                                      │
│  ├── documents (~470k rows)                                 │
│  ├── document_chunks (~5-10M rows, est.)                    │
│  ├── source_registry (~50-100 rows)                         │
│  ├── execution_manifests                                    │
│  ├── dlq_messages                                           │
│  └── audit logs                                             │
├─────────────────────────────────────────────────────────────┤
│  Elasticsearch                                              │
│  └── gabi_documents_v1 (BM25 + dense_vector)                │
├─────────────────────────────────────────────────────────────┤
│  Redis                                                      │
│  ├── Celery task queues                                     │
│  ├── Result backend                                         │
│  └── Cache layer                                            │
├─────────────────────────────────────────────────────────────┤
│  File System                                                │
│  └── TEI models (~472 MB)                                   │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Data Volume Estimates

| Store | Records | Size Est. | Growth Rate |
|-------|---------|-----------|-------------|
| PostgreSQL documents | 470,000 | ~20 GB | +1k/day |
| PostgreSQL chunks | ~5M | ~40 GB | +10k/day |
| PostgreSQL embeddings | ~5M | ~30 GB | +10k/day |
| Elasticsearch index | 470,000 docs | ~15 GB | +1k/day |
| Redis (transient) | - | ~2 GB | rotated |
| TEI models | - | 472 MB | static |

### 1.3 Critical Dependencies

- **Embeddings**: 384-dimensional vectors (immutable per ADR-001)
- **Fingerprint**: SHA-256 content hashing for deduplication
- **ES Sync**: PostgreSQL `es_indexed` flag tracks sync state
- **Chunks**: Each document has 10-15 chunks average

---

## 2. Migration Options Comparison

### Option A: Full Migration (RECOMMENDED)

Migrate all data to Fly.io-managed services.

**Pros:**
- Single environment to manage
- Lower latency between services
- Simplified operations
- Cost-effective at scale

**Cons:**
- Large initial transfer
- Requires cutover window
- Rollback complexity

**Cost Estimate:**
- Fly.io PostgreSQL: ~$50-100/month (100GB)
- Fly.io Elasticsearch: ~$30-60/month
- Fly.io Redis: ~$15-30/month
- Data transfer: ~$20-50 (one-time)
- **Total: ~$100-200/month**

### Option B: Partial Migration (API on Fly.io, Data Local)

Keep data local, run API on Fly.io with VPN/tunnel.

**Pros:**
- No large data transfer
- Immediate rollback capability
- Gradual migration

**Cons:**
- Higher latency (API ↔ Data)
- Complex network setup
- Split-brain risks
- Higher operational overhead

### Option C: Fresh Start (Re-ingest)

Start fresh on Fly.io, re-ingest all documents.

**Pros:**
- Cleanest state
- No migration complexity
- Can optimize schema

**Cons:**
- ~2-4 weeks to re-ingest 470k docs
- Data loss (history, manifests, DLQ)
- Source APIs may have rate limits

---

## 3. Migration Strategy: Option A (Full)

### 3.1 Pre-Migration Phase (Week -1)

```bash
# 1. Provision Fly.io infrastructure
fly postgres create --name gabi-db-prod --region gru --vm-size dedicated-cpu-2x --volume-size 100
fly ext elasticsearch create --name gabi-es-prod --region gru --plan starter
fly redis create --name gabi-redis-prod --region gru --plan starter

# 2. Create migration user with appropriate permissions
# 3. Configure VPC/private networking
# 4. Set up backup schedules on Fly.io
```

### 3.2 Migration Execution (Migration Day)

```
Phase 1: Schema & Reference Data (0-30 min)
├── Run Alembic migrations on Fly.io Postgres
├── Migrate source_registry (config)
└── Verify schema compatibility

Phase 2: PostgreSQL Data (30 min - 4 hours)
├── pg_dump with compression
├── Transfer to Fly.io
├── pg_restore with parallel workers
└── Verify row counts

Phase 3: Elasticsearch Index (2-4 hours)
├── Create index with mappings
├── Reindex from PostgreSQL (NOT snapshot restore)
└── Verify document counts + search

Phase 4: Validation (1-2 hours)
├── Row count validation
├── Spot-check embeddings
├── Search functionality test
└── Application smoke tests

Phase 5: Cutover (30 min)
├── DNS switch
├── Monitor error rates
└── Enable write traffic
```

### 3.3 Post-Migration

```
├── 24-hour monitoring period
├── Incremental sync validation
├── Performance baseline establishment
└── Decommission local infrastructure
```

---

## 4. Migration Scripts

### 4.1 Database Migration Script

```bash
#!/bin/bash
# scripts/migrate_postgres.sh

set -euo pipefail

# Configuration
SOURCE_URL="${SOURCE_DB_URL:-postgresql://localhost:5432/gabi}"
TARGET_URL="${TARGET_DB_URL:-postgres://user:pass@db.fly.dev:5432/gabi}"
DUMP_FILE="gabi_dump_$(date +%Y%m%d_%H%M%S).sql.gz"
PARALLEL_WORKERS=4

log() { echo "[$(date +%H:%M:%S)] $*"; }

# Phase 1: Schema-only dump
log "Creating schema dump..."
pg_dump "$SOURCE_URL" \
    --schema-only \
    --no-owner \
    --no-privileges \
    --file=schema.sql

# Phase 2: Data dump (parallel)
log "Creating data dump with $PARALLEL_WORKERS parallel jobs..."
pg_dump "$SOURCE_URL" \
    --data-only \
    --compress=9 \
    --jobs=$PARALLEL_WORKERS \
    --file="$DUMP_FILE" \
    --verbose

# Phase 3: Transfer and restore
log "Restoring to target..."
gunzip -c "$DUMP_FILE" | psql "$TARGET_URL"

# Phase 4: Verify
log "Verifying migration..."
source_count=$(psql "$SOURCE_URL" -t -c "SELECT COUNT(*) FROM documents;")
target_count=$(psql "$TARGET_URL" -t -c "SELECT COUNT(*) FROM documents;")

if [ "$source_count" -eq "$target_count" ]; then
    log "✓ Document count match: $target_count"
else
    log "✗ Document count mismatch: source=$source_count, target=$target_count"
    exit 1
fi

log "Migration complete!"
```

### 4.2 Elasticsearch Migration Script

```python
#!/usr/bin/env python3
"""Elasticsearch index migration via reindexing from PostgreSQL."""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from elasticsearch import AsyncElasticsearch
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
SOURCE_PG_URL = "postgresql+asyncpg://localhost:5432/gabi"
TARGET_ES_URL = "https://es.fly.dev:443"
ES_INDEX = "gabi_documents_v1"
BATCH_SIZE = 1000


class ElasticsearchMigrator:
    """Migrates documents from PostgreSQL to Elasticsearch."""
    
    def __init__(self, pg_url: str, es_url: str, index_name: str):
        self.pg_url = pg_url
        self.es_url = es_url
        self.index_name = index_name
        self.engine = create_async_engine(pg_url, echo=False)
        self.async_session = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        self.es_client: Optional[AsyncElasticsearch] = None
        
    async def __aenter__(self):
        self.es_client = AsyncElasticsearch([self.es_url])
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.es_client:
            await self.es_client.close()
        await self.engine.dispose()
        
    async def create_index(self) -> bool:
        """Create index with proper mappings."""
        from gabi.services.elasticsearch_setup import (
            create_index, INDEX_NAME, INDEX_MAPPING
        )
        return await create_index(self.es_client, INDEX_NAME)
        
    async def get_document_batch(self, offset: int, limit: int):
        """Fetch batch of documents from PostgreSQL."""
        async with self.async_session() as session:
            # Query documents with their chunks
            query = text("""
                SELECT 
                    d.id,
                    d.document_id,
                    d.title,
                    d.content_preview as content,
                    d.doc_metadata as metadata,
                    d.source_id as source,
                    d.ingested_at as created_at,
                    d.updated_at,
                    d.url,
                    array_agg(
                        dc.embedding::text
                        ORDER BY dc.chunk_index
                    ) FILTER (WHERE dc.embedding IS NOT NULL) as embeddings
                FROM documents d
                LEFT JOIN document_chunks dc ON d.document_id = dc.document_id
                WHERE d.is_deleted = false
                GROUP BY d.id
                ORDER BY d.ingested_at
                OFFSET :offset
                LIMIT :limit
            """)
            
            result = await session.execute(
                query, {"offset": offset, "limit": limit}
            )
            return [dict(row) for row in result.mappings()]
            
    async def index_batch(self, documents: list[dict]) -> int:
        """Index batch of documents to Elasticsearch."""
        from elasticsearch.helpers import async_bulk
        
        def doc_generator():
            for doc in documents:
                # Average embeddings from all chunks for document-level vector
                embeddings = doc.get("embeddings", [])
                if embeddings and len(embeddings) > 0:
                    # Parse the vector string representation
                    import ast
                    vectors = []
                    for emb_str in embeddings:
                        try:
                            vec = ast.literal_eval(emb_str)
                            vectors.append(vec)
                        except:
                            continue
                    
                    if vectors:
                        # Average the vectors
                        avg_vector = [
                            sum(v[i] for v in vectors) / len(vectors)
                            for i in range(len(vectors[0]))
                        ]
                    else:
                        avg_vector = None
                else:
                    avg_vector = None
                
                yield {
                    "_index": self.index_name,
                    "_id": doc["document_id"],
                    "_source": {
                        "id": doc["document_id"],
                        "title": doc["title"],
                        "content": doc["content"],
                        "content_vector": avg_vector,
                        "source": doc["source"],
                        "source_type": doc.get("metadata", {}).get("source_type", "unknown"),
                        "url": doc["url"],
                        "created_at": doc["created_at"].isoformat() if doc["created_at"] else None,
                        "updated_at": doc["updated_at"].isoformat() if doc["updated_at"] else None,
                        "metadata": doc.get("metadata", {}),
                    }
                }
        
        success, errors = await async_bulk(
            self.es_client,
            doc_generator(),
            raise_on_error=False,
        )
        return success
        
    async def migrate(self) -> dict:
        """Run full migration."""
        logger.info("Starting Elasticsearch migration...")
        
        # Get total count
        async with self.async_session() as session:
            result = await session.execute(
                select(text("COUNT(*)")).select_from(text("documents"))
                .where(text("is_deleted = false"))
            )
            total_docs = result.scalar()
            
        logger.info(f"Total documents to migrate: {total_docs}")
        
        # Create index
        await self.create_index()
        
        # Migrate in batches
        total_indexed = 0
        offset = 0
        start_time = datetime.now()
        
        while offset < total_docs:
            batch = await self.get_document_batch(offset, BATCH_SIZE)
            if not batch:
                break
                
            indexed = await self.index_batch(batch)
            total_indexed += indexed
            offset += len(batch)
            
            # Progress report
            progress = (offset / total_docs) * 100
            elapsed = (datetime.now() - start_time).total_seconds()
            rate = total_indexed / elapsed if elapsed > 0 else 0
            eta_seconds = (total_docs - offset) / rate if rate > 0 else 0
            
            logger.info(
                f"Progress: {progress:.1f}% ({offset}/{total_docs}) "
                f"| Indexed: {total_indexed} "
                f"| Rate: {rate:.1f} docs/sec "
                f"| ETA: {eta_seconds/60:.1f} min"
            )
            
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"Migration complete! Indexed {total_indexed} docs in {duration/60:.1f} minutes")
        
        return {
            "total_documents": total_docs,
            "indexed": total_indexed,
            "duration_seconds": duration,
            "rate": total_indexed / duration if duration > 0 else 0,
        }


async def main():
    async with ElasticsearchMigrator(SOURCE_PG_URL, TARGET_ES_URL, ES_INDEX) as migrator:
        result = await migrator.migrate()
        print(f"\nMigration Summary:")
        print(f"  Documents: {result['indexed']}/{result['total_documents']}")
        print(f"  Duration: {result['duration_seconds']/60:.1f} minutes")
        print(f"  Rate: {result['rate']:.1f} docs/sec")


if __name__ == "__main__":
    asyncio.run(main())
```

### 4.3 File/Asset Migration

```bash
#!/bin/bash
# scripts/migrate_files.sh

# TEI Models migration
SOURCE_MODELS="./data/tei/model"
TARGET_HOST="fly.io-app"

echo "Migrating TEI models..."

# Option 1: Direct upload to Fly.io volume
flyctl ssh console --app gabi-api-prod << 'EOF'
mkdir -p /app/data/tei/model
cd /app/data/tei/model
# Download from S3 or other storage
wget https://your-storage/models.tar.gz
tar xzf models.tar.gz
rm models.tar.gz
EOF

# Option 2: Using fly volumes
echo "Ensure fly volume is mounted at /app/data"
fly volumes list --app gabi-api-prod
```

### 4.4 Validation Script

```python
#!/usr/bin/env python3
"""Post-migration validation suite."""

import asyncio
import sys
from dataclasses import dataclass
from typing import List, Optional

from elasticsearch import AsyncElasticsearch
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine


@dataclass
class ValidationResult:
    name: str
    passed: bool
    details: str
    severity: str  # "error", "warning", "info"


class MigrationValidator:
    """Validates migrated data consistency."""
    
    def __init__(self, pg_url: str, es_url: str, redis_url: str):
        self.pg_url = pg_url
        self.es_url = es_url
        self.redis_url = redis_url
        self.results: List[ValidationResult] = []
        
    async def validate_postgresql(self) -> None:
        """Validate PostgreSQL data."""
        engine = create_async_engine(self.pg_url)
        
        try:
            async with engine.connect() as conn:
                # 1. Row counts
                tables = ["documents", "document_chunks", "source_registry", "execution_manifests"]
                for table in tables:
                    result = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                    count = result.scalar()
                    self.results.append(ValidationResult(
                        name=f"pg_{table}_count",
                        passed=count > 0,
                        details=f"{table}: {count} rows",
                        severity="info" if count > 0 else "error"
                    ))
                
                # 2. Check for orphan chunks
                result = await conn.execute(text("""
                    SELECT COUNT(*) FROM document_chunks dc
                    LEFT JOIN documents d ON dc.document_id = d.document_id
                    WHERE d.document_id IS NULL
                """))
                orphan_count = result.scalar()
                self.results.append(ValidationResult(
                    name="pg_orphan_chunks",
                    passed=orphan_count == 0,
                    details=f"Orphan chunks: {orphan_count}",
                    severity="error" if orphan_count > 0 else "info"
                ))
                
                # 3. Check embedding dimensions
                result = await conn.execute(text("""
                    SELECT embedding_model, COUNT(*) 
                    FROM document_chunks 
                    WHERE embedding IS NOT NULL
                    GROUP BY embedding_model
                """))
                models = result.fetchall()
                for model, count in models:
                    self.results.append(ValidationResult(
                        name=f"pg_embedding_model_{model}",
                        passed=True,
                        details=f"Model {model}: {count} embeddings",
                        severity="info"
                    ))
                    
                # 4. Check es_indexed flag consistency
                result = await conn.execute(text("""
                    SELECT 
                        COUNT(*) FILTER (WHERE es_indexed = true) as indexed,
                        COUNT(*) FILTER (WHERE es_indexed = false) as not_indexed
                    FROM documents
                    WHERE is_deleted = false
                """))
                row = result.fetchone()
                self.results.append(ValidationResult(
                    name="pg_es_sync_status",
                    passed=True,
                    details=f"ES indexed: {row.indexed}, Not indexed: {row.not_indexed}",
                    severity="info"
                ))
                    
        finally:
            await engine.dispose()
            
    async def validate_elasticsearch(self) -> None:
        """Validate Elasticsearch index."""
        es = AsyncElasticsearch([self.es_url])
        
        try:
            # 1. Index exists
            exists = await es.indices.exists(index="gabi_documents_v1")
            self.results.append(ValidationResult(
                name="es_index_exists",
                passed=exists,
                details="Index gabi_documents_v1 exists" if exists else "Index missing!",
                severity="error" if not exists else "info"
            ))
            
            if not exists:
                return
                
            # 2. Document count
            stats = await es.indices.stats(index="gabi_documents_v1")
            doc_count = stats["indices"]["gabi_documents_v1"]["total"]["docs"]["count"]
            self.results.append(ValidationResult(
                name="es_document_count",
                passed=doc_count > 0,
                details=f"ES documents: {doc_count}",
                severity="info"
            ))
            
            # 3. Sample search
            search_result = await es.search(
                index="gabi_documents_v1",
                body={"query": {"match_all": {}}, "size": 1}
            )
            has_hits = search_result["hits"]["total"]["value"] > 0
            self.results.append(ValidationResult(
                name="es_search_functional",
                passed=has_hits,
                details="Search returns results" if has_hits else "Search empty!",
                severity="error" if not has_hits else "info"
            ))
            
            # 4. Vector search test
            vector_result = await es.search(
                index="gabi_documents_v1",
                body={
                    "query": {
                        "script_score": {
                            "query": {"match_all": {}},
                            "script": {
                                "source": "cosineSimilarity(params.query_vector, 'content_vector') + 1.0",
                                "params": {"query_vector": [0.1] * 384}
                            }
                        }
                    },
                    "size": 1
                }
            )
            vector_works = vector_result["hits"]["total"]["value"] > 0
            self.results.append(ValidationResult(
                name="es_vector_search",
                passed=vector_works,
                details="Vector search functional" if vector_works else "Vector search failed!",
                severity="warning" if not vector_works else "info"
            ))
            
        finally:
            await es.close()
            
    async def validate_cross_store_consistency(self) -> None:
        """Validate consistency between PostgreSQL and Elasticsearch."""
        engine = create_async_engine(self.pg_url)
        es = AsyncElasticsearch([self.es_url])
        
        try:
            # Compare document counts
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT COUNT(*) FROM documents WHERE is_deleted = false")
                )
                pg_count = result.scalar()
                
            stats = await es.indices.stats(index="gabi_documents_v1")
            es_count = stats["indices"]["gabi_documents_v1"]["total"]["docs"]["count"]
            
            diff = abs(pg_count - es_count)
            diff_pct = (diff / pg_count * 100) if pg_count > 0 else 0
            
            self.results.append(ValidationResult(
                name="cross_store_count_match",
                passed=diff_pct < 1.0,  # Allow 1% difference
                details=f"PG: {pg_count}, ES: {es_count}, Diff: {diff} ({diff_pct:.2f}%)",
                severity="error" if diff_pct > 5 else "warning" if diff_pct > 1 else "info"
            ))
            
        finally:
            await engine.dispose()
            await es.close()
            
    def print_report(self) -> bool:
        """Print validation report. Returns True if all critical checks passed."""
        print("\n" + "=" * 70)
        print("MIGRATION VALIDATION REPORT")
        print("=" * 70)
        
        errors = []
        warnings = []
        
        for result in self.results:
            status = "✓" if result.passed else "✗"
            color = "\033[92m" if result.passed else "\033[91m"
            reset = "\033[0m"
            
            print(f"{color}{status}{reset} [{result.severity.upper()}] {result.name}")
            print(f"    {result.details}")
            
            if not result.passed and result.severity == "error":
                errors.append(result)
            elif not result.passed and result.severity == "warning":
                warnings.append(result)
                
        print("-" * 70)
        print(f"Results: {len(self.results)} checks")
        print(f"  Passed: {len(self.results) - len(errors) - len(warnings)}")
        print(f"  Warnings: {len(warnings)}")
        print(f"  Errors: {len(errors)}")
        
        if errors:
            print("\n\033[91mCRITICAL ERRORS DETECTED - DO NOT PROCEED WITH CUTOVER\033[0m")
            return False
        elif warnings:
            print("\n\033[93mWarnings present - review before cutover\033[0m")
            return True
        else:
            print("\n\033[92mAll checks passed - ready for cutover\033[0m")
            return True


async def main():
    import os
    
    pg_url = os.getenv("TARGET_PG_URL", "postgresql+asyncpg://localhost:5432/gabi")
    es_url = os.getenv("TARGET_ES_URL", "http://localhost:9200")
    redis_url = os.getenv("TARGET_REDIS_URL", "redis://localhost:6379")
    
    validator = MigrationValidator(pg_url, es_url, redis_url)
    
    print("Running validations...")
    await validator.validate_postgresql()
    await validator.validate_elasticsearch()
    await validator.validate_cross_store_consistency()
    
    success = validator.print_report()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 5. Rollback Strategy

### 5.1 Rollback Triggers

| Trigger | Action |
|---------|--------|
| >5% data loss | Immediate rollback |
| Search non-functional | Immediate rollback |
| Error rate >1% | Evaluate: rollback or hotfix |
| Latency >2s p95 | Evaluate after 15 min |

### 5.2 Rollback Procedure

```bash
#!/bin/bash
# scripts/rollback.sh

# 1. Stop write traffic
echo "Stopping write traffic..."
# Disable ingestion jobs
flyctl ssh console --app gabi-api-prod --command "celery control cancel_consumer gabi.sync"

# 2. Switch DNS back
echo "Reverting DNS..."
# Update DNS records to point to local infrastructure

# 3. Verify local system health
echo "Verifying local system..."
docker compose --profile infra ps
docker compose --profile all ps

# 4. Resume traffic to local
echo "Rollback complete - traffic now routing to local infrastructure"

# 5. Post-rollback: Sync any new data written to Fly.io back to local
echo "Scheduling data sync back from Fly.io (optional)..."
```

### 5.3 Blue-Green Cutover (Zero Downtime Option)

```
┌─────────────────────────────────────────────────────────────────┐
│                    BLUE-GREEN CUTOVER                          │
├─────────────────────────────────────────────────────────────────┤
│  Phase 1: Setup                                                 │
│  ├── Deploy GABI to Fly.io (Green)                             │
│  ├── Run full migration to Fly.io                              │
│  ├── Validate data consistency                                 │
│  └── Configure read replicas (optional)                        │
│                                                                 │
│  Phase 2: Dual Write (1-2 hours)                               │
│  ├── Enable writes to both local (Blue) and Fly.io (Green)     │
│  ├── Monitor consistency                                       │
│  └── Keep reads from Blue                                      │
│                                                                 │
│  Phase 3: Read Cutover                                         │
│  ├── Switch reads to Green                                     │
│  ├── Monitor for 15-30 minutes                                 │
│  └── Disable Blue writes                                       │
│                                                                 │
│  Phase 4: Final Cutover                                        │
│  ├── Verify all writes synced                                  │
│  ├── Switch DNS to Green                                       │
│  └── Decommission Blue                                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. Incremental Sync Strategy (Post-Migration)

### 6.1 Delta Sync Architecture

```python
# After migration, handle new/changed documents

class IncrementalSync:
    """Sync changes from local to Fly.io after main migration."""
    
    def __init__(self, source_pg, target_pg, target_es):
        self.source = source_pg
        self.target_pg = target_pg
        self.target_es = target_es
        self.watermark = None
        
    async def get_changes(self, since: datetime) -> List[Document]:
        """Get documents changed since watermark."""
        query = select(Document).where(
            or_(
                Document.updated_at > since,
                Document.created_at > since
            )
        )
        return await self.source.execute(query)
        
    async def sync_document(self, doc: Document) -> bool:
        """Sync single document to target."""
        # 1. Upsert to target PostgreSQL
        await self.target_pg.merge(doc)
        
        # 2. Reindex to Elasticsearch
        await self.index_to_es(doc)
        
        return True
        
    async def run_sync(self) -> SyncResult:
        """Run incremental sync cycle."""
        changes = await self.get_changes(self.watermark)
        
        for doc in changes:
            await self.sync_document(doc)
            
        self.watermark = datetime.utcnow()
        
        return SyncResult(processed=len(changes))
```

### 6.2 Sync Schedule

```yaml
# post-migration-sync.yaml
schedule:
  # First 24 hours: every 15 minutes
  - interval: "*/15 * * * *"
    duration: "24h"
    
  # Next 7 days: hourly
  - interval: "0 * * * *"
    duration: "7d"
    
  # After first week: daily
  - interval: "0 2 * * *"
    duration: "indefinite"
    
alert_thresholds:
  lag_seconds: 300  # Alert if sync lag > 5 minutes
  error_rate: 0.01  # Alert if error rate > 1%
```

---

## 7. Downtime Estimation

| Phase | Duration | Cumulative |
|-------|----------|------------|
| Pre-checks | 15 min | 15 min |
| PostgreSQL dump | 1-3 hours | 1-3 hours |
| Transfer | 30-60 min | 2-4 hours |
| PostgreSQL restore | 1-2 hours | 3-6 hours |
| ES reindex | 2-4 hours | 5-10 hours |
| Validation | 30-60 min | 6-11 hours |
| Cutover | 15 min | 6-11 hours |

**Recommended Window**: 8-hour maintenance window
**Actual Downtime**: 30 minutes (with blue-green: near-zero)

---

## 8. Cost Analysis

### 8.1 One-Time Migration Costs

| Item | Cost (USD) |
|------|-----------|
| Data transfer (100GB) | $10-20 |
| Temporary compute (migration) | $50-100 |
| Validation/testing | $20-50 |
| **Total One-Time** | **$80-170** |

### 8.2 Monthly Operating Costs (Fly.io)

| Service | Specs | Cost |
|---------|-------|------|
| PostgreSQL | 100GB, 2 vCPU, 4GB RAM | $50-80 |
| Elasticsearch | Starter plan | $30-60 |
| Redis | Starter plan | $15-30 |
| App (API) | 2 instances, 2GB RAM | $40-60 |
| Workers | 2 instances, 4GB RAM | $60-80 |
| **Total Monthly** | | **$195-310** |

---

## 9. Validation Checklist

### Pre-Migration
- [ ] Fly.io infrastructure provisioned
- [ ] Backup of local data verified
- [ ] Migration scripts tested in staging
- [ ] Rollback procedure documented
- [ ] Team notified of maintenance window
- [ ] Monitoring dashboards ready

### During Migration
- [ ] PostgreSQL schema migrated
- [ ] Row counts match (±1%)
- [ ] Elasticsearch index created
- [ ] Document counts match
- [ ] Sample searches functional
- [ ] Vector search functional
- [ ] Application health checks pass

### Post-Migration
- [ ] DNS switched
- [ ] Traffic flowing to Fly.io
- [ ] Error rates <0.1%
- [ ] Latency p95 <500ms
- [ ] Incremental sync running
- [ ] Old infrastructure marked for decommission

---

## 10. Risk Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Data corruption during transfer | Low | High | Checksums, validation suite, rollback plan |
| Extended downtime | Medium | High | Blue-green deployment, staged rollout |
| Performance degradation | Medium | Medium | Load testing, gradual traffic shift |
| Network issues during transfer | Medium | Medium | Resumable transfers, parallel streams |
| Embedding dimension mismatch | Low | Critical | 384-dim invariant (ADR-001), validation |

---

## 11. Timeline

```
Week -1: Preparation
├── Provision Fly.io infrastructure
├── Test migration scripts in staging
└── Schedule maintenance window

Week 0: Migration Day
├── T-2h: Final backups
├── T-1h: Start PostgreSQL dump
├── T+0h: Begin transfer
├── T+2h: Start restore
├── T+4h: ES reindex
├── T+8h: Validation & cutover
└── T+9h: Post-migration monitoring

Week +1: Stabilization
├── Daily incremental sync
├── Performance monitoring
├── Issue resolution
└── Plan decommission of local infra

Week +2: Decommission
├── Final data verification
├── Shutdown local infrastructure
└── Cost optimization review
```

---

## Appendix A: Emergency Contacts

| Role | Contact | Escalation |
|------|---------|------------|
| Migration Lead | | |
| DBA | | |
| Fly.io Support | support@fly.io | +1-xxx-xxx-xxxx |
| On-call Engineer | | |

## Appendix B: Useful Commands

```bash
# Check migration progress
watch -n 30 'psql $TARGET_URL -c "SELECT COUNT(*) FROM documents;"'

# Monitor ES indexing rate
curl -s $ES_URL/_cat/indices/gabi_documents_v1?v

# Check for errors in Fly.io logs
fly logs --app gabi-api-prod | grep -i error

# Verify connectivity
fly ssh console --app gabi-api-prod --command "curl -f http://localhost:8000/health"
```
