# Repository Guidelines

## Project Overview

GABI (Gerador Automatico de Boletins por Inteligencia Artificial) - a Python 3 web crawler and data extraction pipeline for Brazilian legal publications (primarily DOU - Diario Oficial da Uniao). The project includes a CRSS-1 commitment scheme for cryptographic audit trails.

## Project Structure

- **`crawler/`** - YAML-driven web crawler engine
  - `engine.py` - Generic HTTP crawler with `RuntimeAdapter` protocol
  - `dsl_schema.py`, `dsl_loader.py`, `dsl_validator.py` - DSL dataclasses and validation
  - `frontier.py` - URL dedup + FIFO queue
  - `memory_budget.py`, `memory_levels.py` - Memory governor
  - `observability.py` - Logfmt structured logging via loguru
- **`validation/`** - HTML extraction and validation
  - `extractor.py` - `ExtractionHarness` for field extraction via CSS selectors
  - `rules.py` - YAML extraction rules loader
  - `corpus_sampler.py`, `reporter.py` - Sampling and report generation
- **`dbsync/`** - Declarative PostgreSQL schema management
- **`commitment/`** - CRSS-1 commitment scheme (Merkle trees, canonical serialization)
- **`infra/`** - Docker-based PostgreSQL appliance
- **`examples/`** - YAML fixtures and configs

## Build, Test, and Development Commands

### Running Tests
```bash
# Run commitment scheme tests (pure functions, no DB)
python3 test_commitment.py

# Run mock crawl
python3 run_mock_crawl.py --config examples/mock_crawl.yaml

# Extraction harness without DB
python3 extract_test.py --rules examples/sources_v3_model.yaml --html <input_dir> --out <report_dir>

# Full historical validation
python3 historical_validate.py full --rules examples/sources_v3_model.yaml

# Single validation subcommand
python3 historical_validate.py sample --dates 10 --max-articles 50
python3 historical_validate.py extract --rules examples/sources_v3_model.yaml --html samples/
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

from crawler.dsl_schema import CrawlSpec  # Local imports
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
- Tests should be runnable as standalone scripts: `python3 test_commitment.py`
- For crawler changes, verify with `run_mock_crawl.py` and check output for `total_documents=N`
- For extraction changes, run `extract_test.py` or `historical_validate.py`
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
