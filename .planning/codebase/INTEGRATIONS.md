# External Integrations

**Analysis Date:** 2026-03-11

## APIs & External Services

**Government Data Source:**
- in.gov.br (Portal da Imprensa) - Official gazette XML downloads
  - SDK/Client: `requests` with custom User-Agent
  - URL Pattern: `https://www.in.gov.br/documents/{GROUP_ID}/{folder_id}/{filename}`
  - GROUP_ID: `49035712` (hardcoded in `src/backend/ingest/downloader.py`)
  - Auth: None required (public access)
  - Registry: `ops/data/dou_catalog_registry.json` maps months to folder IDs

**AI/LLM Integration (Optional):**
- OpenAI-compatible API - Embedding generation
  - SDK/Client: `httpx` (custom client in `archive_legacy/`)
  - Env vars: `EMBED_API_KEY`, `OPENAI_API_KEY`, `EMBED_BASE_URL`
  - Models: `text-embedding-3-small` (384 dims)
  - Purpose: Vector embeddings for hybrid search

**Chat Proxy (Optional):**
- Qwen API (Alibaba DashScope) - Chat completions
  - Env vars: `QWEN_API_KEY`, `DASHSCOPE_API_KEY`
  - Model: `qwen-plus`
  - Base URL: `https://coding-intl.dashscope.aliyuncs.com/v1`

**Anthropic API (Optional):**
- For multi-agent convergence MCP
  - Env var: `ANTHROPIC_API_KEY`

## Data Storage

**Databases:**
- MongoDB (Atlas or self-hosted)
  - Connection: `MONGO_STRING` env var (MongoDB URI)
  - Database: `gabi_dou` (configurable via `DB_NAME`)
  - Collection: `documents`
  - Client: `pymongo.MongoClient`
  - Index: MongoDB Atlas Search index `default` (for vector/hybrid search)

**Search Engine:**
- Elasticsearch 8.x
  - Connection: `ES_URL` env var (default: `http://localhost:9200`)
  - Index: `gabi_documents_v1`
  - Client: `httpx.Client` with optional basic auth
  - Auth: `ES_USERNAME`/`ES_PASSWORD` env vars (optional)
  - TLS: `ES_VERIFY_TLS` env var (default: true)

**File Storage:**
- Local filesystem - Primary storage for processing
  - Temp path: `/tmp/gabi-pipeline` (configurable via `PIPELINE_TMP`)
  - Archive path: iCloud mount (optional, via `ICLOUD_DATA_PATH`)
- No S3/object storage in current codebase

**Caching:**
- Redis (optional, in `.env.example` but not in main codebase)
  - URL: `REDIS_URL` (e.g., `redis://localhost:6380/0`)
  - Purpose: Query-assist, admin upload job queue

## Authentication & Identity

**Auth Provider:**
- Custom Bearer token authentication
  - Implementation: Token-based API auth
  - Env vars: `GABI_API_TOKENS` (comma-separated tokens)
  - Admin tokens: `GABI_ADMIN_TOKEN_LABELS`
  - Session: `GABI_AUTH_SECRET`, `GABI_SESSION_COOKIE`, `GABI_SESSION_TTL_SEC`

**Email Verification (Optional):**
- Resend API
  - Env vars: `RESEND_API_KEY`, `RESEND_FROM`
  - Purpose: User email verification

## Monitoring & Observability

**Error Tracking:**
- Sentry (optional)
  - Env vars: `SENTRY_DSN_BACKEND`, `SENTRY_DSN_WORKER`, `VITE_SENTRY_DSN_FRONTEND`
  - Not actively configured in current codebase

**Logs:**
- Python `logging` module with stdout stream handler
- Format: `%(asctime)s - %(levelname)s - %(message)s`
- No structured logging or log aggregation

## CI/CD & Deployment

**Hosting:**
- No specific platform required
- Designed for local/Docker deployment
- Fly.io mentioned in `.env.example` comments

**CI Pipeline:**
- None - No `.github/` directory

**Container Services:**
- MongoDB: `mongo:7` Docker image
- Elasticsearch: `docker.elastic.co/elasticsearch/elasticsearch:8.15.4`

## Environment Configuration

**Required env vars (core functionality):**
```
MONGO_STRING         # MongoDB connection URI (required)
DB_NAME              # Database name
ES_URL               # Elasticsearch URL
ES_INDEX             # Elasticsearch index name
DOU_DATA_PATH        # Local data path
```

**Optional env vars (enhanced features):**
```
ES_USERNAME          # Elasticsearch auth
ES_PASSWORD          # Elasticsearch auth
ES_VERIFY_TLS        # TLS verification
ES_TIMEOUT_SEC       # Request timeout
ICLOUD_DATA_PATH     # iCloud archive path
SEARCH_BACKEND       # pg | es | hybrid
EMBED_API_KEY        # OpenAI embeddings
OPENAI_API_KEY       # OpenAI API key
QWEN_API_KEY         # Qwen chat
REDIS_URL            # Redis cache
```

**Secrets location:**
- `.env` file (gitignored)
- No secrets manager integration

## Webhooks & Callbacks

**Incoming:**
- None - No webhook endpoints defined

**Outgoing:**
- None - No outbound webhooks

## MCP Server Integration

**Model Context Protocol:**
- `ops/bin/mcp_es_server.py` - Standalone ES search MCP server
- `src/backend/mcp_server.py` - MongoDB Atlas Search MCP server
- Transport: stdio (default) or SSE
- SSE port: 8766 (configurable)

**MCP Tools Exposed:**
- `es_search` - BM25 full-text search with filters
- `es_suggest` - Autocomplete suggestions
- `es_facets` - Facet aggregations
- `es_document` - Single document fetch
- `es_health` - Cluster health check
- `search_dou` - MongoDB Atlas Search (hybrid)

## Database Schemas

**MongoDB Document Schema:**
```python
# From src/backend/data/models/document.py
DouDocument:
  _id: str                    # Deterministic ID (date + section + hash)
  source_id: str              # Original XML filename
  source_zip: str             # ZIP archive filename
  source_type: "inlabs" | "liferay" | "manual"
  pub_date: datetime          # Publication date
  section: str                # DO1, DO2, DO3
  art_type: str               # Act type (decreto, portaria, etc.)
  orgao: str                  # Issuing organ
  identifica: str             # Title/identifier
  ementa: str                 # Abstract/summary
  texto: str                  # Full text (plain)
  content_html: str           # Original HTML
  structured: StructuredData  # Parsed act number, year, signer
  references: List[Reference] # Legal references
  affected_entities: List[str]
  embedding: List[float]      # Vector embedding (optional)
```

**Elasticsearch Index Mapping:**
```json
// From src/backend/search/es_index_v1.json
{
  "doc_id": keyword,
  "identifica": text (pt_folded) + keyword,
  "ementa": text (pt_folded),
  "body_plain": text (pt_folded),
  "art_type": text (pt_folded) + keyword,
  "issuing_organ": text (pt_folded) + keyword,
  "edition_section": keyword,
  "pub_date": date,
  "document_number": keyword,
  "document_year": integer
}
```

---

*Integration audit: 2026-03-11*
