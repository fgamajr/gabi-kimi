# AGENTS.md - GABI Codebase Guidelines

## Project
**GABI** — Full-text search platform for Brazil's Diário Oficial da União (~16M documents, 2002-2026). Hosted on Hetzner (gabidou.top). Python 3.12+, FastAPI, MongoDB 7, Elasticsearch 8.15.4 (BM25), MCP server for AI agents.

## Build & Run Commands

```bash
# Full stack (dev)
docker compose up --build

# Storage only
docker compose up -d mongo elasticsearch

# Production (on Hetzner)
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml --profile container-nginx up -d  # with nginx
docker compose -f docker-compose.prod.yml --profile reranker up -d          # with reranker

# Tail logs
docker compose logs -f backend

# Backend shell
docker compose exec backend sh
```

### Ingestion & Indexing

```bash
# Historical backfill
docker compose exec backend python -m src.backend.ingest.sync_dou --year 2024

# Daily INLABS ingest
docker compose exec backend python -m src.backend.ingest.inlabs_daily

# MongoDB → ES sync (incremental)
docker compose exec backend python -m src.backend.ingest.es_indexer sync

# Full reindex
docker compose exec backend python -m src.backend.ingest.es_indexer backfill
```

### Lint & Format

```bash
# Python (ruff — run in container or local venv)
ruff check .                  # Lint
ruff check . --fix            # Lint with auto-fix
ruff format .                 # Format

# Frontend (inside src/frontend/app/)
npm run lint                  # ESLint
npm run build                 # TypeScript check + Vite build
```

### Tests

```bash
# Python — pytest (unit tests)
pytest tests/                              # All unit tests
pytest tests/unit/test_classifier.py       # Single file
pytest tests/unit/test_classifier.py::TestQueryClassification  # Single class
pytest tests/unit/test_classifier.py::TestQueryClassification::test_immutability  # Single test

# Python — operational smoke tests (standalone scripts)
python ops/test_mcp_tools.py               # MCP tool smoke suite
python ops/test_mongo_connection.py        # MongoDB connection
python ops/test_answering.py               # RAG answer pipeline
python ops/test_api_adversarial.py         # Adversarial API tests
python ops/test_dev_converge_tools.py      # Dev-converge MCP tools
python ops/eval_mcp_quality.py             # MCP quality benchmark
python ops/eval_mcp_quality.py --case lgpd # Single benchmark case

# Frontend (inside src/frontend/app/)
npm run test                               # All tests (vitest run)
npm run test:watch                         # Watch mode
npx vitest run src/test/example.test.ts    # Single test file
```

## Python Code Style

### Tooling
- **Ruff** for linting and formatting (line length: **120**)
- **Type hints** required on all functions
- **No comments** unless explaining non-obvious logic

### Import Order
```python
from __future__ import annotations          # 1. Future
import argparse                             # 2. Stdlib (alphabetical)
import json
from datetime import datetime
from pathlib import Path
from typing import Any
import httpx                                # 3. Third-party (alphabetical)
from pydantic import BaseModel, Field
from pymongo import MongoClient
from src.backend.core.config import settings  # 4. Local (absolute path from src/)
```

### Naming Conventions
| Type | Convention | Example |
|------|-----------|---------|
| Files | snake_case | `dou_chunker.py`, `es_indexer.py` |
| Classes | PascalCase | `DouDocument`, `ESClient`, `QueryIntent` |
| Functions | snake_case | `parse_date()`, `hybrid_search()` |
| Constants | UPPER_SNAKE | `BASE_URL`, `_MAPPING_PATH`, `MIN_PHRASE_RESULTS` |
| Private | leading underscore | `_log()`, `_env_bool()`, `_normalize_for_matching()` |
| Variables | snake_case | `pub_date`, `zip_filename`, `batch_size` |

### Type Annotations
```python
from typing import Any

def _mongo_to_es(doc: dict[str, Any]) -> dict[str, Any]: ...

# Prefer modern union syntax:
def get_document(doc_id: str) -> dict[str, Any] | None: ...

# Dataclasses for structured results:
@dataclass
class IntentResult:
    intent: QueryIntent
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)
```

### Error Handling
```python
# Non-critical: log and continue
try:
    _run_sync()
except Exception as e:
    logger.warning(f"ES sync failed (non-fatal): {e}")

# Critical: log and re-raise
try:
    result = collection.bulk_write(operations)
except Exception as e:
    logger.error(f"Bulk write failed: {e}")
    raise

# Defensive fallbacks on search errors
try:
    results = es.search(index=alias, body=query)
except Exception as e:
    logger.warning(f"Search failed: {e}")
    return []
```

### Pydantic Models & Config
```python
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings

class DouDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    id: str = Field(alias="_id")
    pub_date: datetime

class Settings(BaseSettings):
    MONGO_STRING: str = "mongodb://mongo:27017/gabi_dou"
    class Config:
        env_file = ".env"
        extra = "ignore"
```

### Enums & Dataclasses
```python
from dataclasses import dataclass, field
from enum import Enum

class QueryIntent(Enum):
    EXACT_NAME = "exact_name"
    CANONICAL_LOOKUP = "canonical_lookup"
    PERSON_NAME = "person_name"
    TRENDING = "trending"
    THEMATIC = "thematic"
```

## TypeScript/React Code Style
- **ESLint 9** flat config with typescript-eslint
- **Tailwind CSS** + **shadcn/ui** component patterns
- Use `@/` alias for imports from `src/`
- Functional components with hooks only
- Run modules: `npm run build` / `npm run lint` inside `src/frontend/app/`

## Architecture
```
in.gov.br (INLABS/Liferay) → sync_dou.py → MongoDB → es_indexer.py → Elasticsearch
                                                                              ↑
FastAPI (src/backend/main.py) ← React Frontend (src/frontend/app/)
MCP Server (ops/bin/mcp_es_server.py) ← AI Agents
Dev Converge (src/dev_converge/) ← Multi-agent consensus
```

## Key Files
| File | Purpose |
|------|---------|
| `src/backend/main.py` | FastAPI app — API endpoints, SSR, MCP mount |
| `ops/bin/mcp_es_server.py` | MCP server (20 tools) |
| `src/backend/ingest/sync_dou.py` | Historical DOU ingestion |
| `src/backend/ingest/inlabs_daily.py` | Daily INLABS ingestion |
| `src/backend/ingest/es_indexer.py` | MongoDB → ES sync |
| `src/backend/search/hybrid.py` | BM25 + kNN hybrid search |
| `src/backend/search/intent.py` | Query intent classifier |
| `src/backend/search/classifier.py` | Query classification |
| `src/backend/answering/service.py` | RAG answer pipeline |
| `src/backend/core/config.py` | Pydantic Settings |
| `docker-compose.yml` | Dev services |
| `docker-compose.prod.yml` | Production (Hetzner) |

## Production (Hetzner)

### Services & Ports
| Port | Service | URL |
|------|---------|-----|
| 80 | Nginx (reverse proxy) | gabidou.top |
| 8001 | FastAPI backend | Internal |
| 8011 | Dev Converge API | converge.gabidou.top |
| 8081 | Frontend (serve) | Internal |
| 9200 | Elasticsearch | Internal |
| 27017 | MongoDB | Internal |
| 8902 | Reranker (profile) | Internal |

### Data Volumes
```
/mnt/HC_Volume_105154890/mongo_data     → MongoDB
/mnt/HC_Volume_105154890/elastic_data   → Elasticsearch
/mnt/HC_Volume_105154890/dou_data       → DOU raw data
/mnt/HC_Volume_105154890/dev_converge   → Dev Converge jobs
```

### Networks
- `edge` — services reachable by nginx (backend, frontend, dev-converge)
- `internal` — all services; mongo/es only on internal (not exposed)

## Key Gotchas
- **INLABS WAF blocks Hetzner IP** — solved via `INLABS_PROXY` (residential proxy); Mac relay as fallback
- **Vector search + reranker disabled by default** — BM25-only in production
- **Worker service** runs continuous ES sync loop (30s polling); separate from backend
- **MCP server** at `ops/bin/mcp_es_server.py` is separate from FastAPI app (mounted at `/mcp/` SSE, `/mcp-http/` Streamable HTTP)
- **SSR + SPA hybrid** — FastAPI serves SSR HTML for SEO at `/documento/` paths
- **Run Python modules** with `-m` flag: `python -m src.backend.ingest.sync_dou`
- **ES index is v3**: `gabi_documents_v3` with alias `gabi_documents`

## Environment
```bash
MONGO_STRING=mongodb://mongo:27017/gabi_dou
ES_URL=http://elasticsearch:9200
ES_INDEX=gabi_documents_v3
ES_ALIAS=gabi_documents
VECTOR_SEARCH_ENABLED=false
RERANKER_ENABLED=false
```
