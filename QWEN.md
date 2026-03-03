# GABI Project Context

## Project Overview

**GABI** (Gerador Automatico de Boletins por Inteligencia Artificial) is a Python 3 bulk XML ingestion pipeline for Brazilian legal publications, primarily the **DOU** (Diário Oficial da União). The project downloads daily ZIP bundles from in.gov.br, parses structured XML, persists to PostgreSQL, and produces **CRSS-1** cryptographic audit trails.

### Core Components

| Directory | Purpose |
|-----------|---------|
| `ingest/` | Bulk XML ingestion pipeline (ZIP download, XML parsing, normalization, identity analysis) |
| `commitment/` | CRSS-1 commitment scheme (Merkle trees, canonical serialization, inclusion proofs) |
| `dbsync/` | Declarative PostgreSQL schema management with diff/plan/apply workflow |
| `infra/` | Docker-based PostgreSQL appliance management |
| `tests/` | Test suite with XML fixtures |
| `proofs/` | CRSS-1 anchor chain and golden test vectors |
| `docs/` | XML schema reference, DB handbook |

### Architecture

The system follows a **bulk ingestion pipeline**:

```
in.gov.br ZIP bundles → XML parsing (DOUArticle) → Normalization → Commitment (CRSS-1) → PostgreSQL (immutable registry)
```

- **Bulk XML ingestion**: Daily ZIP bundles from in.gov.br Liferay document library, parsed via `xml.etree.ElementTree`
- **CRSS-1**: Canonical serialization (NFC-normalized, pipe-delimited) → SHA256 leaf hashes → Merkle tree
- **Temporal registry**: Append-only PostgreSQL schema with `editions`, `concepts`, `versions`, `occurrences`, and `ingestion_log` tables

## Building and Running

### Prerequisites

- Python 3.10+
- Docker (for PostgreSQL appliance)
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Setup

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### Dependencies

```txt
loguru>=0.7          # Structured logging
psycopg[binary]>=3.1 # PostgreSQL driver
pyyaml>=6.0          # YAML parsing
requests>=2.31       # HTTP downloads
```

### Infrastructure Management

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

### Running Tests

```bash
# CRSS-1 commitment scheme tests (62 tests, pure functions, no DB)
python3 tests/test_commitment.py

# Parse XML fixtures (13 samples)
python3 -c "from ingest.xml_parser import parse_directory; arts = parse_directory('tests/fixtures/xml_samples'); print(f'{len(arts)} articles parsed')"

# Compile-check all ingest modules
python3 -m py_compile ingest/xml_parser.py ingest/zip_downloader.py ingest/normalizer.py ingest/date_selector.py ingest/identity_analyzer.py
```

## Development Conventions

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
- Blank lines between class methods and top-level functions
- No trailing whitespace

### Type Hints

```python
def load(self, url: str) -> Page:
def extract(self, selector: str, attribute: str = "href") -> list[str]:
def _safe_load(self, url: str, run_id: str) -> Page | None:
```

- Use type hints for all function signatures
- Use `| None` for optional returns (Python 3.10+ style)
- Use `list[str]`, `dict[str, Any]` instead of `List`, `Dict`

### Naming Conventions

- `snake_case` for modules, functions, variables, CLI flags (`--max-articles`)
- `PascalCase` for classes and exceptions
- `UPPER_SNAKE_CASE` for constants
- Private methods prefixed with underscore: `_safe_load`, `_normalize_url`

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

- Log errors with structured context via loguru
- Use specific exception types when raising
- Custom exceptions: `class ApplyError(RuntimeError): pass`

### Documentation

- Module-level docstrings: `"""Module description."""`
- Class-level docstrings for public classes
- Inline comments sparingly; prefer self-documenting code

## Testing Practices

- No pytest suite — testing is script/harness-driven
- Tests runnable as standalone scripts: `python3 tests/test_commitment.py`
- For ingestion changes: verify XML parsing with fixtures in `tests/fixtures/xml_samples/`
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

## Key Files

| File | Purpose |
|------|---------|
| `sources_v3.yaml` | Master YAML spec defining data model, entities, and constraints |
| `requirements.txt` | Python dependencies |
| `.env.example` | Template for environment configuration |
| `AGENTS.md` | Repository guidelines and development workflow |
| `commitment/crss1.py` | CRSS-1 canonical serializer specification |
| `dbsync/registry_schema.sql` | PostgreSQL immutable registry schema |
| `ingest/xml_parser.py` | INLabs DOU XML parser (DOUArticle dataclass) |
| `ingest/zip_downloader.py` | URL generation for daily ZIP bundles from in.gov.br |
