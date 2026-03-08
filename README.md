# GABI

> Last verified: 2026-03-06

GABI is a Python pipeline for discovering DOU ZIP bundles, parsing the XML corpus, loading it into
PostgreSQL, and serving retrieval through BM25, Elasticsearch, and hybrid lexical-plus-vector search.

## Current Architecture

There are two ingestion tracks in the repository:

1. `ingest.sync_pipeline`
   Purpose: operational ingest into `dou.*`
   Used by: web API, BM25, Elasticsearch, chunking, embeddings, MCP

2. `ingest.bulk_pipeline`
   Purpose: registry ingest into `registry.*` with optional CRSS-1 sealing
   Used by: audit trail and commitment workflows

The current retrieval stack is:

`ZIP catalog -> ZIP download -> XML parse -> dou.* ingest -> chunk backfill -> BM25 + Elasticsearch + vector index -> ops/bin/web_server.py / ops/bin/mcp_es_server.py`

## Stack

- Python 3.12+
- PostgreSQL 16 on `localhost:5433`
- Elasticsearch 8.x on `localhost:9200`
- Redis 7 on `localhost:6380`
- FastAPI + static frontend in `src/frontend/web/`
- Image availability classification + local cache for historical DOU media in `src/backend/ingest/image_checker.py`
- Root wrappers in `ops/bin/web_server.py`, `ops/bin/mcp_server.py`, and `ops/bin/mcp_es_server.py`
- Server implementations in `src/backend/apps/`

## Repository Layout

```text
src/backend/apps/    Web + MCP server implementations and CLI shells
src/backend/ingest/  Download, parse, ingest, chunking, BM25, ES, embeddings
src/backend/dbsync/  SQL schema sync, registry ingest, and schema DDL
src/backend/search/  PG, ES, and hybrid adapters
src/backend/commitment/ CRSS-1 commitment and verification logic
src/frontend/web/    Static frontend served by ops/bin/web_server.py
ops/scripts/             Backfills, sync wrappers, deploy helpers
ops/local/               Local Docker stack control
ops/deploy/              Fly deployment artifacts
tests/               Script-based validation suite
ops/data/                Downloaded ZIPs, XML extracts, and cursor state
ops/proofs/              Anchor chain and proof artifacts
```

## Getting Started

### 1. Create the environment

```bash
cd /home/parallels/dev/gabi-kimi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Use the virtualenv interpreter for all commands below. The global `python3` on this machine may not have the required packages.

### 2. Start local services

```bash
.venv/bin/python ops/local/infra_manager.py up
.venv/bin/python ops/local/infra_manager.py status
```

This starts:

- PostgreSQL on `5433`
- Elasticsearch on `9200`
- Redis on `6380`

### 3. Apply the database schemas

```bash
PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi -f src/backend/dbsync/registry_schema.sql
PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi -f src/backend/dbsync/dou_schema.sql
PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi -f src/backend/dbsync/bm25_schema.sql
```

Optional schema verification from the DSL:

```bash
.venv/bin/python ops/bin/schema_sync.py verify --sources config/sources/sources_v3.yaml
```

### 4. Ingest data into `dou.*`

Primary operational path:

```bash
.venv/bin/python -m src.backend.ingest.sync_pipeline --refresh-catalog
.venv/bin/python -m src.backend.ingest.sync_pipeline --start 2002-01 --end 2002-12
```

What this now does for embedded DOU images:

- extracts every `<img>` from `body_html`
- classifies remote assets as `available`, `missing`, or `unknown`
- caches available files under `ops/data/dou/images/{doc_id}/`
- stores image fallback metadata in `dou.document_media`
- rewrites stored `body_html` to stable local `/api/media/{doc_id}/{media_name}` URLs

Registry/sealing path:

```bash
.venv/bin/python -m src.backend.ingest.bulk_pipeline --start 2002-01-01 --end 2002-01-31 --seal
```

### 5. Build retrieval indexes

BM25:

```bash
.venv/bin/python -m src.backend.ingest.bm25_indexer build
.venv/bin/python -m src.backend.ingest.bm25_indexer stats
```

Elasticsearch lexical index:

```bash
.venv/bin/python -m src.backend.ingest.es_indexer backfill --recreate-index
.venv/bin/python -m src.backend.ingest.es_indexer stats
```

Chunk backfill for hybrid/vector search:

```bash
.venv/bin/python ops/scripts/backfill_chunks.py \
  --batch-size 1500 \
  --date-from 2002-01-01 \
  --date-to 2002-12-31
```

Vector index:

```bash
.venv/bin/python -m src.backend.ingest.embedding_pipeline create-index --recreate-index
.venv/bin/python -m src.backend.ingest.embedding_pipeline backfill --batch-size 1024
.venv/bin/python -m src.backend.ingest.embedding_pipeline stats
```

### 6. Run the servers

Web:

```bash
.venv/bin/python ops/bin/web_server.py --port 8000
```

The document viewer no longer relies on browser broken-image behavior. When an image is unavailable,
the frontend renders a contextual fallback card using `context_hint`, `fallback_text`, and DOU
metadata from `/api/document/{id}`.

MCP:

```bash
.venv/bin/python ops/bin/mcp_es_server.py
.venv/bin/python ops/bin/mcp_server.py
```

## Search Modes

### PostgreSQL BM25

- built from `dou.document`
- managed by `src/backend/ingest/bm25_indexer.py`
- useful when you want the cheapest fully local lexical search

### Elasticsearch full-text

- document index in `gabi_documents_v1`
- managed by `src/backend/ingest/es_indexer.py`
- supports highlight, facets, and suggest

### Hybrid lexical plus vector

- document index: `gabi_documents_v1`
- chunk index: `gabi_chunks_v1`
- adapter: `src/backend/search/adapters.py`
- MCP server: `ops/bin/mcp_es_server.py`
- current default in `.env.example`: `SEARCH_BACKEND=hybrid`

## Core Runtime Files

- [ops/bin/web_server.py](/home/parallels/dev/gabi-kimi/ops/ops/bin/web_server.py)
- [ops/bin/mcp_es_server.py](/home/parallels/dev/gabi-kimi/ops/ops/bin/mcp_es_server.py)
- [ops/bin/mcp_server.py](/home/parallels/dev/gabi-kimi/ops/ops/bin/mcp_server.py)
- [src/backend/apps/web_server.py](/home/parallels/dev/gabi-kimi/src/backend/apps/web_server.py)
- [src/backend/apps/mcp_es_server.py](/home/parallels/dev/gabi-kimi/src/backend/apps/mcp_es_server.py)
- [src/backend/apps/mcp_server.py](/home/parallels/dev/gabi-kimi/src/backend/apps/mcp_server.py)
- [src/backend/ingest/sync_pipeline.py](/home/parallels/dev/gabi-kimi/src/backend/ingest/sync_pipeline.py)
- [src/backend/ingest/bulk_pipeline.py](/home/parallels/dev/gabi-kimi/src/backend/ingest/bulk_pipeline.py)
- [src/backend/ingest/bm25_indexer.py](/home/parallels/dev/gabi-kimi/src/backend/ingest/bm25_indexer.py)
- [src/backend/ingest/es_indexer.py](/home/parallels/dev/gabi-kimi/src/backend/ingest/es_indexer.py)
- [src/backend/ingest/embedding_pipeline.py](/home/parallels/dev/gabi-kimi/src/backend/ingest/embedding_pipeline.py)
- [ops/scripts/backfill_chunks.py](/home/parallels/dev/gabi-kimi/ops/scripts/backfill_chunks.py)
- [src/backend/search/adapters.py](/home/parallels/dev/gabi-kimi/src/backend/search/adapters.py)

## Tests

```bash
.venv/bin/python tests/test_commitment.py
.venv/bin/python tests/test_bulk_pipeline.py
.venv/bin/python tests/test_dou_ingest.py
.venv/bin/python tests/test_seal_roundtrip.py
.venv/bin/python tests/test_search_adapters.py
```

Manual parser smoke check:

```bash
.venv/bin/python -c "from src.backend.ingest.xml_parser import parse_directory; arts = parse_directory('tests/fixtures/xml_samples'); print(len(arts))"
```

## Configuration References

- [.env.example](/home/parallels/dev/gabi-kimi/.env.example): runtime env vars actually used by the code
- [config/sources/sources_v3.yaml](/home/parallels/dev/gabi-kimi/config/sources/sources_v3.yaml): schema DSL for source models
- [config/sources/sources_v3.identity-test.yaml](/home/parallels/dev/gabi-kimi/config/sources/sources_v3.identity-test.yaml): identity/sealing contract
- [config/pipeline_config.example.yaml](/home/parallels/dev/gabi-kimi/config/pipeline_config.example.yaml): orchestrator config template
- [docs/runbooks/PIPELINE.md](/home/parallels/dev/gabi-kimi/docs/runbooks/PIPELINE.md): detailed runbook

## Fly.io Web Deploy

For the hardened public web deployment, use:

- [ops/deploy/web/fly.toml](/home/parallels/dev/gabi-kimi/ops/deploy/web/fly.toml)
- [ops/deploy/web/Dockerfile](/home/parallels/dev/gabi-kimi/ops/deploy/web/Dockerfile)
- [docs/runbooks/FLY_WEB_SECURITY.md](/home/parallels/dev/gabi-kimi/docs/runbooks/FLY_WEB_SECURITY.md)
- [docs/runbooks/FLY_SPLIT_DEPLOY.md](/home/parallels/dev/gabi-kimi/docs/runbooks/FLY_SPLIT_DEPLOY.md)

Recommended production architecture:

- `gabi-dou-web` for API/backend
- `gabi-dou-frontend` for the static SPA

Minimum secrets bootstrap:

```bash
fly secrets set \
  PGPASSWORD='...' \
  GABI_API_TOKENS='ops:token-1,reader:token-2' \
  GABI_AUTH_SECRET='troque-por-um-segredo-forte' \
  QWEN_API_KEY='...' \
  -a gabi-dou-web
```

If the public hostname or Redis app name differs from the defaults, update
[fly.toml](/home/parallels/dev/gabi-kimi/ops/deploy/web/fly.toml#L10) before:

```bash
fly deploy -c ops/deploy/web/fly.toml
```

Frontend static deploy:

```bash
fly deploy -c ops/deploy/frontend-static/fly.toml
```

## Documentation Status

The authoritative operator docs are:

- [README.md](/home/parallels/dev/gabi-kimi/README.md)
- [docs/runbooks/PIPELINE.md](/home/parallels/dev/gabi-kimi/docs/runbooks/PIPELINE.md)
- [docs/runbooks/FLY_WEB_SECURITY.md](/home/parallels/dev/gabi-kimi/docs/runbooks/FLY_WEB_SECURITY.md)
- [docs/runbooks/FLY_SPLIT_DEPLOY.md](/home/parallels/dev/gabi-kimi/docs/runbooks/FLY_SPLIT_DEPLOY.md)
- [docs/meta/DOCS_RECONCILIATION.md](/home/parallels/dev/gabi-kimi/docs/meta/DOCS_RECONCILIATION.md)
