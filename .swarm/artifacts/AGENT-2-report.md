# AGENT-2: Database & Storage Setup Report

**Status:** ✅ COMPLETED  
**Timestamp:** 2026-02-08T18:48:28.573Z  
**Agent:** AGENT-2 (Database & Storage)

---

## Summary

Successfully set up PostgreSQL with pgvector, ran all Alembic migrations, and verified Elasticsearch is running with the required index.

---

## Tasks Completed

### 1. AGENT-1 Status Check
- Status file not found, proceeding independently
- No blocking dependencies

### 2. PostgreSQL + pgvector Setup ✅

**Container:** gabi-postgres  
**Image:** pgvector/pgvector:pg17  
**Port:** 5433 → 5432  
**Status:** Running

**Extensions Installed:**
| Extension | Version |
|-----------|---------|
| plpgsql | 1.0 |
| uuid-ossp | 1.1 |
| vector | 0.8.1 |
| pg_trgm | 1.6 |
| pgcrypto | 1.3 |

### 3. Alembic Migrations ✅

**Migrations Applied:**
1. `001_initial_schema` - Base schema with enums, tables, indexes
2. `002_indexes_constraints` - Additional indexes and constraints
3. `003_audit_functions` - Audit log functions
4. `004_create_data_catalog` - Data catalog table
5. `005_source_registry_soft_delete` - Soft delete columns

**Current Version:** `005_source_registry_soft_delete`

### 4. Database Tables Created ✅

| Table | Description |
|-------|-------------|
| alembic_version | Migration tracking |
| audit_log | Immutable audit trail |
| change_detection_cache | Change detection state |
| data_catalog | Data catalog entries |
| dlq_messages | Dead letter queue |
| document_chunks | Document chunks with vector(384) embeddings |
| documents | Main document storage |
| execution_manifests | Pipeline execution tracking |
| lineage_edges | Data lineage edges |
| lineage_nodes | Data lineage nodes |
| source_registry | Data source configuration |

### 5. Elasticsearch Setup ✅

**Container:** gabi-elasticsearch  
**Image:** docker.elastic.co/elasticsearch/elasticsearch:8.11.0  
**Port:** 9200  
**Status:** Green (healthy)

**Index Created:**
- `gabi_documents_v1` - Document search index with BM25 + dense_vector(384)

---

## Fixes Applied

### Migration Fixes

1. **001_initial_schema.py**
   - Changed `sa.Enum` to `postgresql.ENUM` with `create_type=True`
   - Updated column definitions to use `create_type=False` to avoid duplicate type creation

2. **002_indexes_constraints.py**
   - Removed `is_deleted` references from `source_registry` (column added in 005)
   - Removed `NOW()` from partial index predicate (not IMMUTABLE function)
   - Moved `idx_source_status_deleted` index creation to migration 005

3. **005_source_registry_soft_delete.py**
   - Added `IF EXISTS` to `drop_index` operations for safer downgrades

### Configuration Fixes

4. **.env**
   - Changed `GABI_ELASTICSEARCH_URL` from port 9201 to 9200

---

## Verification Commands

```bash
# Check PostgreSQL tables
docker exec gabi-postgres psql -U gabi -d gabi -c "\dt"

# Check pgvector extension
docker exec gabi-postgres psql -U gabi -d gabi -c "SELECT * FROM pg_extension WHERE extname='vector';"

# Check Elasticsearch
curl http://localhost:9200/_cluster/health

# Check ES indices
curl http://localhost:9200/_cat/indices?v
```

---

## Notes

- All database tables include proper indexes for performance
- Vector dimensionality set to 384 (ADR-001 compliance)
- HNSW index created on `document_chunks.embedding` for fast similarity search
- Elasticsearch configured with Brazilian Portuguese analyzers
- Soft delete pattern implemented across relevant tables
- Audit log table is immutable (no UPDATE/DELETE permissions)

---

## Next Steps for Other Agents

- **AGENT-3** (Vector Store): Can now use `document_chunks` table with vector(384)
- **AGENT-4** (API Server): Can connect to PostgreSQL on port 5433 and ES on port 9200
- **AGENT-5** (Chat Interface): Can query documents via ES and vector search
