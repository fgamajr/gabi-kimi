# GABI - Busca Inteligente no Diário Oficial da União

Full-text search platform for Brazil's official gazette (DOU), covering 2002–2026. Downloads, processes, and indexes the DOU corpus into MongoDB and Elasticsearch BM25, with all runtime code expected to run inside Docker containers.

## Architecture

```
in.gov.br (Liferay ZIPs)
    ↓  src.backend.ingest.sync_dou
MongoDB (documents collection)
    ↓  es_indexer.py
Elasticsearch (BM25 full-text)
    ↑
MCP Server (5 tools) ← Claude Code
```

Runtime topology under Docker Compose:

- `frontend` serves the Vite dev server on host port `8081`
- `backend` serves the FastAPI API on host port `8001`
- `worker` runs background Elasticsearch sync loops
- `mongo` and `elasticsearch` stay on the Docker internal network only

## Stack

| Layer | Tech |
|---|---|
| Ingestion | Python, pymongo, requests |
| Database | MongoDB 7 in Docker Compose |
| Search | Elasticsearch 8.15.4 in Docker Compose |
| MCP | FastMCP (stdio), httpx |
| Backend API | FastAPI, uvicorn |
| Frontend | Vite + React 18 + Tailwind CSS 3 + TypeScript |

## Prerequisites

- Docker with Compose

## Quick Start

### 1. Build and start the stack

```bash
cp .env.example .env
docker compose up --build
```

The host machine only needs Docker and Docker Compose.

### 2. Development endpoints

```text
Frontend:    http://localhost:8081
Backend API: http://localhost:8001
```

Container-to-container networking uses Docker DNS, never host localhost:

```text
frontend -> backend:8000
backend  -> mongo:27017
backend  -> elasticsearch:9200
worker   -> mongo:27017
worker   -> elasticsearch:9200
```

### 3. Ingest DOU Data

First-time full ingestion (2002–2026, ~7M documents):

```bash
# Single year
docker compose exec backend python -m src.backend.ingest.sync_dou --year 2024

# Single month
docker compose exec backend python -m src.backend.ingest.sync_dou --year 2024 --month 6

# Full backfill (all years)
for year in $(seq 2002 2025); do
  docker compose exec -T backend python -m src.backend.ingest.sync_dou --year $year
done
docker compose exec backend python -m src.backend.ingest.sync_dou --year 2026
```

The DOU catalog registry (`ops/data/dou_catalog_registry.json`) maps 289 months (2002-01 to 2026-01) to Liferay folder IDs and ZIP filenames (851 ZIPs total).

By default, all persistent Docker data lives in Docker-managed named volumes:

```text
mongo_data
elastic_data
dou_data
```

### 4. Elasticsearch

Initialize Elasticsearch from inside the backend container:

```bash
docker compose up -d elasticsearch backend worker
docker compose exec -T backend python -m src.backend.ingest.es_indexer backfill
```

The stack now uses project-scoped image/container names consistently:

```text
gabi-kimi-mongo
gabi-kimi-elasticsearch
gabi-kimi-backend
gabi-kimi-frontend
```

MongoDB and Elasticsearch use the official upstream images directly; only the container names are project-scoped.

### 5. Verify

```bash
# MongoDB count
docker compose exec -T backend python - <<'PY'
from pymongo import MongoClient
print(MongoClient('mongodb://mongo:27017')['gabi_dou']['documents'].count_documents({}))
PY

# ES health
docker compose exec -T elasticsearch curl -s localhost:9200/_cluster/health | docker compose exec -T backend python -m json.tool

# ES document count
docker compose exec -T elasticsearch curl -s localhost:9200/gabi_documents_v1/_count | docker compose exec -T backend python -m json.tool

# Parity check (MongoDB vs ES counts)
docker compose exec -T backend python -m src.backend.ingest.es_indexer stats
```

## ES Indexer

The indexer (`src/backend/ingest/es_indexer.py`) reads from MongoDB and bulk-indexes into Elasticsearch using cursor-based pagination.

```bash
# Full reindex (resets cursor, re-reads all MongoDB docs)
docker compose exec -T backend python -m src.backend.ingest.es_indexer backfill

# Incremental sync (from last cursor position)
docker compose exec -T backend python -m src.backend.ingest.es_indexer sync

# Show counts and parity
docker compose exec -T backend python -m src.backend.ingest.es_indexer stats

# Nuclear option: delete index and rebuild
docker compose exec -T backend python -m src.backend.ingest.es_indexer backfill --recreate-index
```

Cursor state is persisted at `ES_SYNC_CURSOR_PATH`, which defaults to `/data/gabi_dou/es_sync_cursor.json` inside the backend container.

After the initial backfill, `src.backend.ingest.sync_dou` automatically triggers an incremental ES sync at the end of each run.

## Reindex V2

The v2 reindex work is staged through a canary path before any broad historical backfill. The current execution artifacts live in:

- `docs/REINDEX_V2_MINIMUM.md`
- `docs/REINDEX_V2_FULL_FIELDS.md`
- `docs/REINDEX_V2_EXECUTION_PLAN.md`
- `docs/REINDEX_V2_SEARCH_CANARY.md`

Typical preflight and canary commands:

```bash
# Check whether the environment is ready for a broader canary/backfill
docker compose exec -T backend python -m src.backend.ingest.reindex_v2 preflight \
  --schema v2_search \
  --glob 'ops/data/raw_export/2002/01/*.zip' \
  --source-collection documents \
  --mongo-collection documents_v2_canary \
  --es-index gabi_documents_v2_search_canary

# Run a local canary against a limited ZIP sample
docker compose exec -T backend python -m src.backend.ingest.reindex_v2 local-canary \
  --schema v2_search \
  --glob 'ops/data/raw_export/2002/01/*.zip' \
  --source-collection documents \
  --mongo-collection documents_v2_canary \
  --es-index gabi_documents_v2_search_canary
```

Current preflight blockers depend on the machine. The default storage target is Docker-managed volumes; override those paths in `.env` only if you want bind mounts on a specific host disk.

## Repo Assistance Index

For containerized codebase search and future agent assistance, the repo can build a hidden SQLite index under `.ai/` inside the backend container with FTS5 and an optional embedding cache.

```bash
# Lexical-only build
docker compose exec -T backend python -m src.backend.repo_index build

# Optional embedding cache build (uses OPENAI_API_KEY / EMBED_* from .env)
docker compose exec -T backend python -m src.backend.repo_index build --with-embeddings

# Lexical-only query
docker compose exec -T backend python -m src.backend.repo_index query "multipart reconstruction" --mode lexical

# Embeddings-only query (requires build --with-embeddings first)
docker compose exec -T backend python -m src.backend.repo_index query "multipart reconstruction" --mode semantic

# Hybrid query (lexical + embeddings; falls back to lexical if no embedding cache exists)
docker compose exec -T backend python -m src.backend.repo_index query "multipart reconstruction" --mode hybrid

# Stats
docker compose exec -T backend python -m src.backend.repo_index stats
```

The `.ai/` directory is container-generated and ignored by git. The first lexical build on this repo created:

- `.ai/repo_index.db`
- `.ai/manifest.json`

with roughly `5,979` files and `9,541` chunks indexed.

## Adversarial API Testing

The sanctioned way to run the FastAPI adversarial suite is from the Linux host that owns the Python environment and services. Do not trust results from a macOS SMB-mounted view of the repo: stale `__pycache__` and cross-filesystem behavior can produce false failures.

Use the remote runner:

```bash
# Default: 3 full runs on the target host alias (1065 HTTP calls total with the current harness)
ops/bin/run_adversarial_remote.sh

# Single run
ops/bin/run_adversarial_remote.sh --runs 1

# Keep the API running after the suite
ops/bin/run_adversarial_remote.sh --runs 1 --keep-server
```

What the runner does:

1. SSHes into the configured host alias (`ubuntu-vm` by default)
2. Starts the Docker services it needs
3. Restarts the backend for a clean app start
4. Waits for health on `127.0.0.1:8001`
5. Runs `ops/test_api_adversarial.py`
6. Stores logs under `~/.local/state/gabi-kimi/adversarial-remote` on the Linux host
7. Stops the backend container unless `--keep-server` is set

The test harness also accepts a custom base URL through `GABI_API_BASE`, which is useful for CI or a remote box already running the API.

```bash
docker compose exec backend python ops/test_api_adversarial.py
```

## Docker-Only Workflow

The repo now runs entirely inside containers. No host `node`, `npm`, `python`, `pip`, MongoDB, or Elasticsearch installation is required.

Optional: install the repo MCP entry into machine-local client configs from inside a container:

```bash
docker compose run --rm -T \
  -v "$HOME:/host-home" \
  backend \
  python ops/bin/install_repo_mcp_clients.py \
  --home /host-home \
  --repo-root "$PWD" \
  --create-missing
```

That installer writes `gabi-es` into the supported machine-local client configs it finds, including:

- `~/Library/Application Support/Claude/claude_desktop_config.json`
- `~/.codex/config.toml`
- `~/Library/Application Support/Code/User/mcp.json`
- `~/.cursor/mcp.json`
- `~/.gemini/settings.json`
- `~/.kimi/mcp.json`
- `~/.qwen/settings.json`
- `~/.config/zed/settings.json`
- `~/Library/Application Support/Zed/settings.json`
- `~/.kiro/settings/mcp.json`
- `~/.kilo/settings/mcp.json`

with a `gabi-es` entry that launches the MCP server inside Docker:

```text
docker compose -f /absolute/path/to/docker-compose.yml run --rm -T backend python ops/bin/mcp_es_server.py
```

## MCP Server (Claude Code Integration)

The MCP server (`ops/bin/mcp_es_server.py`) exposes 5 tools for searching DOU via Claude Code:

| Tool | Description |
|---|---|
| `es_search` | BM25 full-text search with filters, highlights, pagination |
| `es_suggest` | Autocomplete on title, organ, and type fields |
| `es_facets` | Aggregations for sections, types, organs, date histogram |
| `es_document` | Fetch a single document by ID |
| `es_health` | Cluster and index health summary |

Configured in the machine-wide Claude desktop MCP config as `gabi-es`. The repo-local `.mcp.json` is intentionally not used.

The server auto-infers filters from natural language queries (e.g., "decreto do1 ministerio da saude" applies section, type, and organ filters automatically).

## MongoDB Schema

Primary collection: `documents`

| Field | Type | Description |
|---|---|---|
| `_id` | string | Deterministic hash or Mongo object ID, depending on ingest path |
| `pub_date` | datetime | Publication date |
| `section` | string | DOU section (DO1, DO2, DO3, etc.) |
| `edition` | string | Edition number |
| `page` | int | Page number |
| `art_type` | string | Act type (Decreto, Portaria, Edital, etc.) |
| `art_category` | string | Full category path |
| `orgao` | string | Issuing organ |
| `identifica` | string | Document title/identifier |
| `ementa` | string | Summary |
| `texto` | string | Plain text content (searchable) |
| `content_html` | string | Original HTML content |
| `structured` | object | Legacy structured fields |
| `source_zip` | string | Origin ZIP filename |
| `references` | array | Legal references found in text |
| `enrichment` | object | Optional derived/enrichment fields |

For the v2 parse/store contract and expanded field surface, see `docs/REINDEX_V2_FULL_FIELDS.md`.

## ES Index Mapping

Index: `gabi_documents_v1` (defined in `src/backend/search/es_index_v1.json`)

Uses a `pt_folded` analyzer (standard tokenizer + lowercase + asciifolding) for Portuguese text without diacritics sensitivity.

Field boost weights for search: `identifica^5 > ementa^4 > issuing_organ^2 = art_type^2 > art_category > body_plain`.

## Project Structure

```
src/
  backend/
    api/              # FastAPI routes
    core/config.py    # Settings (Mongo, ES, paths)
    data/             # DB connection, models
    ingest/
      downloader.py   # Downloads ZIPs from in.gov.br
      dou_processor.py # Parses XML → DouDocument
      es_indexer.py   # MongoDB → Elasticsearch indexer
    search/
      es_index_v1.json # ES mapping definition
    services/         # Business logic
  frontend/web/       # Vite + React + Tailwind app
ops/
  bin/
    mcp_es_server.py  # MCP server for Claude Code
  data/               # Catalog registry, cursor state
  setup_elasticsearch.sh
  run_full_ingest.sh
    ingest/sync_dou.py # Main ingestion orchestrator
```

## Environment Variables

Defined in `.env`:

| Variable | Default | Description |
|---|---|---|
| `MONGO_STRING` | `mongodb://mongo:27017/gabi_dou` | MongoDB connection URI inside Docker |
| `DB_NAME` | `gabi_dou` | MongoDB database name |
| `ES_URL` | `http://elasticsearch:9200` | Elasticsearch URL inside Docker |
| `ES_INDEX` | `gabi_documents_v1` | ES index name |
| `ES_SYNC_CURSOR_PATH` | `/data/gabi_dou/es_sync_cursor.json` | Persistent ES sync cursor inside the backend container |
| `GABI_CORS_ORIGINS` | `http://localhost:8081,http://127.0.0.1:8081` | Allowed browser origins for the Dockerized frontend |
| `WORKER_BATCH_SIZE` | `1000` | Batch size used by the background ES sync worker |
| `WORKER_POLL_INTERVAL_SEC` | `30` | Sleep interval between worker sync passes |

## Data Flow

1. **Download**: `src.backend.ingest.sync_dou` reads the catalog registry and downloads ZIPs from `in.gov.br/documents`
2. **Parse**: `dou_processor.py` extracts XMLs from ZIPs, parses into `DouDocument` models
3. **Store**: Bulk upsert into MongoDB (`documents` collection)
4. **Archive**: ZIPs copied into `/data/gabi_dou` inside the shared Docker volume, extracted XMLs deleted
5. **Index**: ES incremental sync runs automatically at end of ingestion
6. **Search**: MCP server or API queries Elasticsearch with BM25
