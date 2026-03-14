# Architecture

**Analysis Date:** 2026-03-11

## Pattern Overview

**Overall:** Pipeline-oriented batch processing with dual storage (MongoDB + Elasticsearch)

**Key Characteristics:**
- **ETL Pipeline**: Sequential stages for download, parse, store, index
- **Dual Storage**: MongoDB as source of truth, Elasticsearch for search
- **Cursor-based Pagination**: Stateless incremental sync using MongoDB `_id` cursors
- **MCP Server**: External tool interface via stdio/SSE transport
- **Pydantic Models**: Strong typing with validation throughout data layer

## Layers

### Ingestion Layer
- Purpose: Download and parse DOU ZIP archives from in.gov.br
- Location: `src/backend/ingest/`
- Contains:
  - `downloader.py` - HTTP client for Liferay document portal
  - `dou_processor.py` - XML parsing, text extraction, entity recognition
  - `es_indexer.py` - MongoDB to Elasticsearch sync
- Depends on: `src/backend/core/config.py`, `src/backend/data/models/`
- Used by: `sync_dou.py` (orchestrator)

### Data Layer
- Purpose: Database connections and data models
- Location: `src/backend/data/`
- Contains:
  - `db.py` - MongoDB singleton connection
  - `models/document.py` - Pydantic models for DOU documents
- Depends on: `src/backend/core/config.py`, `pymongo`, `pydantic`
- Used by: Ingestion layer, MCP server, API layer

### Core Layer
- Purpose: Centralized configuration management
- Location: `src/backend/core/config.py`
- Contains: Pydantic Settings class with environment variable binding
- Depends on: `pydantic-settings`, `.env` file
- Used by: All other layers

### Search Layer
- Purpose: Elasticsearch index definition and search utilities
- Location: `src/backend/search/`
- Contains:
  - `es_index_v1.json` - BM25 index mapping with Portuguese analyzer
- Depends on: Elasticsearch cluster
- Used by: `es_indexer.py`, MCP server

### API Layer
- Purpose: HTTP API for frontend integration
- Location: `src/backend/main.py`, `src/backend/api/`
- Contains: FastAPI application with startup/shutdown hooks
- Depends on: `src/backend/data/db.py`
- Used by: Frontend (not yet implemented)

### MCP Server Layer
- Purpose: Expose search tools to Claude Code and other MCP clients
- Location: `ops/bin/mcp_es_server.py`
- Contains: 5 search tools (es_search, es_suggest, es_facets, es_document, es_health)
- Depends on: `httpx`, Elasticsearch, `mcp` package
- Used by: Claude Code via `.mcp.json` configuration

## Data Flow

### Ingestion Pipeline

1. **Orchestration** (`sync_dou.py`):
   - Reads catalog registry for folder IDs and ZIP filenames
   - Iterates by year/month, invokes downloader

2. **Download** (`downloader.py`):
   - Constructs URLs from registry: `https://www.in.gov.br/documents/{GROUP_ID}/{folder_id}/{filename}`
   - Downloads ZIP content, saves to temp directory

3. **Parse** (`dou_processor.py`):
   - Extracts XMLs from ZIP
   - Parses XML with lxml (recover mode for malformed XML)
   - Extracts metadata, content, references, entities
   - Generates deterministic `_id` from content hash

4. **Store** (`sync_dou.py::ingest_documents`):
   - Bulk upsert to MongoDB `documents` collection
   - Uses `UpdateOne` with `upsert=True`

5. **Archive** (`sync_dou.py::archive_and_cleanup`):
   - Copies ZIP to iCloud shared folder with size verification
   - Deletes local ZIP and extracted XMLs

6. **Index** (`es_indexer.py`):
   - Reads from MongoDB with cursor-based pagination
   - Transforms to ES schema via `_mongo_to_es()`
   - Bulk indexes with retry logic

### Search Flow

1. **Query** → MCP tool `es_search()`
2. **Filter Inference** → `_infer_request_filters()` extracts section, art_type, organ from query
3. **ES Query Build** → `_query_clause()` with field boosts, `_build_filters()` for date/range
4. **Elasticsearch** → BM25 search with `pt_folded` analyzer
5. **Response** → Formatted with highlights, snippets, pagination metadata

## Key Abstractions

### DouDocument (Pydantic Model)
- Purpose: Represents a DOU legal document with full metadata
- Examples: `src/backend/data/models/document.py`
- Pattern: Pydantic `BaseModel` with nested models for structured data
- Key fields:
  - `id` (alias `_id`) - Deterministic hash for MongoDB
  - `pub_date` - Publication datetime
  - `texto` - Plain text content (searchable)
  - `content_html` - Original HTML (display)
  - `references` - Extracted legal citations
  - `structured` - Parsed act number/year

### ESClient
- Purpose: Elasticsearch HTTP client with retry and auth
- Examples: `src/backend/ingest/es_indexer.py`, `ops/bin/mcp_es_server.py`
- Pattern: Class-based wrapper around `httpx.Client`
- Features:
  - Configurable timeout, TLS verification
  - Basic auth support
  - Bulk indexing with retry on 429/502/503/504

### MongoDB (Singleton)
- Purpose: Global database connection management
- Examples: `src/backend/data/db.py`
- Pattern: Class with `@classmethod` for connection pooling
- Usage: `MongoDB.get_db()` returns database handle

## Entry Points

### sync_dou.py
- Location: `sync_dou.py`
- Triggers: Manual execution via CLI
- Responsibilities:
  - Orchestrates full ingestion pipeline
  - Disk space monitoring
  - Progress logging
  - Automatic ES sync at completion

### es_indexer.py
- Location: `src/backend/ingest/es_indexer.py`
- Triggers: CLI with subcommands (`backfill`, `sync`, `stats`)
- Responsibilities:
  - Creates ES index if missing
  - Bulk indexes documents with cursor persistence
  - Reports parity between MongoDB and ES

### mcp_es_server.py
- Location: `ops/bin/mcp_es_server.py`
- Triggers: MCP client (Claude Code) via stdio or SSE
- Responsibilities:
  - Exposes search tools
  - Filter inference from natural language
  - Error handling with graceful degradation

### main.py (FastAPI)
- Location: `src/backend/main.py`
- Triggers: uvicorn server
- Responsibilities:
  - HTTP API skeleton
  - MongoDB connection lifecycle

## Error Handling

**Strategy:** Graceful degradation with logging

**Patterns:**
- Try/except with logging for non-critical failures (ES sync after ingestion)
- Empty list returns with warning for parse failures
- Retry logic in ES bulk operations (exponential backoff)
- Optional returns with None for missing data

```python
# Pattern: Non-fatal sync failure
try:
    _run_sync(reset_cursor=False, recreate_index=False, batch_size=2000)
except Exception as e:
    logger.warning(f"ES sync failed (non-fatal): {e}")

# Pattern: Parse error with logging
except Exception as e:
    logger.error(f"Error processing {filename}: {e}")
    return None
```

## Cross-Cutting Concerns

**Logging:**
- Standard library `logging` module
- Format: `'%(asctime)s - %(levelname)s - %(message)s'`
- Output: stdout (streaming)

**Validation:**
- Pydantic models for all data structures
- Environment variable validation via `pydantic-settings`
- XML parsing with `recover=True` for malformed content

**Configuration:**
- `.env` file for secrets and environment-specific values
- `Settings` class with defaults for optional values
- `extra = "ignore"` for forward compatibility

**Authentication:**
- MongoDB: Connection string in `MONGO_STRING`
- Elasticsearch: Optional basic auth via `ES_USERNAME`/`ES_PASSWORD`
- No application-level auth (internal tool)

---

*Architecture analysis: 2026-03-11*
