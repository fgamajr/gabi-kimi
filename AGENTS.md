# AGENTS.md - Guidelines for AI Coding Agents

## Project Overview

GABI (Gestão Automatizada de Busca Inteligente) is a full-text search platform for Brazil's official gazette (Diário Oficial da União - DOU). It processes ~16M legal documents from 2002-2026 with MongoDB storage and Elasticsearch BM25 search.

## Build/Lint/Test Commands

### Primary Operations

```bash
# Data Ingestion
python3 sync_dou.py --year 2024              # Single year
python3 sync_dou.py --year 2024 --month 6    # Single month

# Elasticsearch Indexing
python3 -m src.backend.ingest.es_indexer backfill    # Full reindex
python3 -m src.backend.ingest.es_indexer sync        # Incremental sync
python3 -m src.backend.ingest.es_indexer stats       # Show counts/parity
python3 -m src.backend.ingest.es_indexer backfill --recreate-index  # Reset index

# MCP Server
python ops/bin/mcp_es_server.py                          # stdio transport
python ops/bin/mcp_es_server.py --transport sse --port 8766  # SSE transport
```

### Linting & Formatting

```bash
ruff check .                      # Lint
ruff check . --fix                # Auto-fix linting issues
ruff format .                     # Format code
```

### Testing

No formal test suite in main codebase. Ad-hoc tests in `ops/test_*.py`:
```bash
python ops/test_mongo_connection.py    # Test MongoDB connection
python ops/test_extraction.py          # Test ZIP extraction
```

### Docker Services

```bash
# MongoDB
docker run -d --name gabi-mongo -p 27017:27017 -v /media/psf/gabi_mongo:/data/db mongo:7

# Elasticsearch
docker run -d --name gabi-es -p 9200:9200 \
  -e discovery.type=single-node \
  -e xpack.security.enabled=false \
  -e "ES_JAVA_OPTS=-Xms512m -Xmx512m" \
  -v /media/psf/gabi_es:/usr/share/elasticsearch/data \
  docker.elastic.co/elasticsearch/elasticsearch:8.15.4
```

## Code Style Guidelines

### Python Version & Tooling

- **Python 3.12+**
- **Line length**: 120 characters
- **Linter/Formatter**: Ruff (pyflakes + pycodestyle errors)
- **Ignored rules**: E402 (imports after code), E501 (line length - handled by formatter)

### Import Order

```python
# 1. Future annotations (if needed)
from __future__ import annotations

# 2. Standard library (alphabetical)
import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, List

# 3. Third-party (alphabetical)
from bson import ObjectId
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
from typing import Any, Optional, List

def _mongo_to_es(doc: dict[str, Any]) -> dict[str, Any]:
    ...

def _infer_filters(query: str) -> tuple[str, str | None, str | None]:
    ...

class DouDocument(BaseModel):
    pub_date: datetime
    art_type: Optional[str] = None
    references: List[Reference] = Field(default_factory=list)
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
    MONGO_STRING: str
    DB_NAME: str = "gabi_dou"
    ES_URL: str = "http://localhost:9200"
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
```

### Pydantic Models

```python
from pydantic import BaseModel, Field
from typing import Optional, List, Literal

class StructuredData(BaseModel):
    act_number: Optional[str] = None
    act_year: Optional[int] = None
    signer: Optional[str] = None

class DouDocument(BaseModel):
    id: str = Field(alias="_id")  # MongoDB _id mapping
    source_id: str
    pub_date: datetime
    texto: str
    references: List[Reference] = Field(default_factory=list)
    
    class Config:
        populate_by_name = True
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

### Module Docstrings

Include usage examples in module docstrings:
```python
"""Elasticsearch indexer for DOU documents.

Usage:
  python3 -m src.backend.ingest.es_indexer backfill
  python3 -m src.backend.ingest.es_indexer sync
  python3 -m src.backend.ingest.es_indexer stats
"""
```

## Project Structure

```
src/backend/
  core/config.py        # Settings (Mongo, ES, paths)
  data/
    db.py               # DB connection
    models/document.py  # Pydantic models
  ingest/
    downloader.py       # Downloads ZIPs from in.gov.br
    dou_processor.py    # Parses XML -> DouDocument
    es_indexer.py       # MongoDB -> Elasticsearch indexer
  search/
    es_index_v1.json    # ES mapping definition

ops/
  bin/mcp_es_server.py  # MCP server for Claude Code
  data/dou_catalog_registry.json  # Maps YYYY-MM to folder IDs

sync_dou.py             # Main ingestion orchestrator
```

## Environment Variables

Required in `.env`:
- `MONGO_STRING` - MongoDB connection URI
- `DB_NAME` - Database name (default: gabi_dou)
- `ES_URL` - Elasticsearch URL (default: http://localhost:9200)
- `ES_INDEX` - ES index name (default: gabi_documents_v1)
- `DOU_DATA_PATH` - Local data storage path
- `ICLOUD_DATA_PATH` - iCloud archive path (optional)
