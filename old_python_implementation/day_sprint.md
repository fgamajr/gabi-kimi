# Day Sprint Plan

## 🎯 Goal
Stabilize the infrastructure, clean up technical debt, and implement the core feature set (API matching frontend, Hybrid Search) to prepare for production deployment.

## 🌅 Morning: Infrastructure & Stability

### 0. Fix Environment Consistency (NEW - Priority Critical) ✅ DONE
**Problem**: Cross-checks produce different problems each session due to state residue.
- **Causes**: Docker orphans, systemd conflicts, Python cache, zombie processes, working directory issues, environment leakage.
- **Action**: Implement scripts defensivos conforme `docs/plans/2026-02-12-environment-stability-plan.md`:
    - ✅ `scripts/infra_reset.sh`: Hard reset completo (Docker + dados + cache)
    - ✅ `scripts/check_prerequisites.sh`: Valida portas e resolve conflitos systemd
    - ✅ `scripts/kill_zombies.sh`: Mata processos GABI/Celery/uvicorn pendentes
    - ✅ `scripts/setup_env.sh`: Configura ambiente limpo (sem leakage)
    - ✅ `scripts/dev.sh`: Orquestrador unificado (`reset`, `infra-up`, `ingest`, etc.)
- **Benefit**: Reproducibilidade garantida - qualquer pessoa pode rodar `dev.sh reset && dev.sh infra-up && dev.sh ingest tcu_normas` e obter o mesmo resultado.
- **Success Criteria**: 5 cross-checks consecutivos produzem resultados idênticos.

### 0.1 Fix Memory Leak & Add ES Reindex (NEW - Priority High) ✅ DONE
**Problem 1 - Memory**: Ingestion memory grows to ~1.9GB instead of staying constant at ~200MB
- **Root Cause**: Objects (parsed_doc, chunking_result, embedding_result) not being freed after processing
- **Solution**: Added `del` statements and `gc.collect()` in `src/gabi/tasks/sync.py`
- **Files**: `scripts/fix_memory_sync.py` (patch applied)

**Problem 2 - ES Indexing**: Pipeline saves to PostgreSQL but NOT to Elasticsearch
- **Root Cause**: `_index_document()` only saves to PG, ES indexing is decoupled by design
- **Solution**: Created separate reindexing script `scripts/reindex_to_es.py`
- **Usage**: `./scripts/dev.sh reindex tcu_normas` or `python scripts/reindex_to_es.py --source tcu_normas`

**Cross-Check Results**:
- ✅ Test B (100 docs): Pipeline works end-to-end (Discovery → Parsing → Chunking → Embedding → PG)
- ✅ ES Reindex: Working - 10 docs indexed successfully (11 total in ES including test doc)
- ⚠️ Memory: Still high (~300MB) but improved with gc.collect() - needs more investigation
- ✅ Architecture: Decoupled ES indexing confirmed working via separate script

### 1. Refactor Infrastructure Scripts
Currently, `start.sh` is destructive and mixes concerns. We need to separate "Infrastructure" from "Application".
- **Action**: Split `scripts/start.sh` into:
    - `scripts/infra_manager.sh`: Handles Docker containers (Postgres, ES, Redis, TEI).
        - Commands: `up` (start without destroy), `down` (stop), `reset` (destructive rebuild).
    - `scripts/dev_server.sh`: Starts the API and Celery worker locally.
- **Benefit**: restart the API/Worker without losing ingested data.
- **Dependency**: Reutilizar lógica dos scripts defensivos criados na tarefa 0.

### 2. Cleanup & Consolidation
Delete temporary test files and consolidate useful logic into the codebase.
- **Migrate Logic**:
    - Move `EnhancedMCPTools` from `mcp_migration.py` to `src/gabi/mcp/tools.py`.
    - Save ingestion monitoring logic from `monitor_ingestion_v2.py` to `scripts/monitor_ingestion.py`.
- **Delete Files**:
    - `mcp_migration.py` (after migration)
    - `monitor_celery.sh`, `monitor_crashes.sh`, `monitor_tei.sh`, `monitor_ingestion.sh`
    - `test_aiohttp_streaming.py`, `test_csv_parse.py`, `test_direct_sync.py`, `test_httpx_minimal.py`, `test_streaming_fix.py`, `test_streaming.py`

### 3. Fix Streaming Ingestion (Priority)
Resolve the `httpx.ReadError` to enable ingestion of large sources like `tcu_normas`.
- **Insight**: `test_httpx_minimal.py` proved `httpx` works with specific timeout settings (`read=None`).
- **Action**: Refactor `fetcher.py` to strictly replicate the successful client configuration from the minimal test, ensuring proper lifecycle management of the async client.

## ☀️ Mid-Day: API & Frontend Connection

### 4. API Refactoring
Match the backend API to the frontend requirements (`user-first-view` project).
- **Tasks**:
    - Analyze frontend API calls.
    - Create/Update Pydantic models in `src/gabi/schemas/`.
    - Implement/Update endpoints in `src/gabi/api/`.
    - Add Pipeline Control endpoints (Start/Stop/Status) to manage ingestion from UI.

### 5. Connect Frontend
- **Tasks**:
    - Configure CORS in `main.py`.
    - Test end-to-end flow: Frontend -> API -> Celery -> DB.

## 🌤️ Afternoon: Search & Intelligence

### 6. Hybrid Search Implementation
Implement the advanced search capabilities designed in `mcp_migration.py`.
- **Features**:
    - **Exact Match**: Elasticsearch boolean queries for filters (ano, numero, etc.).
    - **Semantic Search**: Vector search using `paraphrase-multilingual-MiniLM-L12-v2`.
    - **Hybrid Search**: RRF (Reciprocal Rank Fusion) to combine results.
- **Action**: Implement `SearchService` in `src/gabi/services/search.py` and expose via API/MCP.

## 🌙 Evening: Production Prep

### 7. Deployment Configuration
Prepare for Fly.io.
- **Tasks**:
    - Create `Dockerfile` optimized for production (multi-stage build).
    - Create `fly.toml` with volume configuration for persistence.
    - Set up GitHub Actions for CI/CD (optional, or manual deploy first).

## 🔬 Research & Innovation (New)
*Study & Proof of Concept for "Future-Proofing" GABI*

### 8. Graph AI ("Legislative Neural Net")
- **Goal**: Understand relationships (citations, revokations) beyond text keywords.
- **Action**: Research GraphRAG, Neo4j, or easy ways to implement a graph layer over the existing vector data.

### 9. Agentic AI ("Autonomous Auditors")
- **Goal**: Specialized MCP agents that perform tasks (e.g., check CPF availability, validate CNPJ status with Receita Federal API).
- **Action**: Design a prototype MCP tool that goes beyond search and *acts* on external systems.

### 10. Zero-Knowledge Proofs ("The Invisible Audit")
- **Goal**: Verify truth without revealing data (e.g., "Company has capital > X" without seeing the balance).
- **Action**: Research ZK-SNARKs or simple cryptographic proofs applicable to audit evidence (privacy-preserving verification).

### 11. Causal AI ("The 'Why' Engine")
- **Goal**: Move from correlation to causation (explaining *why* an anomaly occurred).
- **Action**: Research methods to link specific Acórdãos/Normas to statistical changes in spending data (causal inference).

## ✅ Cross-Check Task: Verify Streaming Implementation Claim

**Objective**: Independently verify that the TRUE streaming implementation for `tcu_normas` works end-to-end.

**Background**: A claim was made that the streaming implementation successfully ingests the 587MB `tcu_normas` CSV with constant memory (~200MB) using a queue-based architecture with UTF-8 incremental decoding.

> ⚠️ **Note on Session Inconsistencies**: Previous cross-checks revealed inconsistent behavior between sessions, caused by:
> 1. **Docker state residue** (stopped containers, orphan networks, volumes not fully removed)
> 2. **Systemd service conflicts** (Redis/PostgreSQL on host competing with Docker ports)
> 3. **Python cache** (`__pycache__`, `.pyc` files persisting code changes)
> 4. **Port conflicts** from previous API/Celery processes not cleaned up
> 5. **Working directory issues** (Celery/Worker started from wrong directory)
> 6. **Environment variable leakage** between shell sessions

### Cross-Check Procedure (Reproducible)

**Phase 1: Clean Slate - Hard Reset**
```bash
# 1. Full Docker cleanup (aggressive)
docker compose --profile infra --profile all down -v --remove-orphans 2>/dev/null || true
docker system prune -f --volumes 2>/dev/null || true

# 2. Kill any lingering processes
sudo fuser -k 8000/tcp 2>/dev/null || true
sudo fuser -k 5432/tcp 2>/dev/null || true
sudo fuser -k 6379/tcp 2>/dev/null || true

# 3. Stop host services that conflict
sudo systemctl stop redis-server postgresql 2>/dev/null || true

# 4. Clean Python cache
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true

# 5. Clean data directories
sudo rm -rf data/postgres/* data/elasticsearch/* data/redis/* 2>/dev/null || true
mkdir -p data/{postgres,elasticsearch,redis,tei/model}
chmod 777 data/elasticsearch
```

**Phase 2: Infrastructure Bootstrap**
```bash
# Run the destructive start script
./scripts/start.sh
# Or manually:
docker compose --profile infra up -d
# Wait for healthy status
docker ps --format 'table {{.Names}}\t{{.Status}}'
```

**Phase 3: Configuration Verification**
```bash
# Verify sources.yaml has streaming settings
grep -A5 "tcu_normas:" sources.yaml | grep -E "(streaming|max_size)"
# Expected: max_size_mb: 1024, streaming: true
```

**Phase 4: Full Ingestion (No Limits)**
```bash
# Option A: Via start_ingestion.sh (synchronous, blocking)
INGEST_SOURCE=tcu_normas \
MAX_DOCS_PER_SOURCE=0 \
INGEST_MODE=sync \
SOURCE_TIMEOUT_SECONDS=7200 \
./scripts/start_ingestion.sh

# Option B: Via CLI directly (manual control)
source .venv/bin/activate
export PYTHONPATH=src
python -m gabi.cli ingest --source tcu_normas --max-docs-per-source 0
```

**Phase 5: Monitor All Pipeline Phases**
```bash
# Terminal 1: Watch memory usage
watch -n 5 'ps aux | grep -E "(python|celery)" | grep -v grep'

# Terminal 2: Watch document count growth
watch -n 10 'docker exec gabi-postgres psql -U gabi -d gabi -c "SELECT source_id, COUNT(*) FROM documents WHERE source_id = '"'"'tcu_normas'"'"' GROUP BY source_id;"'

# Terminal 3: Watch logs
tail -f logs/ingestion_*.log
```

**Phase 6: Validation Checklist**
- [ ] **Discovery Phase**: CSV URL found and accessible
- [ ] **Streaming Fetch**: Memory stays <300MB throughout download
- [ ] **Parsing Phase**: CSV rows parsed incrementally without loading full file
- [ ] **Processing Phase**: Fingerprint → Dedup → Chunking completes
- [ ] **Embedding Phase**: TEI generates embeddings without OOM
- [ ] **Indexing Phase**: Documents in PostgreSQL, vectors in Elasticsearch

**Phase 7: Final Verification**
```bash
# Document count (expected: ~16,000)
docker exec gabi-postgres psql -U gabi -d gabi -c \
  "SELECT COUNT(*) FROM documents WHERE source_id = 'tcu_normas';"

# Chunks with embeddings
docker exec gabi-postgres psql -U gabi -d gabi -c \
  "SELECT COUNT(*) FROM document_chunks 
   WHERE document_id IN (SELECT id FROM documents WHERE source_id = 'tcu_normas')
   AND embedding IS NOT NULL;"

# Hybrid search test
curl -X POST http://localhost:8000/api/v1/search/hybrid \
  -H "Content-Type: application/json" \
  -d '{"query": "normas jurídicas TCU", "limit": 10}'
```

**Success Criteria**:
- All ~16,000 documents ingested successfully
- Memory usage remained constant (~200-300MB) regardless of file size
- No "Event loop is closed" or "httpx.ReadError" errors
- Full pipeline phases complete without manual intervention
- Hybrid search returns relevant results

### Code Verification (Already Completed)
- ✅ Queue-based streaming fetcher ([fetcher.py:1279-1463](src/gabi/pipeline/fetcher.py#L1279-L1463))
- ✅ UTF-8 incremental decoder ([fetcher.py:1397-1410](src/gabi/pipeline/fetcher.py#L1397-L1410))
- ✅ CSV streaming parser ([parser.py:896-1116](src/gabi/pipeline/parser.py#L896-L1116))
- ✅ Full pipeline integration ([sync.py:554-700](src/gabi/tasks/sync.py#L554-L700))
- ✅ Memory monitoring ([sync.py:66-200](src/gabi/tasks/sync.py#L66-L200))

## 📝 Success Criteria (Definition of Done)
1. Dev environment can be restarted without data loss.
2. `tcu_normas` (587MB) ingested successfully via streaming (verified by cross-check task above).
3. Frontend shows real data and controls the pipeline.
4. Hybrid search returns relevant results for complex queries.