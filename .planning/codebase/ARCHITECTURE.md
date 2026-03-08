# Architecture

**Analysis Date:** 2026-03-08

## Pattern Overview

**Overall:** Pipeline-oriented data platform with a search API layer

**Key Characteristics:**
- Backend-heavy Python system for ingesting Brazilian government legal publications (Diario Oficial da Uniao / DOU)
- Multi-phase data pipeline: discover -> download -> parse -> normalize -> ingest -> index -> search
- Dual frontend: a standalone single-file Alpine.js landing page (`web/index.html`) and a Vite+React SPA (`src/frontend/web/`)
- PostgreSQL as primary data store, Elasticsearch as search index, Redis for query analytics caching
- MCP (Model Context Protocol) servers expose search tools for AI assistants
- Cryptographic commitment chain (CRSS-1) for data integrity verification

## Layers

**Ingest Layer (Data Pipeline):**
- Purpose: Discover, download, parse, normalize, and persist DOU publications
- Location: `src/backend/ingest/`
- Contains: Pipeline orchestration, ZIP downloading, XML parsing, normalization, ES indexing, embedding generation, chunking
- Depends on: PostgreSQL (via psycopg2), Elasticsearch (via httpx), in.gov.br public APIs
- Used by: CLI entrypoints, systemd timers, ops scripts

**Commitment Layer (Integrity):**
- Purpose: Cryptographic sealing of ingested data using CRSS-1 Merkle trees
- Location: `src/backend/commitment/`
- Contains: Canonical serialization (`crss1.py`), Merkle tree construction (`tree.py`), anchor chaining (`chain.py`), verification (`verify.py`), anchor persistence (`anchor.py`)
- Depends on: PostgreSQL registry data, hashlib (SHA-256)
- Used by: Ingest pipeline (sealing phase), commitment CLI

**DBSync Layer (Schema Management):**
- Purpose: Declarative schema reconciliation from YAML source models to PostgreSQL
- Location: `src/backend/dbsync/`
- Contains: YAML model loader (`loader.py`), PostgreSQL introspection (`introspect.py`), diff engine (`differ.py`), migration planner (`planner.py`), migration executor (`executor.py`), SQL schema files
- Depends on: `config/sources/sources_v3.yaml` for desired schema, PostgreSQL catalog
- Used by: Schema sync CLI (`src/backend/apps/schema_sync.py`)

**Search Layer (Query):**
- Purpose: Multi-backend search with PostgreSQL BM25, Elasticsearch, and hybrid (BM25 + vector + RRF) retrieval
- Location: `src/backend/search/`
- Contains: Search adapter protocol and implementations (`adapters.py`), legal norm query detection (`norm_queries.py`), Redis-backed query analytics (`redis_signals.py`)
- Depends on: PostgreSQL, Elasticsearch, Redis, embedding models
- Used by: MCP servers, FastAPI web server

**Application Layer (API & Services):**
- Purpose: HTTP API, MCP tool servers, CLI commands, security middleware
- Location: `src/backend/apps/`
- Contains: FastAPI web server (`web_server.py`), MCP servers (`mcp_server.py`, `mcp_es_server.py`), auth (`auth.py`), chat security (`chat_security.py`), security middleware (`middleware/`)
- Depends on: Search layer, ingest layer, commitment layer
- Used by: End users (via API), AI assistants (via MCP)

**Frontend Layer (UI):**
- Purpose: User-facing search and document reading interface
- Location: `src/frontend/web/` (React SPA) and `web/index.html` (standalone Alpine.js page)
- Contains: React pages (Home, Search, Document, Analytics, Chat), shadcn/ui components, Tailwind styling
- Depends on: FastAPI backend `/api/*` endpoints
- Used by: End users via browser

## Data Flow

**Ingestion Pipeline:**

1. `src/backend/ingest/orchestrator.py` or `src/backend/ingest/bulk_pipeline.py` is invoked via CLI
2. `src/backend/ingest/auto_discovery.py` + `src/backend/ingest/catalog_scraper.py` detect new publications from in.gov.br
3. `src/backend/ingest/zip_downloader.py` downloads monthly ZIP bundles using folder IDs from `ops/data/dou_catalog_registry.json`
4. `src/backend/ingest/xml_parser.py` parses INLabs XML into `DOUArticle` dataclasses
5. `src/backend/ingest/normalizer.py` computes content hashes, natural key hashes, and canonical fields
6. `src/backend/ingest/dou_ingest.py` enriches documents via `html_extractor.py` (NLP extraction of signatures, normative references, procedure references) and inserts into PostgreSQL `dou.*` schema
7. `src/backend/commitment/` seals the batch with a CRSS-1 Merkle tree commitment, appending an anchor to the chain
8. `src/backend/ingest/es_indexer.py` syncs documents from PostgreSQL to Elasticsearch
9. `src/backend/ingest/embedding_pipeline.py` generates vector embeddings and indexes chunks into `gabi_chunks_v1`

**Incremental Sync Pipeline:**

1. `src/backend/ingest/sync_pipeline.py` compares catalog registry against `dou.source_zip` table
2. Downloads only missing ZIPs, ingests into `dou.*` schema
3. Designed for periodic cron/systemd execution

**Search Request Flow:**

1. Client sends request to FastAPI (`src/backend/apps/web_server.py`) endpoints: `/api/search`, `/api/suggest`, `/api/document/{id}`, `/api/stats`, etc.
2. Web server delegates to `src/backend/apps/mcp_server.py` payload builders which use search adapters
3. `src/backend/search/adapters.py` dispatches to configured backend: `PGSearchAdapter` (BM25), `ESSearchAdapter` (Elasticsearch), or `HybridSearchAdapter` (BM25 + vector + RRF reranking)
4. `src/backend/search/redis_signals.py` caches results and tracks query analytics (top searches)
5. `src/backend/search/norm_queries.py` detects legal norm patterns in queries for special handling

**MCP Tool Flow:**

1. AI assistant (Claude Desktop, VS Code) connects via stdio or SSE to MCP servers
2. `src/backend/apps/mcp_es_server.py` exposes: `es_search`, `es_suggest`, `es_facets`, `es_document`, `es_health`
3. `src/backend/apps/mcp_server.py` exposes: `dou_search`, `dou_search_filtered`, `dou_stats`, `dou_document`
4. Both use the search adapter layer for actual query execution

**State Management:**
- Server-side: PostgreSQL is the authoritative data store; Elasticsearch is a derived search index; Redis holds ephemeral query analytics
- Frontend React SPA: React Query (`@tanstack/react-query`) for server state caching
- Frontend standalone: Alpine.js reactive state in `web/index.html`

## Key Abstractions

**DOUArticle:**
- Purpose: Parsed article from INLabs XML, core domain object
- Defined in: `src/backend/ingest/xml_parser.py`
- Pattern: Frozen dataclass with slots, mirrors XML `<article>` element attributes

**SearchAdapter (Protocol):**
- Purpose: Polymorphic search backend abstraction
- Defined in: `src/backend/search/adapters.py`
- Implementations: `PGSearchAdapter`, `ESSearchAdapter`, `HybridSearchAdapter`
- Pattern: Python Protocol class; factory function `create_search_adapter()` selects implementation based on `SEARCH_BACKEND` env var

**PipelineResult:**
- Purpose: Aggregate metrics from a complete pipeline run
- Defined in: `src/backend/ingest/bulk_pipeline.py`
- Pattern: Mutable dataclass accumulating counts across pipeline phases

**PipelineConfig / PipelineOrchestrator:**
- Purpose: Configuration and coordination of multi-phase ingestion
- Defined in: `src/backend/ingest/orchestrator.py`
- Pattern: Config dataclass + orchestrator class with phase tracking

**Sources V3 YAML DSL:**
- Purpose: Declarative data model definition driving schema sync
- Defined in: `config/sources/sources_v3.yaml`
- Pattern: Custom DSL with entities, fields, constraints, indexes, and relations; parsed by `src/backend/dbsync/loader.py`

**CRSS-1 Commitment:**
- Purpose: Deterministic canonical serialization for Merkle tree integrity proofs
- Defined in: `src/backend/commitment/crss1.py`
- Pattern: Fixed field ordering, NFC normalization, pipe-delimited canonical bytes, SHA-256 hashing

## Entry Points

**FastAPI Web Server:**
- Location: `src/backend/apps/web_server.py`
- Launcher: `ops/bin/web_server.py`
- Triggers: HTTP requests from browser/clients
- Responsibilities: REST API for search, document retrieval, stats, chat proxy, static file serving

**MCP Server (general):**
- Location: `src/backend/apps/mcp_server.py`
- Launcher: `ops/bin/mcp_server.py`
- Triggers: MCP protocol connections (stdio/SSE)
- Responsibilities: Expose DOU search tools to AI assistants

**MCP ES Server (Elasticsearch-specific):**
- Location: `src/backend/apps/mcp_es_server.py`
- Launcher: `ops/bin/mcp_es_server.py`
- Triggers: MCP protocol connections (stdio/SSE)
- Responsibilities: Direct Elasticsearch search, facets, suggest, health

**Pipeline Orchestrator:**
- Location: `src/backend/ingest/orchestrator.py`
- Triggers: CLI invocation (`python -m src.backend.ingest.orchestrator`)
- Responsibilities: Full automated ingestion pipeline with discovery, download, parse, ingest, seal, report

**Bulk Pipeline:**
- Location: `src/backend/ingest/bulk_pipeline.py`
- Triggers: CLI invocation (`python -m src.backend.ingest.bulk_pipeline`)
- Responsibilities: Date-range based bulk ingestion

**Sync Pipeline:**
- Location: `src/backend/ingest/sync_pipeline.py`
- Triggers: CLI or systemd timer (`config/systemd/gabi-ingest.timer`)
- Responsibilities: Incremental sync of new publications

**Schema Sync:**
- Location: `src/backend/apps/schema_sync.py` / `src/backend/dbsync/schema_sync.py`
- Launcher: `ops/bin/schema_sync.py`
- Triggers: CLI invocation
- Responsibilities: Declarative PostgreSQL schema reconciliation (plan/apply/verify)

**Commitment CLI:**
- Location: `src/backend/apps/commitment_cli.py`
- Launcher: `ops/bin/commitment_cli.py`
- Triggers: CLI invocation
- Responsibilities: Compute and verify CRSS-1 cryptographic commitments

**Embedding Pipeline:**
- Location: `src/backend/ingest/embedding_pipeline.py`
- Triggers: CLI invocation (`python -m src.backend.ingest.embedding_pipeline`)
- Responsibilities: Generate vector embeddings, create/backfill ES chunks index

**React SPA:**
- Location: `src/frontend/web/src/main.tsx`
- Triggers: Browser navigation
- Responsibilities: Client-side search UI, document reader, analytics dashboard, chat interface

## Error Handling

**Strategy:** Function-level try/except with stderr logging; no centralized error framework

**Patterns:**
- Pipeline phases use phase-level error tracking in `PipelineOrchestrator` with status=failed markers
- Bulk pipeline accumulates errors in `PipelineResult.extraction_errors` and `PipelineResult.ingestion_errors` lists
- Search adapters raise on HTTP errors via `httpx` response `raise_for_status()`
- FastAPI web server uses `HTTPException` for API error responses
- Auth module raises `HTTPException` with 401/403 status codes
- DBSync raises custom `ModelLoadError`, `PlanningError`, `ApplyError` exception classes

## Cross-Cutting Concerns

**Logging:** Print to stderr via `_log()` helper functions (no structured logging framework); `loguru` is in `requirements.txt` but not yet widely adopted
**Validation:** Pydantic models in FastAPI endpoints; dataclass-based validation in pipeline code; Zod on frontend
**Authentication:** Token-based auth with HMAC-signed session cookies (`src/backend/apps/auth.py`); rate limiting via `src/backend/apps/middleware/security.py`
**Configuration:** Environment variables (`.env` file via `python-dotenv`), YAML config files (`config/production.yaml`, `config/sources/sources_v3.yaml`), CLI arguments

---

*Architecture analysis: 2026-03-08*
