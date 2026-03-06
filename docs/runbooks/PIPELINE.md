# GABI Pipeline Runbook

> Last verified: 2026-03-06

This document describes the end-to-end pipeline currently implemented in this repository and the exact operator flow to reproduce it. It is written for a new operator who needs to stand up the pipeline locally, run ingestion, and publish three retrieval layers:

1. PostgreSQL BM25 keyword search
2. Elasticsearch full-text search
3. Hybrid/RAG search backed by vector embeddings

The runbook also explains how to adapt the pipeline to a different YAML-defined source model with minimal changes.

## 1. Pipeline Topology

The current stack has two complementary ingestion tracks:

1. `ingest.sync_pipeline`
   Purpose: production operational path for `dou.*`
   Output: PostgreSQL operational schema used by web, MCP, BM25, ES, and vectors

2. `ingest.bulk_pipeline`
   Purpose: append-only registry and CRSS-1 sealing path for `registry.*`
   Output: temporal/audit trail tables and commitment proofs

For search, the primary path is:

`catalog -> ZIP download -> XML parse -> dou.* ingest -> chunk backfill -> BM25/ES/vector indexers -> web/MCP`

Runtime entrypoints stay under `ops/bin/` as compatibility wrappers:

- `ops/bin/web_server.py`
- `ops/bin/mcp_server.py`
- `ops/bin/mcp_es_server.py`
- `ops/bin/schema_sync.py`
- `ops/bin/commitment_cli.py`

Their current implementations live under `src/backend/apps/`. The static frontend lives under `src/frontend/web/`.

## 2. Dependencies

Operator prerequisites:

- Python 3.13+ with virtualenv
- Docker / Docker Compose
- PostgreSQL 16 on port `5433`
- Elasticsearch 8.x on port `9200`
- Redis 7 on port `6380` for query-assist signals
- Optional: OpenAI-compatible embedding endpoint for production semantic vectors

Install the Python environment:

```bash
cd /home/parallels/dev/gabi-kimi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Bring up local infra:

```bash
python3 ops/local/infra_manager.py up
python3 ops/local/infra_manager.py status
```

## 3. Configuration Surfaces

Main runtime configuration files:

- `.env.example`: baseline runtime variables
- `.env`: local active config
- `config/pipeline_config.example.yaml`: operator-oriented pipeline config template
- `config/sources/sources_v3.yaml`: schema manifest DSL for source models
- `config/sources/sources_v3.identity-test.yaml`: identity strategy for registry ingest
- `.mcp.json`: project MCP config
- `.vscode/mcp.json`: VS Code MCP config

Current critical environment variables:

```bash
SEARCH_BACKEND=hybrid
ES_URL=http://localhost:9200
ES_INDEX=gabi_documents_v1
ES_CHUNKS_INDEX=gabi_chunks_v1
EMBED_PROVIDER=openai-compatible
EMBED_MODEL=text-embedding-3-small
EMBED_DIM=384
EMBED_BASE_URL=https://api.openai.com/v1
EMBED_API_KEY=...
REDIS_URL=redis://localhost:6380/0
```

Copy and edit local config:

```bash
cp .env.example .env
```

## 4. Stage 1: YAML Manifest Schema and Parsing

### 4.1 What the YAML manifest does

The repository uses a declarative DSL under `sources.<source_id>.model` to define relational entities, fields, constraints, and indexes. The active example is `config/sources/sources_v3.yaml`.

The loader in `src/backend/dbsync/loader.py` expects:

- top-level `sources` mapping
- one or more `sources.<id>.model` blocks
- each model to define:
  - `namespace`
  - `entities`
  - `identity.primary_key`
  - `fields`
  - optional `constraints.unique`
  - optional `indexes`

Minimal pattern:

```yaml
sources:
  my_source:
    model:
      dsl_version: "1.0"
      namespace: my_namespace
      entities:
        document:
          kind: record
          table: document
          identity:
            primary_key:
              field: id
              type: uuid
              generated: uuid_v7
          fields:
            id: { type: uuid, required: true, nullable: false }
            title: { type: text, required: true, nullable: false }
            body_text: { type: text, required: true, nullable: false }
```

### 4.2 How the manifest is parsed

`src/backend/dbsync/loader.py` reads the YAML with `yaml.safe_load()` and normalizes it into:

- `SourceModelSpec`
- `EntitySpec`
- `FieldSpec`

The schema sync chain is:

1. `ops/bin/schema_sync.py` -> `dbsync.schema_sync.main()`
2. `dbsync.loader.load_source_models()`
3. `dbsync.planner.build_plan()`
4. `dbsync.differ.diff_schema()`
5. `dbsync.executor.apply_operations()`

Validate and apply the model:

```bash
.venv/bin/python ops/bin/schema_sync.py plan --sources config/sources/sources_v3.yaml
.venv/bin/python ops/bin/schema_sync.py apply --sources config/sources/sources_v3.yaml
.venv/bin/python ops/bin/schema_sync.py verify --sources config/sources/sources_v3.yaml
```

### 4.3 Adapting to a different YAML source

To onboard a different source with minimal adaptation:

1. Create a new manifest following the same `sources.<id>.model` structure.
2. Run `ops/bin/schema_sync.py plan/apply/verify` against that manifest.
3. Make sure your downloader/parser emits records compatible with the target schema.
4. If you need operational search on the new source, either:
   - map the new source into `dou.*`, or
   - add a parallel adapter/indexer set for the new schema.

Important: the YAML file defines the relational target model, not the source file parser by itself. For a non-DOU source you still need a parser equivalent to `xml_parser.py` plus a normalizer/ingestor equivalent to `dou_ingest.py` or `registry_ingest.py`.

## 5. Stage 2: Source File Downloading

### 5.1 Discovery

The DOU source path begins with catalog discovery:

- `src/backend/ingest/catalog_scraper.py`
- `src/backend/ingest/sync_pipeline.py`
- `ops/data/dou_catalog_registry.json`

Refresh the monthly catalog registry:

```bash
.venv/bin/python -m src.backend.ingest.catalog_scraper --output ops/data/dou_catalog_registry.json
```

Or let sync refresh it:

```bash
.venv/bin/python -m src.backend.ingest.sync_pipeline --refresh-catalog
```

### 5.2 Download

Downloader implementation lives in `src/backend/ingest/zip_downloader.py`. It builds ZIP targets, resolves the INLabs/Liferay paths, downloads bundles, and extracts XML members.

Download-only examples:

```bash
.venv/bin/python -m src.backend.ingest.bulk_pipeline --days 7 --download-only
.venv/bin/python -m src.backend.ingest.bulk_pipeline --start 2002-01-01 --end 2002-01-31 --download-only
```

Incremental download through the operational sync path:

```bash
.venv/bin/python -m src.backend.ingest.sync_pipeline --start 2002-01 --end 2002-12
```

Source assets are stored under:

- `ops/data/inlabs/`
- `ops/data/inlabs/zips/`

## 6. Stage 3: Ingestion Into the Data Layer

There are two ingestion targets.

### 6.1 Operational ingest into `dou.*`

Use `ingest.sync_pipeline` and `ingest.dou_ingest.DOUIngestor` for the active search path.

Pipeline steps:

1. compare catalog entries vs `dou.source_zip`
2. download missing ZIPs
3. parse XML
4. merge multipart fragments
5. extract signatures/references/media
6. insert into:
   - `dou.source_zip`
   - `dou.edition`
   - `dou.document`
   - `dou.document_media`
   - `dou.document_signature`
   - `dou.normative_reference`
   - `dou.procedure_reference`

Run:

```bash
.venv/bin/python -m src.backend.ingest.sync_pipeline --refresh-catalog
.venv/bin/python -m src.backend.ingest.sync_pipeline --start 2002-01 --end 2002-12
```

### 6.2 Registry ingest into `registry.*`

Use `ingest.bulk_pipeline` when you want the append-only temporal registry and optional CRSS-1 sealing.

Run:

```bash
.venv/bin/python -m src.backend.ingest.bulk_pipeline --start 2002-01-01 --end 2002-01-31 --seal
```

This path flows through:

- `src/backend/ingest/xml_parser.py`
- `src/backend/ingest/normalizer.py`
- `src/backend/dbsync/registry_ingest.py`
- `src/backend/commitment/*`

For web search, BM25, Elasticsearch, and vectors, the `dou.*` operational path is the one that matters.

## 7. Stage 4: Processing and Transformation

### 7.1 XML parsing and enrichment

Core processors:

- `src/backend/ingest/xml_parser.py`: XML -> structured article objects
- `src/backend/ingest/multipart_merger.py`: reassembles split acts
- `src/backend/ingest/html_extractor.py`: signatures, media, reference extraction
- `src/backend/ingest/normalizer.py`: article -> registry ingest record
- `src/backend/ingest/dou_ingest.py`: operational row building for `dou.*`

### 7.2 Chunk generation for RAG/hybrid search

Chunking is a separate transformation step after `dou.document` exists.

Schema:

- `src/backend/dbsync/dou_schema.sql` creates `dou.document_chunk`

Chunking implementation:

- `src/backend/ingest/chunker.py`
- `ops/scripts/backfill_chunks.py`

Chunk metadata currently includes:

- `section`
- `publication_date`
- `issuing_organ`
- `art_type`
- `heading_context`
- character offsets
- token estimate

Run chunk backfill:

```bash
.venv/bin/python ops/scripts/backfill_chunks.py \
  --batch-size 1500 \
  --date-from 2002-01-01 \
  --date-to 2002-12-31 \
  --cursor-file ops/data/chunks_backfill_cursor_2002.json
```

Useful controls:

- `--replace`
- `--only-missing`
- `--dry-run`
- `--chunk-size`
- `--chunk-overlap`
- `--min-chunk-size`
- `--max-chunk-size`

## 8. Stage 5: Retrieval Indexing

### 8.1 Retrieval Strategy A: BM25 in PostgreSQL

This layer operates on `dou.document` and materialized views from `src/backend/dbsync/bm25_schema.sql`.

Builder:

- `src/backend/ingest/bm25_indexer.py`

Run:

```bash
.venv/bin/python -m src.backend.ingest.bm25_indexer build
.venv/bin/python -m src.backend.ingest.bm25_indexer refresh
.venv/bin/python -m src.backend.ingest.bm25_indexer stats
```

What it creates/refreshed:

- `dou.bm25_term_stats`
- `dou.bm25_corpus_stats`
- `dou.v_bm25_stats`

CLI query example:

```bash
.venv/bin/python -m src.backend.ingest.bm25_indexer search "portaria ministerio saude" --date-from 2002-01-01 --date-to 2002-12-31
```

Use this layer when:

- you want a pure PostgreSQL stack
- exact/legal keyword search dominates
- you need the cheapest operational footprint

### 8.2 Retrieval Strategy B: Elasticsearch full-text

This layer indexes complete documents from PostgreSQL into `gabi_documents_v1`.

Indexer:

- `src/backend/ingest/es_indexer.py`

Mapping:

- `src/backend/search/es_index_v1.json`

Run:

```bash
.venv/bin/python -m src.backend.ingest.es_indexer backfill --recreate-index
.venv/bin/python -m src.backend.ingest.es_indexer sync
.venv/bin/python -m src.backend.ingest.es_indexer stats
```

Cursor state defaults to:

- `ops/data/es_sync_cursor.json`

Use this layer when:

- you want highlights, suggest, facets, fuzzy matching
- Elasticsearch is your primary lexical engine

### 8.3 Retrieval Strategy C: Vector embeddings and hybrid RAG

This layer indexes chunks from `dou.document_chunk` into `gabi_chunks_v1`.

Pipeline pieces:

- `src/backend/ingest/embedding_pipeline.py`
- `src/backend/search/es_chunks_v1.json`
- `src/backend/search/adapters.py` hybrid adapter

Current vector index settings:

- `dense_vector`
- `dims=384`
- cosine similarity
- one document per chunk

Create and populate the vector index:

```bash
.venv/bin/python -m src.backend.ingest.embedding_pipeline create-index --recreate-index
.venv/bin/python -m src.backend.ingest.embedding_pipeline backfill \
  --batch-size 1024 \
  --cursor ops/data/es_chunks_openai_cursor_384.json
.venv/bin/python -m src.backend.ingest.embedding_pipeline stats \
  --cursor ops/data/es_chunks_openai_cursor_384.json
```

Provider modes:

- `EMBED_PROVIDER=hash`: development fallback only
- `EMBED_PROVIDER=openai-compatible`: real semantic vectors

Recommended production config:

```bash
EMBED_PROVIDER=openai-compatible
EMBED_MODEL=text-embedding-3-small
EMBED_DIM=384
EMBED_BASE_URL=https://api.openai.com/v1
EMBED_API_KEY=...
```

## 9. Serving Layer

### 9.1 Web API

Entrypoint wrapper:

- `ops/bin/web_server.py`

Implementation:

- `src/backend/apps/web_server.py`

Run:

```bash
.venv/bin/python ops/bin/web_server.py --port 8000
```

Key routes:

- `GET /api/search`
- `GET /api/suggest`
- `GET /api/autocomplete`
- `GET /api/document/{id}`
- `GET /api/stats`

### 9.2 MCP server

Entrypoint wrapper:

- `ops/bin/mcp_es_server.py`

Implementation:

- `src/backend/apps/mcp_es_server.py`

Run:

```bash
.venv/bin/python ops/bin/mcp_es_server.py
.venv/bin/python ops/bin/mcp_es_server.py --transport sse --port 8766
```

Current active retrieval behavior:

- `SEARCH_BACKEND=hybrid`
- lexical search on `gabi_documents_v1`
- vector search on `gabi_chunks_v1`
- reciprocal rank fusion (`HYBRID_RRF_K=60`)
- basic rerank (`RERANK_PROVIDER=basic`)

Health validation:

```bash
.venv/bin/python -c "from mcp_es_server import es_health; import json; print(json.dumps(es_health(), indent=2, ensure_ascii=False))"
```

Expected health fields:

- `search_backend`
- `index`
- `chunks_index`

## 10. Reproducible End-to-End Run

From a clean local environment:

```bash
cd /home/parallels/dev/gabi-kimi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 ops/local/infra_manager.py up

PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi -f src/backend/dbsync/dou_schema.sql
PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi -f src/backend/dbsync/bm25_schema.sql
PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi -f src/backend/dbsync/registry_schema.sql

.venv/bin/python ops/bin/schema_sync.py verify --sources config/sources/sources_v3.yaml
.venv/bin/python -m src.backend.ingest.sync_pipeline --refresh-catalog --start 2002-01 --end 2002-12
.venv/bin/python ops/scripts/backfill_chunks.py --batch-size 1500 --date-from 2002-01-01 --date-to 2002-12-31
.venv/bin/python -m src.backend.ingest.bm25_indexer build
.venv/bin/python -m src.backend.ingest.es_indexer backfill --recreate-index
.venv/bin/python -m src.backend.ingest.embedding_pipeline create-index --recreate-index
.venv/bin/python -m src.backend.ingest.embedding_pipeline backfill --batch-size 1024 --cursor ops/data/es_chunks_openai_cursor_384.json
.venv/bin/python ops/bin/web_server.py --port 8000
```

## 11. Minimal Adaptation Recipe for a Different YAML Source

If the next source is not DOU but still file-driven and schema-first:

1. Duplicate `config/sources/sources_v3.yaml` into a new manifest for the new domain.
2. Apply it with `ops/bin/schema_sync.py`.
3. Copy `config/pipeline_config.example.yaml` into a source-specific config file.
4. Implement a downloader equivalent to `src/backend/ingest/zip_downloader.py`.
5. Implement a parser that emits structured records from the new raw files.
6. Implement an ingestor that writes either:
   - directly into your new schema, or
   - into `dou.*` if you want to reuse all src/backend/search/indexing code unchanged.
7. Reuse these stages unchanged if your destination is compatible:
   - BM25: `ingest.bm25_indexer`
   - ES lexical: `ingest.es_indexer`
   - chunking: `ops/scripts/backfill_chunks.py`
   - vectors: `ingest.embedding_pipeline`
   - serving: `ops/bin/web_server.py`, `ops/bin/mcp_es_server.py`

The lowest-friction route is to preserve the `dou.document`-compatible shape. That lets you swap the source parser while keeping the retrieval stack intact.

## 12. Validation Checklist

Use this after each run:

- schema sync verifies cleanly
- `ingest.sync_pipeline` reports downloaded and ingested ZIPs
- `dou.document` has the expected row count
- `ops/scripts/backfill_chunks.py` writes `dou.document_chunk`
- `ingest.bm25_indexer stats` reports corpus stats
- `ingest.es_indexer stats` shows PG/ES parity
- `ingest.embedding_pipeline stats` shows chunk count and index size
- `mcp_es_server.es_health()` reports `search_backend=hybrid`
- web `/api/search` returns `backend=hybrid` for relevance queries
