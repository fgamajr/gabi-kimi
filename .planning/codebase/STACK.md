# Technology Stack

**Analysis Date:** 2026-03-11

## Languages

**Primary:**
- Python 3.12+ - All backend services, data pipelines, MCP servers

**Secondary:**
- None - Project is Python-only

## Runtime

**Environment:**
- CPython 3.12.4 (pyenv-managed)
- No virtual environment committed; developers expected to create one

**Package Manager:**
- pip 26.0.1
- Lockfile: Not present (only `requirements.txt` with unpinned versions)

## Frameworks

**Core:**
- FastAPI - REST API framework (`src/backend/main.py`)
- Pydantic v2 - Data validation and settings management
- MCP (Model Context Protocol) - AI tool server framework for Claude integration

**Testing:**
- pytest (in `archive_legacy/` only, not current codebase)
- asyncio_mode enabled for async tests

**Build/Dev:**
- Ruff - Linting and formatting (pyflakes + pycodestyle errors)
- No build step required (interpreted Python)

## Key Dependencies

**Critical:**
- `pymongo` - MongoDB driver for document storage
- `httpx` - HTTP client for Elasticsearch API calls
- `lxml` - XML parsing for DOU document extraction
- `pydantic-settings` - Configuration management with `.env` support
- `mcp` - Model Context Protocol server implementation
- `fastapi` - REST API framework
- `uvicorn` - ASGI server for FastAPI
- `requests` - HTTP client for downloading ZIPs
- `python-dotenv` - `.env` file loading

**Infrastructure:**
- `bson` (from pymongo) - BSON/ObjectId handling for MongoDB

## Configuration

**Environment:**
- Pydantic Settings with `.env` file loading
- Config class: `src/backend/core/config.py`
- Settings singleton: `settings = Settings()`
- `.env`, `.env.example`, `.env.local` files present (do not read contents)

**Key Configuration Files:**
- `requirements.txt` - Python dependencies (unpinned)
- `ops/data/dou_catalog_registry.json` - Maps YYYY-MM to folder IDs for downloading
- `src/backend/search/es_index_v1.json` - Elasticsearch index mapping

**Required Environment Variables:**
```
MONGO_STRING       # MongoDB connection URI
DB_NAME            # Database name (default: gabi_dou)
ES_URL             # Elasticsearch URL (default: http://localhost:9200)
ES_INDEX           # ES index name (default: gabi_documents_v1)
DOU_DATA_PATH      # Local data storage path
ICLOUD_DATA_PATH   # iCloud archive path (optional)
```

## Platform Requirements

**Development:**
- Python 3.12+
- MongoDB instance (local or Atlas)
- Elasticsearch 8.x instance (local or remote)
- ~2GB+ free disk for temporary ZIP extraction

**Production:**
- MongoDB Atlas (cloud) or self-hosted MongoDB 7.x
- Elasticsearch 8.15.4+ (self-hosted Docker recommended)
- No specific cloud provider required (runs locally or any VM)

## Data Storage

**Primary Database:**
- MongoDB 7.x - Document storage for ~7M DOU documents (2002-2026)
- Collection: `documents`
- Connection via `pymongo.MongoClient`

**Search Engine:**
- Elasticsearch 8.x - BM25 full-text search index
- Index: `gabi_documents_v1`
- Custom Portuguese analyzer with ASCII folding

**File Storage:**
- Local filesystem for temporary processing
- iCloud (optional) for ZIP archive storage
- No object storage (S3) in current implementation

## Code Quality Tools

**Linter/Formatter:**
- Ruff with 120 char line length
- Ignored rules: E402 (imports after code), E501 (line length)
- Configuration in `archive_legacy/pyproject.toml` (inherited by convention)

**No CI/CD:**
- No `.github/` directory
- No automated testing pipeline
- Manual deployment assumed

---

*Stack analysis: 2026-03-11*
