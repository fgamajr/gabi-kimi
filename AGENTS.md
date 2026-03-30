# AGENTS.md - GABI Codebase Guidelines

## Project
**GABI** — Full-text search platform for Brazil's Diário Oficial da União (~16M documents, 2002-2026). Python 3.12+, FastAPI, MongoDB 7, Elasticsearch 8.15.4 (BM25), MCP server for AI agents.

## Build & Run Commands

```bash
# Full stack
docker compose up --build

# Backend shell
docker compose exec backend sh

# MCP server (stdio for Claude Code, SSE for HTTP)
python ops/bin/mcp_es_server.py --transport stdio
python ops/bin/mcp_es_server.py --transport sse --port 8766

# Lint & format (run in container or with venv)
ruff check .
ruff check . --fix
ruff format .

# Run a single test
python ops/test_mcp_tools.py  # Full MCP test suite
python ops/test_mongo_connection.py  # Single test file
```

## Python Code Style

### Tooling
- **Ruff** for linting and formatting (line length: 120)
- **Type hints** required on all functions
- **No comments** unless explaining non-obvious logic

### Import Order
```python
from __future__ import annotations          # 1. Future
import argparse                           # 2. Stdlib (alpha)
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import httpx                              # 3. Third-party (alpha)
from pydantic import BaseModel, Field
from pymongo import MongoClient
from src.backend.core.config import settings  # 4. Local (absolute path)
```

### Naming Conventions
| Type | Convention | Example |
|------|-----------|---------|
| Files | snake_case | `dou_chunker.py` |
| Classes | PascalCase | `DouDocument`, `ESClient` |
| Functions | snake_case | `parse_date()` |
| Constants | UPPER_SNAKE | `BASE_URL`, `_MAPPING_PATH` |
| Private | leading underscore | `_log()`, `_env_bool()` |
| Variables | snake_case | `pub_date`, `zip_filename` |

### Type Annotations
```python
from typing import Any, Optional

def _mongo_to_es(doc: dict[str, Any]) -> dict[str, Any]: ...

class DouDocument(BaseModel):
    pub_date: datetime
    art_type: Optional[str] = None
```

### Error Handling
```python
# Log and continue (non-critical)
try:
    _run_sync()
except Exception as e:
    logger.warning(f"ES sync failed (non-fatal): {e}")

# Fail fast with context
try:
    result = collection.bulk_write(operations)
except Exception as e:
    logger.error(f"Bulk write failed: {e}")
    raise
```

### Pydantic Models
```python
class DouDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    id: str = Field(alias="_id")
    pub_date: datetime
```

### Configuration
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    MONGO_STRING: str = "mongodb://mongo:27017/gabi_dou"
    class Config:
        env_file = ".env"
        extra = "ignore"
```

## Architecture
```
in.gov.br → sync_dou.py → MongoDB → es_indexer.py → Elasticsearch
                                                        ↑
MCP Server (ops/bin/mcp_es_server.py) ← AI Agents
```

## Key Files
| File | Purpose |
|------|---------|
| `ops/bin/mcp_es_server.py` | MCP server (17 tools) |
| `src/backend/ingest/sync_dou.py` | DOU ingestion orchestrator |
| `src/backend/ingest/es_indexer.py` | MongoDB → ES indexer |
| `src/backend/search/hybrid.py` | BM25 + kNN hybrid search |
| `src/backend/search/reranker.py` | Neural reranker client |
| `src/backend/core/config.py` | Settings (Pydantic) |
| `docker-compose.yml` | Service definitions |

## MCP Tools (17 total)
`es_search`, `es_suggest`, `es_facets`, `es_document`, `es_health`, `es_more_like_this`, `es_significant_terms`, `es_timeline`, `es_trending`, `es_cross_reference`, `es_organ_profile`, `es_compare_periods`, `es_explain`, `es_btcu_search`, `es_publicacoes_search`, `es_tcu_semantic_search`, `es_tcu_similar`

## Environment
```bash
MONGO_STRING=mongodb://mongo:27017/gabi_dou
ES_URL=http://elasticsearch:9200
ES_INDEX=gabi_documents_v1
VECTOR_SEARCH_ENABLED=false
RERANKER_ENABLED=false
EMBED_SERVER_URL=http://host.docker.internal:8900
RERANKER_URL=http://host.docker.internal:8902
```

## Ports
| Port | Service |
|------|---------|
| 27017 | MongoDB |
| 9200 | Elasticsearch |
| 8001 | FastAPI |
| 8081 | Frontend |

## Docker-Only
No host Python/node required. All commands run inside containers via `docker compose exec`.
