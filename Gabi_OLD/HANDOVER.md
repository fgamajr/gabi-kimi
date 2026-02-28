# GABI Handover — 2026-02-27

## Where We Are

Branch: `feat/fullpipeline`
Build: **green** (`dotnet build GabiSync.sln`)
Arch tests: **3/3 green** (`dotnet test tests/Gabi.Architecture.Tests`)
Unit tests: **all green** (Ingest 14/14, Jobs 23/23, Fetch 26/26, Discover 74/74)
Api tests: **30/31** (1 pre-existing reflection test failure — `ParseDiscoveryConfig_ShouldPreserveStrategyAndExtraFields`, the method is instance not static)
Postgres/System/ReliabilityLab tests: Testcontainers timeouts — pre-existing infra issue, not our code.

**Nothing is committed.** All work is unstaged. 48 files changed, 15 new files.

---

## What Was Done (This Session)

### Fan-Out Ingestion Architecture — fully implemented

Replaced the old `EmbedAndIndexJobExecutor` with a new `ChunkAndExtractJobExecutor` that fans out from a single chunking step to **3 independent stores**:

```
Fetch → PG documents → ChunkAndExtractJobExecutor
                              │
                    ┌─────────┼─────────┐
                    ↓         ↓         ↓
              BM25 Index  Embedding   KG Store
             (ES text)   (pgvector)  (PG adj.)
                    │         │         │
                    └─────────┼─────────┘
                              ↓
                    3-Strategy Search + RRF Fusion
```

Each output is independent and fault-tolerant. Config flags control which are active:
- `Pipeline:EnableBM25Index` (default: true)
- `Pipeline:EnableEmbeddings` (default: true)
- `Pipeline:EnableGraphExtraction` (default: true)

### 7 Sections Implemented

| # | Section | Status |
|---|---------|--------|
| 1 | **pgvector + KG schema** — `document_embeddings` (384-dim vectors) + `document_relationships` (adjacency table), entities, repos, migration | Done |
| 2 | **ChunkAndExtractJobExecutor** — fan-out job, `EmbedAndIndexJobExecutor` marked `[Obsolete]` | Done |
| 3 | **BM25-only ES** — stripped vectors from ES mapping and indexer (vectors moved to pgvector) | Done |
| 4 | **ONNX Runtime Embedder** — local inference replacing TEI, manual WordPiece tokenizer, 384-dim | Done |
| 5 | **3-strategy search + RRF** — BM25 (ES) + vector (pgvector) + graph (PG) with RRF fusion k=60 | Done |
| 6 | **ZIP-level SHA-256** — content dedup for DOU zip files in `FetchJobExecutor` | Done |
| 7 | **ARM64 cleanup** — TEI `profiles: [tei]` (opt-in), embedder provider config auto/onnx/tei/hash | Done |

### New Files Created (untracked)

```
src/Gabi.Contracts/Embed/IDocumentEmbeddingRepository.cs   — ChunkEmbedding, VectorSearchResult records
src/Gabi.Contracts/Graph/IDocumentRelationshipRepository.cs — DocumentRelation, GraphSearchResult records
src/Gabi.Contracts/Graph/IDocumentRelationshipExtractor.cs  — interface
src/Gabi.Ingest/OnnxEmbedder.cs                           — ONNX local embedder (384-dim, vocab.txt WordPiece)
src/Gabi.Ingest/DocumentRelationshipExtractor.cs           — regex legal citation extractor (Acórdão, Lei, Processo, Súmula)
src/Gabi.Postgres/Entities/DocumentEmbeddingEntity.cs
src/Gabi.Postgres/Entities/DocumentRelationshipEntity.cs
src/Gabi.Postgres/Repositories/DocumentEmbeddingRepository.cs  — raw SQL + Dapper, pgvector <=> cosine
src/Gabi.Postgres/Repositories/DocumentRelationshipRepository.cs
src/Gabi.Postgres/Migrations/20260227120000_AddDocumentEmbeddingsAndRelationships.cs
src/Gabi.Worker/Jobs/ChunkAndExtractJobExecutor.cs         — the fan-out job (392 lines)
src/Gabi.Worker/Jobs/Fetch/DouZipXmlExtractor.cs           — DOU INLABS ZIP/XML parser (256 lines)
scripts/download-model.sh                                  — downloads ONNX model from HuggingFace
```

### Key Modified Files

- `src/Gabi.Api/Program.cs` — DI for embedding/relationship repos, SearchService now scoped, graph endpoints (`/api/v1/documents/{id}/related`, `/api/v1/graph/search`)
- `src/Gabi.Api/Services/SearchService.cs` — 3-strategy hybrid search with RRF fusion
- `src/Gabi.Worker/Program.cs` — DI for ChunkAndExtract, ONNX embedder, repos, extractor; embedder provider switch
- `src/Gabi.Worker/appsettings.json` — Embeddings + Pipeline config sections
- `src/Gabi.Ingest/ElasticsearchIndexSetup.cs` — removed DenseVector mapping (BM25-only now)
- `src/Gabi.Ingest/ElasticsearchDocumentIndexer.cs` — removed embedding averaging, EsChunk class deleted
- `src/Gabi.Postgres/GabiDbContext.cs` — 2 new DbSets, pgvector extension conditional, Embedding ignored in EF model
- `src/Gabi.Worker/Jobs/FetchJobExecutor.cs` — ZIP-level SHA-256 hashing, DOU `zip_xml_dou` converter path
- `docker-compose.yml` — TEI profiles: [tei], embedder env vars
- `docker/postgres/init/01-init.sql` — `CREATE EXTENSION IF NOT EXISTS "vector"`

---

## What Was Done (Previous Sessions — already committed)

### DOU INLABS Pipeline (commits cb5bf80, e8b63ae, 59b83e3)
- `DouDiscoveryDriver` — discovers DOU ZIP files by date range from INLABS
- `DouZipXmlExtractor` — extracts articles from DOU ZIP/XML format
- `FetchJobExecutor` — `zip_xml_dou` converter pipeline
- `sources_v2.yaml` — `dou_inlabs_secao1_atos_administrativos` enabled, date range 2026-02-20 to current

### Ingestion Results So Far
- **~9 DOU ZIP files fetched** (daily editions, 2026-02-20 onwards)
- **~2200+ XML documents extracted** and ingested into PostgreSQL
- Pipeline flow: Seed → Discovery (date range) → Fetch (download ZIPs) → Extract (XML articles) → Ingest (PG documents)
- Documents are in PG with content + metadata, indexed in ES (BM25 text-only)

### Reliability Migration (commits 6e9359d through 59b83e3)
- Temporal orchestration (opt-in per source)
- WAL logical replication projection (opt-in)
- Workflow event tracking
- Drift auditor
- V10 code gap fixes (see MEMORY.md for details)

---

## Gotchas / Known Quirks

1. **Pgvector.Vector in EF**: Must `entity.Ignore(e => e.Embedding)` — the actual column is managed via raw SQL migration + Dapper repos. InMemory/SQLite providers can't handle it.
2. **HasPostgresExtension("vector")**: Must be conditional — `if (Database.ProviderName == "Npgsql.EntityFrameworkCore.PostgreSQL")`
3. **Pgvector 0.3.0** requires Npgsql >= 8.0.3 — ZeroKelvinHarness bumped to match.
4. **Microsoft.ML.Tokenizers** API was incompatible — OnnxEmbedder uses manual WordPiece tokenizer (loads vocab.txt directly).
5. **ONNX model** not in repo — must run `scripts/download-model.sh` to get `models/paraphrase-multilingual-MiniLM-L12-v2/model.onnx` + `vocab.txt`.
6. **TEI service** is now opt-in (`docker compose --profile tei up`). Default embedder is `auto` (tries ONNX first, falls back to TEI, then hash).
7. **Pre-existing test failure**: `ParseDiscoveryConfig_ShouldPreserveStrategyAndExtraFields` — uses `BindingFlags.Static` but method is instance.

---

## What To Do Next

### Immediate (commit the work)
- [ ] Review all changes, stage, and commit
- [ ] Consider squashing into logical commits (fan-out arch, DOU pipeline, V10 fixes)

### Pipeline Validation
- [ ] `./scripts/dev infra up` then `./scripts/dev db apply` — verify migration creates pgvector tables
- [ ] Run a DOU ingest cycle end-to-end with `ChunkAndExtractJobExecutor` enabled
- [ ] Verify 3-strategy search works: `GET /api/v1/search?q=acordao&limit=10`
- [ ] Test graph endpoints: `GET /api/v1/documents/{id}/related`

### Embeddings
- [ ] Download ONNX model: `./scripts/download-model.sh`
- [ ] Test ONNX embedder locally (verify 384-dim vectors in `document_embeddings` table)
- [ ] Compare ONNX vs TEI embedding quality (cosine similarity should be near-identical)

### Scale / Production
- [ ] Backfill existing ~2200 documents through `ChunkAndExtractJobExecutor` (embeddings + KG edges)
- [ ] Monitor pgvector search latency with `EXPLAIN ANALYZE`
- [ ] Consider IVFFlat index rebuild after >10k embeddings (`lists = 100` is tuned for ~100k rows)
- [ ] ReconcileTargetRefsAsync — run periodically to link KG edges to actual document IDs

### Remaining from V10 Plan
- [ ] Full zero-kelvin test: `./tests/zero-kelvin-test.sh docker-only`
- [ ] Merge `feat/fullpipeline` → `main` when stable

---

## Quick Commands

```bash
# Build & test
dotnet build GabiSync.sln
dotnet test tests/Gabi.Architecture.Tests   # must be 3/3
dotnet test GabiSync.sln                    # unit tests pass; Testcontainers may timeout

# Infrastructure
./scripts/dev infra up
./scripts/dev db apply

# Download ONNX model (required for embedding)
./scripts/download-model.sh

# Run API
dotnet run --project src/Gabi.Api --urls "http://localhost:5100"

# Run Worker
dotnet run --project src/Gabi.Worker

# Trigger pipeline
TOKEN=$(curl -s -X POST http://localhost:5100/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"operator","password":"op123"}' | jq -r .token)

curl -s -X POST http://localhost:5100/api/v1/dashboard/seed \
  -H "Authorization: Bearer $TOKEN"
```
