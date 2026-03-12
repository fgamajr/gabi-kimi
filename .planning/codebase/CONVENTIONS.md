# Coding Conventions

**Analysis Date:** 2026-03-11

## Naming Patterns

**Files:**
- snake_case with `.py` extension
- Examples: `dou_processor.py`, `es_indexer.py`, `mcp_es_server.py`
- Test files: `test_<feature>.py` (e.g., `test_mongo_connection.py`, `test_extraction.py`)

**Classes:**
- PascalCase
- Examples: `DouProcessor`, `ESClient`, `DouDocument`, `MongoDB`, `ElasticClient`
- Models inherit from `BaseModel`: `class DouDocument(BaseModel)`

**Functions:**
- snake_case
- Examples: `parse_date()`, `generate_id()`, `process_zip()`, `_run_sync()`

**Variables:**
- snake_case
- Examples: `pub_date`, `art_type`, `zip_filename`, `doc_id`

**Constants:**
- UPPER_SNAKE at module level
- Examples: `BASE_URL`, `GROUP_ID`, `_MAPPING_PATH`, `_DEFAULT_CURSOR_PATH`

**Private functions:**
- Leading underscore prefix
- Examples: `_log()`, `_env_bool()`, `_load_cursor()`, `_mongo_to_es()`

**Model fields:**
- snake_case
- Examples: `pub_date`, `art_type`, `issuing_organ`, `act_number`

**Types:**
- PascalCase for type aliases and model classes
- Examples: `StructuredData`, `Reference`, `Enrichment`

## Code Style

**Formatting:**
- Ruff (pyflakes + pycodestyle errors)
- Line length: 120 characters
- No formal config file (settings documented in `AGENTS.md`)
- Ignored rules: E402 (imports after code), E501 (line length - handled by formatter)

**Linting:**
```bash
ruff check .                      # Lint
ruff check . --fix                # Auto-fix linting issues
ruff format .                     # Format code
```

**Python Version:**
- Python 3.12+
- Modern type hint syntax: `dict[str, Any]`, `list[dict]`, `tuple[str, str | None]`

## Import Organization

**Order (top to bottom):**
1. `from __future__ import annotations` (if needed)
2. Standard library (alphabetical)
3. Third-party (alphabetical)
4. Local imports (absolute paths from `src/`)

**Example from `es_indexer.py`:**
```python
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any

import httpx
import pymongo
from bson import ObjectId

_MAPPING_PATH = Path(__file__).resolve().parent.parent / "search" / "es_index_v1.json"
```

**Example from `dou_processor.py`:**
```python
import logging
import zipfile
import io
import re
import hashlib
import html
import os
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any
from lxml import etree
import requests

from src.backend.data.models.document import (
    DouDocument, Metadata, Usage, StructuredData, Reference, Image, Enrichment
)
```

**Path Aliases:**
- None configured - use absolute imports from `src/`
- Example: `from src.backend.core.config import settings`

## Error Handling

**Patterns:**

1. **Try/except with logging** - for critical operations:
```python
try:
    result = collection.bulk_write(operations)
    logger.info(f"Upserted {result.upserted_count} documents")
except Exception as e:
    logger.error(f"Bulk write failed: {e}")
```

2. **Graceful degradation** - non-critical failures:
```python
try:
    _run_sync()
except Exception as e:
    logger.warning(f"ES sync failed (non-fatal): {e}")
```

3. **None-safe returns with logging** - parsing/validation:
```python
def parse_date(self, date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str.strip(), "%d/%m/%Y")
    except ValueError:
        logger.warning(f"Failed to parse date: {date_str}")
        return None
```

4. **HTTP raise_for_status** - for API calls:
```python
resp = self.client.request(method=method, url=f"{self.url}{path}", json=payload)
resp.raise_for_status()
```

5. **Silent exception handling** - for optional features:
```python
try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:
    FastMCP = None  # type: ignore[assignment]
```

## Logging

**Framework:** Python standard library `logging`

**Setup:**
```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
```

**Patterns:**
```python
logger.info(f"Processing {count} documents")
logger.warning(f"No folder ID found for {month_key}")
logger.error(f"Failed to download {url}: {e}")
```

**Simple print for CLI tools:**
```python
def _log(msg: str) -> None:
    print(f"[es-indexer] {msg}", flush=True)
```

## Comments

**When to Comment:**
- Module-level docstrings with usage examples
- Complex regex patterns with explanations
- Workarounds and fixes with reference numbers

**Module Docstrings:**
```python
"""Elasticsearch indexer for DOU documents (backfill, incremental sync, stats).

Reads from MongoDB, indexes into Elasticsearch with BM25.

Usage:
  python3 -m src.backend.ingest.es_indexer backfill
  python3 -m src.backend.ingest.es_indexer sync
  python3 -m src.backend.ingest.es_indexer stats
"""
```

**Inline Comments:**
```python
# Cleanup Logic:
# 1. We keep the raw ZIPs in iCloud (Source of Truth)
# 2. We DELETE the extracted XMLs from iCloud/Linux to save space/inodes
```

**JSDoc/TSDoc:**
- Not used - Python docstrings preferred

## Function Design

**Size:**
- Typical functions: 10-30 lines
- Large functions up to 80+ lines exist (e.g., `process_xml`)
- Complex functions extracted into helpers

**Parameters:**
- Use keyword arguments for optional parameters
- Default values for common cases
- Type hints on all parameters

**Return Values:**
- Type hints required
- `Optional[T]` for nullable returns
- Empty collections for no results (not None)

**Example:**
```python
def _fetch_batch(collection, cursor_id: str, batch_size: int) -> list[dict[str, Any]]:
    """Fetch a batch of documents from MongoDB using cursor pagination."""
    query = {"_id": {"$gt": cursor_id}}
    cursor = collection.find(query).sort("_id", 1).limit(batch_size)
    return list(cursor)
```

## Module Design

**Exports:**
- Single primary class/function per module when possible
- Helper functions prefixed with `_`
- Public API through explicit imports

**Barrel Files:**
- Not used - prefer direct imports

**Module Structure:**
```python
# 1. Module docstring
# 2. Future annotations
# 3. Imports
# 4. Module constants
# 5. Helper functions (private)
# 6. Public classes
# 7. CLI entry point (if __name__ == "__main__")
```

## Configuration Pattern

**Pydantic Settings:**
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

**Environment Variables:**
- Required: `MONGO_STRING`, `DB_NAME`, `ES_URL`, `ES_INDEX`
- Optional with defaults: `DOU_DATA_PATH`, `ICLOUD_DATA_PATH`, `PIPELINE_TMP`

## Pydantic Models

**Structure:**
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
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
```

**Patterns:**
- `Optional[T] = None` for nullable fields
- `Field(default_factory=list)` for mutable defaults
- `Field(alias="_id")` for MongoDB field mapping
- `Literal["opt1", "opt2"]` for enum-like fields

## CLI Pattern

**argparse with subcommands:**
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

## MCP Tool Pattern

**FastMCP decorated functions:**
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

---

*Convention analysis: 2026-03-11*
