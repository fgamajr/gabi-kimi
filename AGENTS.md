# Repository Guidelines

## Project Overview

GABI (Gerador Automatico de Boletins por Inteligencia Artificial) - a Python 3 bulk XML ingestion pipeline for Brazilian legal publications (DOU - Diario Oficial da Uniao). The project downloads monthly ZIP bundles from in.gov.br, parses structured XML, persists to PostgreSQL, and produces CRSS-1 cryptographic audit trails.

## Project Structure

- **`ingest/`** - Bulk XML ingestion pipeline
  - `bulk_pipeline.py` - Main orchestrator CLI: download → parse → ingest → seal (also `--sync`)
  - `sync_pipeline.py` - Incremental sync: catalog discovery → delta → download → ingest
  - `dou_ingest.py` - DOU schema ingestor: ZIP → parse → NLP enrich → insert dou.* tables
  - `html_extractor.py` - NLP extraction: signatures, images, norm refs, proc refs, doc numbers
  - `multipart_merger.py` - Group and merge multi-part XML articles (e.g. _1, _2)
  - `xml_parser.py` - Parse INLabs DOU XML into `DOUArticle` dataclasses (with XML sanitizer)
  - `zip_downloader.py` - URL generation, HTTP download, tags API, ZIP extraction
  - `normalizer.py` - DOUArticle → PG schema + registry ingest record bridge
  - `date_selector.py` - Date range generation
  - `identity_analyzer.py` - Identity hashing and deduplication
  - `catalog_scraper.py` - Scrape catalog page for per-month folderId registry
  - `discovery_probe.py` - URL pattern probing and tags API discovery
- **`commitment/`** - CRSS-1 commitment scheme (Merkle trees, canonical serialization)
  - `anchor.py`, `chain.py`, `crss1.py`, `tree.py`, `verify.py`
- **`dbsync/`** - Declarative PostgreSQL schema management
  - `dou_schema.sql` - DOU publication schema: 7 tables + view + GIN FTS index
  - `schema_sync.py`, `registry_ingest.py`, `differ.py`, `planner.py`, etc.
- **`infra/`** - Docker-based PostgreSQL appliance
- **`tests/`** - Test suite
  - `test_commitment.py` - CRSS-1 pure function tests
  - `test_seal_roundtrip.py` - End-to-end seal integration test
  - `test_bulk_pipeline.py` - Bulk pipeline unit tests (135 assertions)
  - `test_dou_ingest.py` - DOU ingest pipeline tests (211 assertions)
  - `fixtures/xml_samples/` - Real DOU XML samples for testing
- **`data/`** - Data files and registries
  - `dou_catalog_registry.json` - Month→folderId mapping (289 months, Jan 2002 → Jan 2026)
  - `inlabs/` - Downloaded ZIP bundles + manifest
  - `discovery/` - Discovery probe results and validation ZIPs
- **`proofs/`** - CRSS-1 anchor chain and golden test vectors
- **`governance/`** - Repository classification, dead code reports, refactor plans
- **`archive_legacy/`** - Archived modules from pre-consolidation (crawler, HTML scraping, etc.)

## Build, Test, and Development Commands

### Running Tests
```bash
# Run commitment scheme tests (pure functions, no DB)
python3 tests/test_commitment.py

# Run bulk pipeline tests (parsing, normalization, extraction)
python3 tests/test_bulk_pipeline.py

# Parse XML fixtures
python3 -c "from ingest.xml_parser import parse_directory; arts = parse_directory('tests/fixtures/xml_samples'); print(f'{len(arts)} articles parsed')"

# Compile-check all modules
python3 -m py_compile ingest/xml_parser.py ingest/zip_downloader.py ingest/normalizer.py ingest/bulk_pipeline.py
```

### Bulk Ingestion Pipeline
```bash
# Download + parse last 7 days (no DB)
python3 -m ingest.bulk_pipeline --days 7 --parse-only

# Download only
python3 -m ingest.bulk_pipeline --days 7 --download-only

# Full pipeline (download + parse + ingest)
python3 -m ingest.bulk_pipeline --start 2026-02-20 --end 2026-02-27

# Full pipeline with CRSS-1 sealing
python3 -m ingest.bulk_pipeline --start 2026-02-20 --end 2026-02-27 --seal

# Ingest from already-downloaded ZIPs
python3 -m ingest.bulk_pipeline --start 2026-02-20 --end 2026-02-27 --skip-download
```

### Incremental Sync Pipeline
```bash
# Auto-sync: discover new ZIPs from catalog → download → ingest
python3 -m ingest.sync_pipeline

# Via bulk_pipeline CLI
python3 -m ingest.bulk_pipeline --sync

# Dry-run: show what would be downloaded
python3 -m ingest.sync_pipeline --dry-run

# Refresh catalog from in.gov.br first, then sync
python3 -m ingest.sync_pipeline --refresh-catalog

# Sync specific month range
python3 -m ingest.sync_pipeline --start 2025-01 --end 2026-01

# Limit ZIPs per run (for testing or rate limiting)
python3 -m ingest.sync_pipeline --limit 20
```

### DOU Schema Ingest (standalone)
```bash
# Ingest all ZIPs in a directory into dou.* schema
python3 -m ingest.dou_ingest --data-dir data/sample200/zips

# Ingest with custom DSN and limit
python3 -m ingest.dou_ingest --data-dir data/inlabs --dsn "host=... port=5433 ..." --limit 10
```

### Catalog Registry
```bash
# Scrape full catalog (289 months, Jan 2002 → Jan 2026)
python3 -m ingest.catalog_scraper --start-year 2002 --end-year 2026

# Scrape a specific year range
python3 -m ingest.catalog_scraper --start-year 2020 --end-year 2026 --delay 0.4

# Registry is saved to data/dou_catalog_registry.json
```

### Infrastructure
```bash
python3 infra/infra_manager.py up        # Start PostgreSQL (port 5433)
python3 infra/infra_manager.py status    # Check container/DB health
python3 infra/infra_manager.py down      # Stop
python3 infra/infra_manager.py reset_db  # Wipe DB (destructive)
```

### Database Schema Sync
```bash
python3 schema_sync.py plan --sources sources_v3.yaml
python3 schema_sync.py apply --sources sources_v3.yaml
python3 schema_sync.py verify --sources sources_v3.yaml
```

## Code Style Guidelines

### Imports
```python
from __future__ import annotations  # Always first

from collections import deque           # Stdlib
from dataclasses import dataclass
from typing import Any, Protocol

import yaml                             # Third-party

from ingest.xml_parser import DOUArticle  # Local imports
```
- Group imports: stdlib, third-party, local (blank line between groups)
- Use `from __future__ import annotations` at the top of every module
- Prefer explicit imports over `import *`

### Formatting
- 4-space indentation (no tabs)
- Max line length: ~100 characters (flexible)
- Blank lines between class methods, between top-level functions
- No trailing whitespace

### Type Hints
```python
def load(self, url: str) -> Page:
def extract(self, selector: str, attribute: str = "href") -> list[str]:
def _safe_load(self, runtime: RuntimeAdapter, url: str, run_id: str) -> Page | None:
```
- Use type hints for all function signatures
- Use `| None` for optional returns (Python 3.10+ style)
- Use `list[str]`, `dict[str, Any]` instead of `List`, `Dict`

### Naming Conventions
- `snake_case` for modules, functions, variables, CLI flags (`--max-articles`)
- `PascalCase` for classes and exceptions
- `UPPER_SNAKE_CASE` for constants and module-level globals
- Prefix private methods with underscore: `_safe_load`, `_normalize_url`
- Protocol classes: `RuntimeAdapter`, not `IRuntimeAdapter`

### Data Classes
```python
@dataclass(slots=True)
class Page:
    url: str
    status_code: int
    html: str
    loaded_at_ms: int
```
- Use `@dataclass(slots=True)` for data containers
- Use `field(default_factory=list)` for mutable defaults

### Error Handling
```python
def _safe_load(self, runtime: RuntimeAdapter, url: str, run_id: str) -> Page | None:
    try:
        return runtime.load(url)
    except Exception as ex:
        self._log.error(run=run_id, stage="request", error_type=type(ex).__name__, error_message=str(ex))
        return None
```
- Log errors with structured context via loguru
- Use specific exception types when raising
- Custom exceptions inherit from appropriate built-in: `class ApplyError(RuntimeError): pass`

### Documentation
- Module-level docstrings: `"""Module description."""`
- Class-level docstrings for public classes
- Inline comments sparingly; prefer self-documenting code
- CLI help via argparse: `p.add_argument("--dates", help="Number of dates to sample")`

## Testing Guidelines

- No pytest suite - testing is script/harness-driven
- Tests should be runnable as standalone scripts: `python3 tests/test_commitment.py`
- For ingestion changes, verify XML parsing with fixture samples in `tests/fixtures/xml_samples/`
- Include reproduction commands and expected output in PR descriptions

## Commit and Pull Request Guidelines

- Short, imperative commit subjects: `Fix pipeline runtime bugs`, `Add CRSS-1 commitment scheme`
- PRs must include: purpose, affected paths, commands run, before/after behavior
- Link related issues; attach logs/screenshots for workflow changes
- Run relevant test scripts before committing

## Security and Configuration

- Keep secrets in `.env` (copy from `.env.example`); never commit credentials
- Validate destructive DB operations (`reset_db`, `recreate`) before running
- Database runs on port 5433 (non-standard to avoid conflicts)
