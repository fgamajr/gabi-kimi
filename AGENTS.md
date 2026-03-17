# AGENTS.md - Guidelines for AI Coding Agents

## Project Overview

**GABI (Gestão Automatizada de Busca Inteligente)** is a full-text search platform for Brazil's official gazette (Diário Oficial da União - DOU). It processes ~16M legal documents from 2002-2026, providing enterprise-grade BM25 search over the complete DOU corpus.

### Data Flow Architecture

```
in.gov.br (Liferay ZIPs)
    ↓  src.backend.ingest.sync_dou
MongoDB (documents collection)
    ↓  es_indexer.py
Elasticsearch (BM25 full-text)
    ↑
MCP Server (13 tools) ← Claude Code / AI Agents
    ↑
FastAPI Backend ← React Frontend
```

### Runtime Topology (Docker Compose)

| Service | Container Name | Port | Description |
|---------|---------------|------|-------------|
| MongoDB | gabi-kimi-mongo | 27017 | Document storage |
| Elasticsearch | gabi-kimi-elasticsearch | 9200 | BM25 search index |
| Backend | gabi-kimi-backend | 8001 | FastAPI API server |
| Worker | gabi-kimi-worker | - | Background ES sync loop |
| Frontend | gabi-kimi-frontend | 8081 | Vite + React dev server |

Container-to-container networking uses Docker DNS:
- `frontend → backend:8000`
- `backend → mongo:27017`
- `backend → elasticsearch:9200`
- `worker → mongo:27017`, `elasticsearch:9200`

## Technology Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.12+ |
| Web Framework | FastAPI, uvicorn |
| Database | MongoDB 7 |
| Search | Elasticsearch 8.15.4 (BM25) |
| Frontend | Vite + React 18 + TypeScript + Tailwind CSS 3 |
| UI Components | Radix UI primitives + shadcn/ui patterns |
| MCP Framework | FastMCP (stdio/SSE transports) |
| HTTP Client | httpx |
| Data Validation | Pydantic v2 |

## Build, Test & Development Commands

### Docker Compose Operations

```bash
# Build and start the full stack
docker compose up --build

# Start specific services only
docker compose up -d mongo elasticsearch

# View logs
docker compose logs -f backend
docker compose logs -f worker

# Restart a service
docker compose restart backend
```

### Data Ingestion (MongoDB)

```bash
# Single year
docker compose exec backend python -m src.backend.ingest.sync_dou --year 2024

# Single month
docker compose exec backend python -m src.backend.ingest.sync_dou --year 2024 --month 6

# With XML extraction to disk (for debugging)
docker compose exec backend python -m src.backend.ingest.sync_dou --year 2024 --extract-xmls

# Skip ES sync at end of run
docker compose exec backend python -m src.backend.ingest.sync_dou --year 2024 --skip-es-sync
```

### Elasticsearch Indexing

```bash
# Full backfill (resets cursor, re-reads all MongoDB docs)
docker compose exec backend python -m src.backend.ingest.es_indexer backfill

# Incremental sync (from last cursor position)
docker compose exec backend python -m src.backend.ingest.es_indexer sync

# Show counts and parity check
docker compose exec backend python -m src.backend.ingest.es_indexer stats

# Nuclear option: delete index and rebuild
docker compose exec backend python -m src.backend.ingest.es_indexer backfill --recreate-index

# Custom batch size
docker compose exec backend python -m src.backend.ingest.es_indexer sync --batch-size 2000
```

### MCP Server

```bash
# stdio transport (for Claude Code integration)
python ops/bin/mcp_es_server.py

# SSE transport (for HTTP clients)
python ops/bin/mcp_es_server.py --transport sse --port 8766
```

### Linting & Formatting

```bash
# Lint check
ruff check .

# Auto-fix linting issues
ruff check . --fix

# Format code
ruff format .
```

### Frontend (inside container)

```bash
# The frontend runs via Docker. To run commands inside:
docker compose exec frontend sh
cd /workspace/src/frontend/app
npm run dev      # Dev server (already running by default)
npm run build    # Production build
npm run lint     # ESLint
npm run test     # Vitest
```

### Testing

No formal test suite in main codebase. Ad-hoc tests in `ops/`:

```bash
# Test MongoDB connection
docker compose exec backend python ops/test_mongo_connection.py

# Test ZIP extraction
docker compose exec backend python ops/test_extraction.py

# Test MCP tools
docker compose exec backend python ops/test_mcp_tools.py

# Adversarial API testing (from Linux host)
ops/bin/run_adversarial_remote.sh
```

## Code Style Guidelines

### Python Version & Tooling

- **Python 3.12+**
- **Line length**: 120 characters
- **Linter/Formatter**: Ruff
- **Ignored rules**: E402 (imports after code), E501 (line length handled by formatter)

### Import Order

```python
# 1. Future annotations (if needed)
from __future__ import annotations

# 2. Standard library (alphabetical)
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# 3. Third-party (alphabetical)
import httpx
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from pymongo import MongoClient, UpdateOne

# 4. Local imports (absolute paths from src/)
from src.backend.core.config import settings
from src.backend.data.db import MongoDB
from src.backend.data.models.document import DouDocument
```

### Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Files | snake_case | `dou_processor.py`, `es_indexer.py` |
| Classes | PascalCase | `DouDocument`, `ESClient`, `MongoDB` |
| Functions | snake_case | `parse_date()`, `generate_id()`, `process_zip()` |
| Constants | UPPER_SNAKE | `BASE_URL`, `GROUP_ID`, `_MAPPING_PATH` |
| Private functions | Leading underscore | `_log()`, `_env_bool()`, `_load_cursor()` |
| Variables | snake_case | `pub_date`, `art_type`, `zip_filename` |
| Model fields | snake_case | `pub_date`, `art_type`, `issuing_organ` |

### Type Annotations

Use modern Python type hints:

```python
from typing import Any, Optional

def _mongo_to_es(doc: dict[str, Any]) -> dict[str, Any]:
    ...

def _infer_filters(query: str) -> tuple[str, str | None, str | None]:
    ...

class DouDocument(BaseModel):
    pub_date: datetime
    art_type: Optional[str] = None
```

### Error Handling

```python
# 1. Try/except with logging
try:
    result = collection.bulk_write(operations)
    logger.info(f"Upserted {result.upserted_count} documents")
except Exception as e:
    logger.error(f"Bulk write failed: {e}")

# 2. Graceful degradation (non-critical failures)
try:
    _run_sync()
except Exception as e:
    logger.warning(f"ES sync failed (non-fatal): {e}")

# 3. None-safe returns with logging
def parse_date(self, date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str.strip(), "%d/%m/%Y")
    except ValueError:
        logger.warning(f"Failed to parse date: {date_str}")
        return None
```

### Configuration Pattern

Use Pydantic Settings with `.env` file:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    MONGO_STRING: str = "mongodb://mongo:27017/gabi_dou"
    DB_NAME: str = "gabi_dou"
    ES_URL: str = "http://elasticsearch:9200"
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
```

### Pydantic Models

```python
from pydantic import BaseModel, Field
from typing import Optional, List

class StructuredData(BaseModel):
    act_number: Optional[str] = None
    act_year: Optional[int] = None
    signer: Optional[str] = None

class DouDocument(BaseModel):
    id: str = Field(alias="_id")  # MongoDB _id mapping
    source_id: str
    pub_date: datetime
    texto: str
    
    class Config:
        populate_by_name = True
        extra = "allow"  # For forward compatibility
```

### CLI Pattern (argparse with subcommands)

```python
import argparse

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="...")
    sub = p.add_subparsers(dest="cmd", required=True)
    
    sp = sub.add_parser("backfill", help="Full backfill")
    sp.add_argument("--batch-size", type=int, default=2000)
    sp.set_defaults(func=cmd_backfill)
    return p

def main() -> None:
    args = build_parser().parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
```

### MCP Tool Pattern

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("GABI Elasticsearch MCP")

@mcp.tool()
def es_search(query: str, page: int = 1, page_size: int = 20) -> dict[str, Any]:
    """Search DOU documents with BM25 full-text search.
    
    Args:
        query: Search query text
        page: Page number (1-indexed)
        page_size: Results per page
        
    Returns:
        dict with results, total, and pagination info
    """
    # Implementation
    return {"results": [...], "total": 100}
```

### Logging

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

logger.info(f"Processing {count} documents")
logger.error(f"Failed: {e}")
```

## Project Structure

```
src/
  backend/
    core/
      config.py           # Pydantic Settings (Mongo, ES, paths)
    data/
      db.py               # MongoDB connection singleton
      models/
        document.py       # Pydantic models (DouDocument, etc.)
    ingest/
      sync_dou.py         # Main ingestion orchestrator (CLI)
      downloader.py       # Downloads ZIPs from in.gov.br
      dou_processor.py    # Parses XML → DouDocument
      es_indexer.py       # MongoDB → Elasticsearch indexer
      es_v2_minimal.py    # v2 schema: minimal mapping
      es_v2_search.py     # v2 schema: search-optimized
      reindex_v2.py       # v2 reindex orchestrator
      field_extractors.py # Structured data extractors
      reconstruction.py   # Document reconstruction logic
    search/
      es_index_v1.json    # ES mapping definition (current)
      es_index_v2.json    # ES mapping definition (v2)
      es_index_v2_search.json  # v2 search-optimized mapping
      es_index_min_v2.json     # v2 minimal mapping
      es_index_v3.json    # Experimental v3 mapping
      hybrid.py           # Hybrid search (BM25 + vector)
      reranker.py         # Neural reranker client
    api/                  # FastAPI routes (if modularized)
    services/             # Business logic
    main.py               # FastAPI application entry
    mcp_server.py         # Legacy MCP server (use ops/bin/)
    
  frontend/
    app/
      src/
        pages/            # Route pages (HomePage, SearchPage, etc.)
        components/       # React components
          ui/             # shadcn/ui primitive components
        lib/              # Utilities
      public/             # Static assets
      package.json        # npm dependencies
      tsconfig.json       # TypeScript config
      vite.config.ts      # Vite configuration
      tailwind.config.js  # Tailwind CSS config

ops/
  bin/
    mcp_es_server.py      # MCP server entry (13 tools)
    install_repo_mcp_clients.py  # MCP client config installer
    monitor_ingest.sh     # Mongo-based ingest monitor
    run_adversarial_remote.sh    # Remote API testing
    run_overnight_ingest.sh      # Scheduled ingest runner
  container/
    backend-dev.sh        # Backend container startup
    frontend-dev.sh       # Frontend container startup
    worker-dev.sh         # Worker container startup
  data/
    dou_catalog_registry.json    # Maps YYYY-MM to folder IDs
    ingest_state.json            # Ingest progress tracking
  embedding-server/       # MLX embedding server (optional)
  repo_index/             # Repo assistance index tools

docs/
  LIFERAY.md              # Liferay integration notes
  MACHINE_TOOLING.md      # Machine-level tooling
  REINDEX_V2_*.md         # v2 reindex documentation
```

## Environment Variables

Required in `.env` (copy from `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGO_STRING` | `mongodb://mongo:27017/gabi_dou` | MongoDB connection URI |
| `DB_NAME` | `gabi_dou` | MongoDB database name |
| `ES_URL` | `http://elasticsearch:9200` | Elasticsearch URL |
| `ES_INDEX` | `gabi_documents_v1` | ES index name |
| `ES_ALIAS` | `gabi_documents` | ES alias name |
| `ES_SYNC_CURSOR_PATH` | `/data/gabi_dou/es_sync_cursor.json` | Persistent cursor |
| `DOU_DATA_PATH` | `/data/gabi_dou` | Local data storage path |
| `GABI_CORS_ORIGINS` | `http://localhost:8081` | Allowed browser origins |
| `WORKER_BATCH_SIZE` | `1000` | ES sync batch size |
| `WORKER_POLL_INTERVAL_SEC` | `30` | Worker sleep interval |
| `VECTOR_SEARCH_ENABLED` | `false` | Enable hybrid search |
| `EMBED_SERVER_URL` | `http://host.docker.internal:8900` | Embedding server |
| `RERANKER_ENABLED` | `false` | Enable neural reranker |
| `RERANKER_URL` | `http://host.docker.internal:8902` | Reranker server |

## MCP Server Tools (13 Tools)

The MCP server (`ops/bin/mcp_es_server.py`) exposes these tools for AI agents:

| Tool | Description |
|------|-------------|
| `es_search` | Primary search with BM25 + re-ranking. Smart query parsing, quoted phrases, legal references, synonym expansion |
| `es_suggest` | Autocomplete on title, organ, and type fields |
| `es_facets` | Aggregations for sections, types, organs, date histogram |
| `es_document` | Fetch a single document by ID |
| `es_health` | Cluster and index health summary |
| `es_more_like_this` | Find similar documents using TF-IDF |
| `es_significant_terms` | Statistically significant terms for theme discovery |
| `es_timeline` | Temporal distribution of publications |
| `es_trending` | Recent publication activity analysis |
| `es_cross_reference` | Find documents citing a legal reference |
| `es_organ_profile` | Publishing profile for a government organ |
| `es_compare_periods` | Compare results between two time periods |
| `es_explain` | Debug why a document scored as it did |

### MCP Configuration

The server auto-infers filters from natural language queries:
- "decreto do1 ministerio da saude" → applies section, type, and organ filters

## Elasticsearch Index Schema

Index: `gabi_documents_v1` (defined in `src/backend/search/es_index_v1.json`)

Uses a `pt_folded` analyzer (standard tokenizer + lowercase + asciifolding) for Portuguese text without diacritics sensitivity.

Field boost weights for search:
```
identifica^5 > ementa^4 > issuing_organ^2 = art_type^2 > art_category > body_plain
```

### Key Fields

| Field | Type | Description |
|-------|------|-------------|
| `doc_id` | keyword | Document identifier |
| `identifica` | text | Document title (boosted) |
| `ementa` | text | Summary/abstract |
| `body_plain` | text | Full text content |
| `art_type` | text | Act type (Portaria, Decreto, etc.) |
| `art_category` | text | Full category path |
| `issuing_organ` | text | Publishing organ |
| `edition_section` | keyword | DO1, DO2, DO3, DOE |
| `pub_date` | date | Publication date |

## MongoDB Schema

Primary collection: `documents` (configurable via `MONGO_COLLECTION`)

| Field | Type | Description |
|-------|------|-------------|
| `_id` | string | Deterministic hash or ObjectId |
| `source_id` | string | Original source identifier |
| `pub_date` | datetime | Publication date |
| `section` | string | DOU section (DO1, DO2, DO3) |
| `edition` | string | Edition number |
| `page` | int | Page number |
| `art_type` | string | Act type |
| `art_category` | string | Full category path |
| `orgao` / `issuing_organ` | string | Issuing organ |
| `identifica` | string | Document title |
| `ementa` | string | Summary |
| `texto` | string | Plain text content |
| `content_html` | string | Original HTML |
| `structured` | object | Structured fields (act_number, act_year, signer) |
| `source_zip` | string | Origin ZIP filename |
| `references` | array | Legal references found in text |
| `embedding_status` | string | Vector embedding status |

## Deployment

### Docker-Only Workflow

The repo runs entirely inside containers. No host `node`, `npm`, `python`, `pip`, MongoDB, or Elasticsearch installation is required.

### Persistent Data (Docker Volumes)

```
mongo_data      → MongoDB data
elastic_data    → Elasticsearch data
dou_data        → DOU raw files and pipeline
dou_data/host   → Host-mounted via bind mount (optional)
```

### Port Mapping

| Host Port | Container | Service |
|-----------|-----------|---------|
| 27017 | mongo:27017 | MongoDB |
| 9200 | elasticsearch:9200 | Elasticsearch |
| 8001 | backend:8000 | FastAPI |
| 8081 | frontend:8080 | Vite dev server |

## Security Considerations

- Elasticsearch: security disabled (`xpack.security.enabled=false`) for local dev
- CORS configured via `GABI_CORS_ORIGINS`
- No authentication on API by default (add reverse proxy for production)
- `.env` files contain secrets — never commit to git

## Key Files for Development

| File | Purpose |
|------|---------|
| `src/backend/core/config.py` | Central configuration |
| `src/backend/data/models/document.py` | Data models |
| `src/backend/ingest/sync_dou.py` | Main ingest orchestrator |
| `src/backend/ingest/es_indexer.py` | ES indexing logic |
| `src/backend/main.py` | FastAPI app |
| `ops/bin/mcp_es_server.py` | MCP server (13 tools) |
| `docker-compose.yml` | Service definitions |
| `.env.example` | Configuration template |

## Troubleshooting

### Check service health

```bash
# MongoDB
docker compose exec mongo mongosh --eval 'db.runCommand({ping: 1})'

# Elasticsearch
curl http://localhost:9200/_cluster/health

# Backend API
curl http://localhost:8001/

# Frontend
curl http://localhost:8081
```

### Reset ES sync cursor

```bash
rm ops/data/es_sync_cursor.json
# or
docker compose exec backend rm /data/gabi_dou/es_sync_cursor.json
```

### Clear MongoDB and restart

```bash
docker compose exec mongo mongosh gabi_dou --eval 'db.documents.drop()'
docker compose exec backend python -m src.backend.ingest.es_indexer backfill --recreate-index
```
