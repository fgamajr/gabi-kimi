#!/usr/bin/env python3
"""
GABI Migration - Phase 5: Post-Migration Validation

Comprehensive validation suite to verify data integrity after migration.
"""

import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

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

# Use target PG as source for comparison if available
COMPARISON_PG_URL = TARGET_PG_URL or SOURCE_PG_URL


@dataclass
class ValidationResult:
    """Result of a single validation check."""
    name: str
    passed: bool
    details: str
    severity: str = "info"  # "error", "warning", "info"
    metric: Optional[float] = None


@dataclass
class ValidationReport:
    """Complete validation report."""
    results: List[ValidationResult] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    def add(self, result: ValidationResult) -> None:
        self.results.append(result)
    
    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)
    
    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)
    
    @property
    def error_count(self) -> int:
        return sum(1 for r in self.results if not r.passed and r.severity == "error")
    
    @property
    def warning_count(self) -> int:
        return sum(1 for r in self.results if not r.passed and r.severity == "warning")
    
    def print_report(self) -> bool:
        """Print validation report. Returns True if no errors."""
        print("\n" + "=" * 70)
        print("MIGRATION VALIDATION REPORT")
        print("=" * 70)
        
        for result in self.results:
            status = "✓" if result.passed else "⚠" if result.severity == "warning" else "✗"
            color = "\033[92m" if result.passed else "\033[93m" if result.severity == "warning" else "\033[91m"
            reset = "\033[0m"
            
            print(f"{color}{status}{reset} [{result.severity.upper()}] {result.name}")
            print(f"    {result.details}")
        
        print("-" * 70)
        print(f"Total checks: {len(self.results)}")
        print(f"  Passed: {self.passed_count}")
        print(f"  Warnings: {self.warning_count}")
        print(f"  Errors: {self.error_count}")
        
        if self.error_count > 0:
            print("\n\033[91m" + "=" * 70)
            print("CRITICAL ERRORS DETECTED - DO NOT PROCEED WITH CUTOVER")
            print("=" * 70 + "\033[0m")
            return False
        elif self.warning_count > 0:
            print("\n\033[93m" + "=" * 70)
            print("Warnings present - review before cutover")
            print("=" * 70 + "\033[0m")
            return True
        else:
            print("\n\033[92m" + "=" * 70)
            print("All checks passed - ready for cutover")
            print("=" * 70 + "\033[0m")
            return True


class MigrationValidator:
    """Validates migrated data consistency."""
    
    def __init__(self, pg_url: str, es_url: str):
        self.pg_url = pg_url
        self.es_url = es_url
        self.report = ValidationReport()
        
    async def _get_pg_engine(self):
        """Create PostgreSQL engine."""
        from sqlalchemy.ext.asyncio import create_async_engine
        return create_async_engine(self.pg_url, echo=False)
    
    async def _get_es_client(self):
        """Create Elasticsearch client."""
        from elasticsearch import AsyncElasticsearch
        return AsyncElasticsearch([self.es_url])
    
    async def validate_postgresql(self) -> None:
        """Validate PostgreSQL data integrity."""
        logger.info("Validating PostgreSQL...")
        
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy.orm import sessionmaker
        
        engine = await self._get_pg_engine()
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        
        try:
            async with async_session() as session:
                # 1. Table row counts
                tables = [
                    ("documents", "is_deleted = false"),
                    ("document_chunks", "deleted_at IS NULL"),
                    ("source_registry", "deleted_at IS NULL"),
                    ("execution_manifests", None),
                    ("dlq_messages", None),
                ]
                
                for table, condition in tables:
                    query = f"SELECT COUNT(*) FROM {table}"
                    if condition:
                        query += f" WHERE {condition}"
                    
                    result = await session.execute(text(query))
                    count = result.scalar()
                    
                    self.report.add(ValidationResult(
                        name=f"pg_{table}_count",
                        passed=count is not None,
                        details=f"{table}: {count or 0} rows",
                        severity="error" if count is None else "info",
                    ))
                
                # 2. Orphan chunks check
                result = await session.execute(text("""
                    SELECT COUNT(*) FROM document_chunks dc
                    LEFT JOIN documents d ON dc.document_id = d.document_id
                    WHERE d.document_id IS NULL AND dc.deleted_at IS NULL
                """))
                orphan_count = result.scalar() or 0
                
                self.report.add(ValidationResult(
                    name="pg_orphan_chunks",
                    passed=orphan_count == 0,
                    details=f"Orphan chunks: {orphan_count}",
                    severity="error" if orphan_count > 0 else "info",
                ))
                
                # 3. Embedding model consistency
                result = await session.execute(text("""
                    SELECT embedding_model, COUNT(*) as cnt
                    FROM document_chunks
                    WHERE embedding IS NOT NULL
                    GROUP BY embedding_model
                    ORDER BY cnt DESC
                """))
                models = result.fetchall()
                
                for model, count in models:
                    self.report.add(ValidationResult(
                        name=f"pg_embeddings_{model or 'null'}",
                        passed=True,
                        details=f"Model '{model}': {count} embeddings",
                        severity="info",
                    ))
                
                # 4. Documents without chunks
                result = await session.execute(text("""
                    SELECT COUNT(*) FROM documents d
                    WHERE d.is_deleted = false
                    AND d.chunks_count = 0
                """))
                no_chunks = result.scalar() or 0
                
                self.report.add(ValidationResult(
                    name="pg_docs_without_chunks",
                    passed=no_chunks == 0,
                    details=f"Documents without chunks: {no_chunks}",
                    severity="warning" if no_chunks > 0 else "info",
                ))
                
                # 5. Embedding dimension check
                result = await session.execute(text("""
                    SELECT 
                        MIN(array_length(embedding, 1)) as min_dim,
                        MAX(array_length(embedding, 1)) as max_dim,
                        COUNT(*) as total
                    FROM document_chunks
                    WHERE embedding IS NOT NULL
                    LIMIT 1000
                """))
                dim_row = result.fetchone()
                
                if dim_row:
                    min_dim, max_dim, total = dim_row
                    dim_ok = min_dim == 384 and max_dim == 384
                    self.report.add(ValidationResult(
                        name="pg_embedding_dimensions",
                        passed=dim_ok,
                        details=f"Embedding dims: min={min_dim}, max={max_dim} (expected 384)",
                        severity="error" if not dim_ok else "info",
                    ))
                
                # 6. Fingerprint uniqueness
                result = await session.execute(text("""
                    SELECT COUNT(DISTINCT fingerprint), COUNT(fingerprint)
                    FROM documents
                    WHERE is_deleted = false
                """))
                distinct_count, total_count = result.fetchone()
                dup_rate = 1 - (distinct_count / total_count) if total_count > 0 else 0
                
                self.report.add(ValidationResult(
                    name="pg_fingerprint_uniqueness",
                    passed=dup_rate < 0.1,  # Allow up to 10% duplicates (revisions)
                    details=f"Unique fingerprints: {distinct_count}/{total_count} ({dup_rate*100:.1f}% duplicates)",
                    severity="warning" if dup_rate > 0.1 else "info",
                    metric=dup_rate,
                ))
                
        finally:
            await engine.dispose()
    
    async def validate_elasticsearch(self) -> None:
        """Validate Elasticsearch index."""
        logger.info("Validating Elasticsearch...")
        
        es = await self._get_es_client()
        
        try:
            # 1. Cluster health
            try:
                health = await es.cluster.health()
                status = health["status"]
                self.report.add(ValidationResult(
                    name="es_cluster_health",
                    passed=status in ["green", "yellow"],
                    details=f"Cluster status: {status}",
                    severity="error" if status == "red" else "warning" if status == "yellow" else "info",
                ))
            except Exception as e:
                self.report.add(ValidationResult(
                    name="es_cluster_health",
                    passed=False,
                    details=f"Failed to get cluster health: {e}",
                    severity="error",
                ))
                return
            
            # 2. Index exists
            exists = await es.indices.exists(index=ES_INDEX)
            self.report.add(ValidationResult(
                name="es_index_exists",
                passed=exists,
                details=f"Index '{ES_INDEX}' {'exists' if exists else 'MISSING'}",
                severity="error" if not exists else "info",
            ))
            
            if not exists:
                return
            
            # 3. Index stats
            try:
                stats = await es.indices.stats(index=ES_INDEX)
                doc_count = stats["indices"][ES_INDEX]["total"]["docs"]["count"]
                store_size = stats["indices"][ES_INDEX]["total"]["store"]["size_in_bytes"]
                
                self.report.add(ValidationResult(
                    name="es_document_count",
                    passed=doc_count > 0,
                    details=f"ES documents: {doc_count} ({store_size / 1024 / 1024:.1f} MB)",
                    severity="error" if doc_count == 0 else "info",
                ))
            except Exception as e:
                self.report.add(ValidationResult(
                    name="es_document_count",
                    passed=False,
                    details=f"Failed to get index stats: {e}",
                    severity="error",
                ))
            
            # 4. Basic search
            try:
                search_result = await es.search(
                    index=ES_INDEX,
                    body={"query": {"match_all": {}}, "size": 1},
                    timeout="10s",
                )
                has_hits = search_result["hits"]["total"]["value"] > 0
                
                self.report.add(ValidationResult(
                    name="es_search_basic",
                    passed=has_hits,
                    details="Basic search returns results" if has_hits else "Search returned no results",
                    severity="error" if not has_hits else "info",
                ))
            except Exception as e:
                self.report.add(ValidationResult(
                    name="es_search_basic",
                    passed=False,
                    details=f"Search failed: {e}",
                    severity="error",
                ))
            
            # 5. BM25 search
            try:
                bm25_result = await es.search(
                    index=ES_INDEX,
                    body={
                        "query": {"match": {"content": "tribunal"}},
                        "size": 5,
                    },
                    timeout="10s",
                )
                bm25_ok = bm25_result["hits"]["total"]["value"] > 0
                
                self.report.add(ValidationResult(
                    name="es_search_bm25",
                    passed=bm25_ok,
                    details=f"BM25 search: {bm25_result['hits']['total']['value']} results",
                    severity="warning" if not bm25_ok else "info",
                ))
            except Exception as e:
                self.report.add(ValidationResult(
                    name="es_search_bm25",
                    passed=False,
                    details=f"BM25 search failed: {e}",
                    severity="warning",
                ))
            
            # 6. Vector search (if embeddings exist)
            try:
                vector_result = await es.search(
                    index=ES_INDEX,
                    body={
                        "query": {
                            "script_score": {
                                "query": {"match_all": {}},
                                "script": {
                                    "source": "cosineSimilarity(params.query_vector, 'content_vector') + 1.0",
                                    "params": {"query_vector": [0.01] * 384}
                                }
                            }
                        },
                        "size": 5,
                    },
                    timeout="10s",
                )
                vector_ok = vector_result["hits"]["total"]["value"] > 0
                
                self.report.add(ValidationResult(
                    name="es_search_vector",
                    passed=vector_ok,
                    details=f"Vector search: {vector_result['hits']['total']['value']} results",
                    severity="warning" if not vector_ok else "info",
                ))
            except Exception as e:
                self.report.add(ValidationResult(
                    name="es_search_vector",
                    passed=False,
                    details=f"Vector search failed (embeddings may not be indexed): {e}",
                    severity="warning",
                ))
                
        finally:
            await es.close()
    
    async def validate_cross_store_consistency(self) -> None:
        """Validate consistency between PostgreSQL and Elasticsearch."""
        logger.info("Validating cross-store consistency...")
        
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy.orm import sessionmaker
        
        engine = await self._get_pg_engine()
        es = await self._get_es_client()
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        
        try:
            async with async_session() as session:
                # Get PG document count
                result = await session.execute(
                    text("SELECT COUNT(*) FROM documents WHERE is_deleted = false")
                )
                pg_count = result.scalar() or 0
            
            # Get ES document count
            try:
                stats = await es.indices.stats(index=ES_INDEX)
                es_count = stats["indices"][ES_INDEX]["total"]["docs"]["count"]
            except:
                es_count = 0
            
            diff = abs(pg_count - es_count)
            diff_pct = (diff / pg_count * 100) if pg_count > 0 else 0
            
            self.report.add(ValidationResult(
                name="cross_store_document_count",
                passed=diff_pct < 5.0,  # Allow 5% difference during migration
                details=f"PG: {pg_count}, ES: {es_count}, Diff: {diff} ({diff_pct:.2f}%)",
                severity="error" if diff_pct > 10 else "warning" if diff_pct > 5 else "info",
                metric=diff_pct,
            ))
            
            # Sample document comparison
            if pg_count > 0 and es_count > 0:
                async with async_session() as session:
                    # Get sample documents from PG
                    result = await session.execute(
                        text("""
                            SELECT document_id, title, fingerprint
                            FROM documents
                            WHERE is_deleted = false
                            ORDER BY random()
                            LIMIT 10
                        """)
                    )
                    samples = result.fetchall()
                    
                    matched = 0
                    for doc_id, title, fp in samples:
                        try:
                            es_doc = await es.get(index=ES_INDEX, id=doc_id)
                            if es_doc["found"]:
                                matched += 1
                        except:
                            pass
                    
                    match_rate = matched / len(samples) if samples else 0
                    self.report.add(ValidationResult(
                        name="cross_store_sample_match",
                        passed=match_rate >= 0.8,  # At least 80% of samples match
                        details=f"Sample match rate: {matched}/{len(samples)} ({match_rate*100:.1f}%)",
                        severity="error" if match_rate < 0.5 else "warning" if match_rate < 0.8 else "info",
                        metric=match_rate,
                    ))
                    
        finally:
            await engine.dispose()
            await es.close()
    
    async def run_all_validations(self) -> ValidationReport:
        """Run all validation checks."""
        self.report.start_time = datetime.now()
        
        await self.validate_postgresql()
        
        if self.es_url:
            await self.validate_elasticsearch()
            await self.validate_cross_store_consistency()
        else:
            logger.warning("Skipping ES validation - TARGET_ES_URL not set")
        
        self.report.end_time = datetime.now()
        return self.report


async def main():
    """Main entry point."""
    # Validate configuration
    if not TARGET_PG_URL:
        print("Warning: TARGET_PG_URL not set, using SOURCE_PG_URL for validation")
    
    pg_url = TARGET_PG_URL or SOURCE_PG_URL
    es_url = TARGET_ES_URL
    
    logger.info(f"Validating target: PG={pg_url}, ES={es_url or 'N/A'}")
    
    validator = MigrationValidator(pg_url, es_url)
    report = await validator.run_all_validations()
    
    success = report.print_report()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
