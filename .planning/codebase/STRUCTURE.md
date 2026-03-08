# Codebase Structure

**Analysis Date:** 2026-03-08

## Directory Layout

```
gabi-kimi/
├── src/
│   ├── backend/
│   │   ├── apps/                # API servers, CLIs, middleware
│   │   │   ├── middleware/      # Security middleware (rate limiting, CSP)
│   │   │   ├── web_server.py    # FastAPI HTTP server
│   │   │   ├── mcp_server.py    # MCP server (general search)
│   │   │   ├── mcp_es_server.py # MCP server (Elasticsearch-specific)
│   │   │   ├── auth.py          # Token auth + session cookies
│   │   │   ├── chat_security.py # Chat endpoint security
│   │   │   ├── commitment_cli.py# CRSS-1 commitment CLI
│   │   │   └── schema_sync.py   # Schema sync CLI wrapper
│   │   ├── ingest/              # Data ingestion pipeline modules
│   │   │   ├── orchestrator.py  # Top-level pipeline coordinator
│   │   │   ├── bulk_pipeline.py # Date-range bulk ingestion
│   │   │   ├── sync_pipeline.py # Incremental sync pipeline
│   │   │   ├── zip_downloader.py# ZIP download from in.gov.br
│   │   │   ├── xml_parser.py    # INLabs XML parser
│   │   │   ├── normalizer.py    # Field normalization + hashing
│   │   │   ├── dou_ingest.py    # Full DOU schema ingestor (NLP enrichment)
│   │   │   ├── html_extractor.py# HTML/NLP extraction (signatures, references)
│   │   │   ├── image_checker.py # Document image resolution
│   │   │   ├── multipart_merger.py # Multi-part article merging
│   │   │   ├── chunker.py       # Document chunking for RAG
│   │   │   ├── embedding_pipeline.py # Vector embedding generation
│   │   │   ├── es_indexer.py    # Elasticsearch document indexer
│   │   │   ├── bm25_indexer.py  # PostgreSQL BM25 indexer
│   │   │   ├── catalog_scraper.py # in.gov.br catalog scraper
│   │   │   ├── auto_discovery.py# Publication auto-discovery
│   │   │   ├── discovery_probe.py # Discovery probe utilities
│   │   │   ├── discovery_registry.py # Discovery state tracking
│   │   │   ├── identity_analyzer.py # Document identity analysis
│   │   │   ├── date_selector.py # Date range utilities
│   │   │   ├── sample_download.py # Sample data downloader
│   │   │   └── media_backfill.py# Media backfill operations
│   │   ├── search/              # Search backend adapters
│   │   │   ├── adapters.py      # PG/ES/Hybrid search adapters
│   │   │   ├── norm_queries.py  # Legal norm query detection
│   │   │   ├── redis_signals.py # Redis query analytics/caching
│   │   │   ├── es_index_v1.json # ES document index mapping
│   │   │   └── es_chunks_v1.json# ES chunks index mapping
│   │   ├── commitment/          # Cryptographic commitment (CRSS-1)
│   │   │   ├── crss1.py         # Canonical serialization
│   │   │   ├── tree.py          # Merkle tree construction
│   │   │   ├── chain.py         # Anchor chaining
│   │   │   ├── anchor.py        # Anchor file persistence
│   │   │   └── verify.py        # Commitment verification
│   │   └── dbsync/              # Declarative schema management
│   │       ├── loader.py        # YAML model loader
│   │       ├── introspect.py    # PostgreSQL catalog introspection
│   │       ├── planner.py       # Migration planner
│   │       ├── differ.py        # Schema diff engine
│   │       ├── executor.py      # Migration executor
│   │       ├── registry_ingest.py # Registry ingestion
│   │       ├── schema_sync.py   # Schema sync CLI entrypoint
│   │       ├── dou_schema.sql   # DOU schema SQL
│   │       ├── registry_schema.sql
│   │       ├── bm25_schema.sql
│   │       └── download_registry_schema.sql
│   └── frontend/
│       └── web/                 # React SPA (Vite + shadcn/ui)
│           ├── src/
│           │   ├── pages/       # Route-level page components
│           │   ├── components/  # Shared UI components
│           │   │   └── ui/      # shadcn/ui primitives
│           │   ├── hooks/       # Custom React hooks
│           │   ├── lib/         # Utility functions
│           │   ├── test/        # Test setup + test files
│           │   ├── App.tsx      # Root component with routing
│           │   ├── main.tsx     # React entry point
│           │   └── index.css    # Global styles + Tailwind
│           ├── package.json
│           ├── tailwind.config.ts
│           ├── vite.config.ts
│           └── tsconfig.json
├── config/
│   ├── sources/
│   │   ├── sources_v3.yaml      # Data model DSL (schema source of truth)
│   │   └── sources_v3.identity-test.yaml
│   ├── production.yaml          # Production pipeline config
│   ├── pipeline_config.example.yaml
│   └── systemd/                 # Systemd service/timer units
│       ├── gabi-ingest.service
│       └── gabi-ingest.timer
├── ops/
│   ├── bin/                     # Thin CLI launchers (sys.path wrappers)
│   │   ├── web_server.py
│   │   ├── mcp_server.py
│   │   ├── mcp_es_server.py
│   │   ├── commitment_cli.py
│   │   └── schema_sync.py
│   ├── scripts/                 # Operational scripts
│   │   ├── daily_sync.sh
│   │   ├── run_overnight_chain.sh
│   │   ├── backfill_chunks.py
│   │   ├── backfill_embeddings.py
│   │   ├── reprocess_2002.py
│   │   ├── cleanup.sh
│   │   └── deploy.sh
│   ├── local/                   # Local dev infrastructure
│   │   ├── docker-compose.yml   # PostgreSQL + Elasticsearch + Redis
│   │   ├── db_control.py
│   │   └── infra_manager.py
│   ├── deploy/                  # Deployment configs
│   │   ├── postgres/            # PostgreSQL Dockerfile + fly.toml
│   │   ├── web/                 # Web server Dockerfile + fly.toml
│   │   └── frontend-static/     # Static frontend nginx + fly.toml
│   ├── data/                    # Runtime data (cursors, registries, logs)
│   │   ├── dou_catalog_registry.json  # Month-to-folder-ID mapping
│   │   ├── es_sync_cursor.json
│   │   ├── es_chunks_sync_cursor.json
│   │   └── logs/
│   └── proofs/                  # Commitment proofs
│       ├── anchors/             # Anchor chain files
│       │   └── 0000-bootstrap.json
│       └── crss1-golden/        # Golden test vectors
├── tests/                       # Python test files
│   ├── test_commitment.py
│   ├── test_seal_roundtrip.py
│   ├── test_bulk_pipeline.py
│   ├── test_image_checker.py
│   ├── test_search_adapters.py
│   └── test_dou_ingest.py
├── docs/                        # Documentation
├── var/                         # Runtime variable data
├── .env                         # Environment variables (DO NOT read)
├── .env.example                 # Example environment template
├── .mcp.json                    # MCP server configurations
├── requirements.txt             # Python dependencies
└── .gitignore
```

## Directory Purposes

**`src/backend/ingest/`:**
- Purpose: All data pipeline modules for DOU publication ingestion
- Contains: ~24 Python modules covering discovery, download, parsing, normalization, indexing, embedding
- Key files: `orchestrator.py` (top-level coordinator), `bulk_pipeline.py` (date-range ingestion), `dou_ingest.py` (full schema ingestor with NLP enrichment), `xml_parser.py` (INLabs XML parsing)

**`src/backend/search/`:**
- Purpose: Search query execution across multiple backends
- Contains: Adapter pattern implementations, legal norm detection, Redis caching
- Key files: `adapters.py` (3 search adapters: PG, ES, Hybrid), `norm_queries.py` (legal norm pattern matching), `redis_signals.py` (query analytics)

**`src/backend/commitment/`:**
- Purpose: CRSS-1 cryptographic commitment chain for data integrity
- Contains: Canonical serialization, Merkle trees, anchor chaining, verification
- Key files: `crss1.py` (serialization spec), `tree.py` (Merkle construction), `chain.py` (append-only chain)

**`src/backend/dbsync/`:**
- Purpose: Declarative schema management from YAML to PostgreSQL
- Contains: YAML loader, PostgreSQL introspection, diff engine, migration executor
- Key files: `loader.py` (parses sources_v3.yaml), `differ.py` (schema diff), `executor.py` (applies migrations)

**`src/backend/apps/`:**
- Purpose: Application-level servers, CLIs, and middleware
- Contains: FastAPI web server, two MCP servers, auth, security middleware
- Key files: `web_server.py` (main HTTP API), `mcp_server.py` + `mcp_es_server.py` (MCP tools), `auth.py` (token + session auth)

**`src/frontend/web/`:**
- Purpose: React SPA for search and document reading
- Contains: Vite project with React 18, shadcn/ui components, Tailwind CSS
- Key files: `src/App.tsx` (routing), `src/pages/` (5 pages), `src/components/` (~20 custom components + shadcn primitives)

**`ops/`:**
- Purpose: Operational tooling, scripts, deployment configs, runtime data
- Contains: CLI launchers, shell scripts, Docker configs, Fly.io configs, data cursors
- Key files: `bin/` (thin launchers), `local/docker-compose.yml` (dev infrastructure), `data/dou_catalog_registry.json` (catalog mapping)

**`config/`:**
- Purpose: Application configuration files
- Contains: Data model YAML, production pipeline config, systemd units
- Key files: `sources/sources_v3.yaml` (schema source of truth), `production.yaml` (pipeline config)

**`tests/`:**
- Purpose: Python test suite
- Contains: 6 test files covering commitment, pipeline, search, and ingestion

## Key File Locations

**Entry Points:**
- `src/backend/apps/web_server.py`: FastAPI HTTP server (main API)
- `src/backend/apps/mcp_server.py`: MCP server for general DOU search
- `src/backend/apps/mcp_es_server.py`: MCP server for Elasticsearch operations
- `src/backend/ingest/orchestrator.py`: Full automated pipeline
- `src/backend/ingest/bulk_pipeline.py`: Date-range bulk ingestion
- `src/backend/ingest/sync_pipeline.py`: Incremental sync
- `src/frontend/web/src/main.tsx`: React SPA entry

**Configuration:**
- `config/sources/sources_v3.yaml`: Data model DSL (schema source of truth)
- `config/production.yaml`: Production pipeline configuration
- `.env` / `.env.example`: Environment variables
- `.mcp.json`: MCP server definitions
- `ops/local/docker-compose.yml`: Local dev infrastructure (Postgres, ES, Redis)

**Core Domain Logic:**
- `src/backend/ingest/xml_parser.py`: DOUArticle dataclass and XML parsing
- `src/backend/ingest/normalizer.py`: Field normalization and content hashing
- `src/backend/ingest/dou_ingest.py`: Full document ingestion with NLP enrichment
- `src/backend/search/adapters.py`: SearchAdapter protocol + 3 implementations
- `src/backend/commitment/crss1.py`: CRSS-1 canonical serialization

**Database Schemas:**
- `src/backend/dbsync/dou_schema.sql`: DOU schema DDL
- `src/backend/dbsync/registry_schema.sql`: Registry schema DDL
- `src/backend/dbsync/bm25_schema.sql`: BM25 search schema DDL
- `src/backend/search/es_index_v1.json`: Elasticsearch document mapping
- `src/backend/search/es_chunks_v1.json`: Elasticsearch chunks mapping

**Testing:**
- `tests/test_commitment.py`: CRSS-1 commitment tests
- `tests/test_seal_roundtrip.py`: Seal round-trip verification
- `tests/test_bulk_pipeline.py`: Bulk pipeline tests
- `tests/test_search_adapters.py`: Search adapter tests
- `tests/test_dou_ingest.py`: DOU ingestion tests
- `src/frontend/web/src/test/example.test.ts`: Frontend example test

## Naming Conventions

**Files (Python):**
- `snake_case.py` for all modules: `xml_parser.py`, `bulk_pipeline.py`, `es_indexer.py`
- `__init__.py` in every package directory

**Files (TypeScript/React):**
- `PascalCase.tsx` for components and pages: `AppShell.tsx`, `SearchBar.tsx`, `HomePage.tsx`
- `camelCase.ts` for utilities and hooks: `sectionParser.ts`, `useDeepLink.ts`
- `ui/` directory contains lowercase shadcn primitives: `button.tsx`, `card.tsx`

**Directories:**
- `snake_case` for Python packages: `ingest/`, `dbsync/`, `commitment/`
- `kebab-case` for ops directories: `frontend-static/`, `crss1-golden/`
- `camelCase` or `lowercase` for frontend: `components/`, `hooks/`, `lib/`, `pages/`

**Python Modules:**
- Prefix private helpers with `_`: `_log()`, `_nfc()`, `_build_dsn()`
- CLI entrypoints use `main()` function + `if __name__ == "__main__": raise SystemExit(main())`
- Dataclasses use `slots=True` and often `frozen=True`

**SQL Files:**
- `{domain}_schema.sql` pattern: `dou_schema.sql`, `bm25_schema.sql`, `registry_schema.sql`

## Where to Add New Code

**New Ingest Pipeline Module:**
- Primary code: `src/backend/ingest/{module_name}.py`
- Tests: `tests/test_{module_name}.py`
- Wire into: `src/backend/ingest/orchestrator.py` or `src/backend/ingest/bulk_pipeline.py`

**New API Endpoint:**
- Add route to: `src/backend/apps/web_server.py`
- Add payload builder to: `src/backend/apps/mcp_server.py` (if shared with MCP)
- Add security rules to: `src/backend/apps/middleware/security.py`

**New MCP Tool:**
- Add to: `src/backend/apps/mcp_server.py` or `src/backend/apps/mcp_es_server.py`
- Register with: `mcp.tool()` decorator

**New Search Backend:**
- Implement `SearchAdapter` protocol in: `src/backend/search/adapters.py`
- Update factory: `create_search_adapter()` in same file

**New Frontend Page:**
- Create page component: `src/frontend/web/src/pages/{PageName}.tsx`
- Add lazy import + route in: `src/frontend/web/src/App.tsx`
- Add nav link in: `src/frontend/web/src/components/AppShell.tsx`

**New Frontend Component:**
- Shared component: `src/frontend/web/src/components/{ComponentName}.tsx`
- shadcn/ui primitive: `src/frontend/web/src/components/ui/{component}.tsx`
- Custom hook: `src/frontend/web/src/hooks/{hookName}.ts`
- Utility: `src/frontend/web/src/lib/{utilName}.ts`

**New Database Entity:**
- Add entity to: `config/sources/sources_v3.yaml`
- Run schema sync: `python ops/bin/schema_sync.py plan` then `apply`

**New CLI Command:**
- Add app module: `src/backend/apps/{command_name}.py`
- Add thin launcher: `ops/bin/{command_name}.py` (sys.path setup + import)

**New Operational Script:**
- Add to: `ops/scripts/{script_name}.py` or `ops/scripts/{script_name}.sh`

## Special Directories

**`ops/data/`:**
- Purpose: Runtime data files (sync cursors, catalog registry, logs)
- Generated: Yes (by pipeline runs)
- Committed: Partially (registry JSON is committed; cursor files and logs are gitignored)

**`ops/proofs/`:**
- Purpose: Cryptographic commitment proof chain
- Generated: Yes (by commitment sealing)
- Committed: Yes (anchors and golden test vectors)

**`ops/bin/`:**
- Purpose: Thin CLI launcher scripts that set up sys.path and delegate to `src/backend/apps/`
- Generated: No
- Committed: Yes

**`var/`:**
- Purpose: Runtime variable data (temp files, caches)
- Generated: Yes
- Committed: No (gitignored contents)

**`.dev/`:**
- Purpose: Development MCP servers and tooling (ui-copilot, dev-converge, shannon, json-render)
- Generated: No
- Committed: Partially

---

*Structure analysis: 2026-03-08. Legacy web/ (Alpine.js) removed Phase 10.*
