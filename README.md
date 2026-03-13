# GABI - Busca Inteligente no Diário Oficial da União

Full-text search platform for Brazil's official gazette (DOU), covering 2002–2026. Downloads, processes, and indexes ~7M legal documents for BM25 search via Elasticsearch, with an MCP server for Claude Code integration.

## Architecture

```
in.gov.br (Liferay ZIPs)
    ↓  sync_dou.py
MongoDB (documents collection)
    ↓  es_indexer.py
Elasticsearch (BM25 full-text)
    ↑
MCP Server (5 tools) ← Claude Code
```

## Stack

| Layer | Tech |
|---|---|
| Ingestion | Python, pymongo, requests |
| Database | MongoDB (localhost:27017, db: `gabi_dou`) |
| Search | Elasticsearch 8.15.4 (localhost:9200) |
| MCP | FastMCP (stdio), httpx |
| Backend API | FastAPI, uvicorn |
| Frontend | Vite + React 18 + Tailwind CSS 3 + TypeScript |

## Prerequisites

- Python 3.12+ with pyenv
- Docker (for MongoDB and Elasticsearch)
- Parallels Desktop (for persistent storage on macOS host)

## Quick Start

### 1. MongoDB

```bash
docker run -d --name gabi-mongo \
  -p 27017:27017 \
  -v /media/psf/gabi_mongo:/data/db \
  mongo:7
```

### 2. Ingest DOU Data

First-time full ingestion (2002–2026, ~7M documents):

```bash
# Single year
python3 sync_dou.py --year 2024

# Single month
python3 sync_dou.py --year 2024 --month 6

# Full backfill (all years)
for year in $(seq 2002 2025); do
  python3 sync_dou.py --year $year
done
python3 sync_dou.py --year 2026
```

The DOU catalog registry (`ops/data/dou_catalog_registry.json`) maps 289 months (2002-01 to 2026-01) to Liferay folder IDs and ZIP filenames (851 ZIPs total).

### 3. Elasticsearch

Automated setup (creates index, runs backfill):

```bash
bash ops/setup_elasticsearch.sh
```

Or manually:

```bash
# Create Parallels shared folder first:
#   macOS: mkdir -p ~/Data/gabi_es
#   Parallels > VM Settings > Shared Folders > Add ~/Data/gabi_es

docker run -d --name gabi-es \
  -p 9200:9200 \
  -e discovery.type=single-node \
  -e xpack.security.enabled=false \
  -e "ES_JAVA_OPTS=-Xms512m -Xmx512m" \
  -v /media/psf/gabi_es:/usr/share/elasticsearch/data \
  docker.elastic.co/elasticsearch/elasticsearch:8.15.4

# Wait for ES, then backfill
python3 -m src.backend.ingest.es_indexer backfill
```

### 4. Verify

```bash
# MongoDB count
python3 -c "from pymongo import MongoClient; print(MongoClient('mongodb://localhost:27017')['gabi_dou']['documents'].count_documents({}))"

# ES health
curl -s localhost:9200/_cluster/health | python3 -m json.tool

# ES document count
curl -s localhost:9200/gabi_documents_v1/_count | python3 -m json.tool

# Parity check (MongoDB vs ES counts)
python3 -m src.backend.ingest.es_indexer stats
```

## ES Indexer

The indexer (`src/backend/ingest/es_indexer.py`) reads from MongoDB and bulk-indexes into Elasticsearch using cursor-based pagination.

```bash
# Full reindex (resets cursor, re-reads all MongoDB docs)
python3 -m src.backend.ingest.es_indexer backfill

# Incremental sync (from last cursor position)
python3 -m src.backend.ingest.es_indexer sync

# Show counts and parity
python3 -m src.backend.ingest.es_indexer stats

# Nuclear option: delete index and rebuild
python3 -m src.backend.ingest.es_indexer backfill --recreate-index
```

Cursor state is persisted at `src/backend/data/es_sync_cursor.json`.

After the initial backfill, `sync_dou.py` automatically triggers an incremental ES sync at the end of each run — no manual step needed.

## MCP Server (Claude Code Integration)

The MCP server (`ops/bin/mcp_es_server.py`) exposes 5 tools for searching DOU via Claude Code:

| Tool | Description |
|---|---|
| `es_search` | BM25 full-text search with filters, highlights, pagination |
| `es_suggest` | Autocomplete on title, organ, and type fields |
| `es_facets` | Aggregations for sections, types, organs, date histogram |
| `es_document` | Fetch a single document by ID |
| `es_health` | Cluster and index health summary |

Configured in `.mcp.json` as `gabi-es`. Restart Claude Code after any config changes.

The server auto-infers filters from natural language queries (e.g., "decreto do1 ministerio da saude" applies section, type, and organ filters automatically).

## MongoDB Schema

Collection: `documents`

| Field | Type | Description |
|---|---|---|
| `_id` | string | Deterministic hash: `{date}_{section}_{content_hash}` |
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
| `structured` | object | `{act_number, act_year}` |
| `source_zip` | string | Origin ZIP filename |
| `references` | array | Legal references found in text |
| `enrichment` | object | `{relevance_score, category}` |

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
sync_dou.py           # Main ingestion orchestrator
```

## Environment Variables

Defined in `.env`:

| Variable | Default | Description |
|---|---|---|
| `MONGO_STRING` | `mongodb://localhost:27017/gabi_dou` | MongoDB connection URI |
| `DB_NAME` | `gabi_dou` | MongoDB database name |
| `ES_URL` | `http://localhost:9200` | Elasticsearch URL |
| `ES_INDEX` | `gabi_documents_v1` | ES index name |
| `DOU_DATA_PATH` | `/tmp/gabi-pipeline` | Temp path for downloads |
| `ICLOUD_DATA_PATH` | — | Parallels shared folder for ZIP archival |

## Data Flow

1. **Download**: `sync_dou.py` reads the catalog registry, downloads ZIPs from `in.gov.br/documents`
2. **Parse**: `dou_processor.py` extracts XMLs from ZIPs, parses into `DouDocument` models
3. **Store**: Bulk upsert into MongoDB (`documents` collection)
4. **Archive**: ZIPs copied to iCloud shared folder, extracted XMLs deleted
5. **Index**: ES incremental sync runs automatically at end of ingestion
6. **Search**: MCP server or API queries Elasticsearch with BM25
