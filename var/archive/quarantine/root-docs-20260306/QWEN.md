> Last verified: 2026-03-06

# Qwen Integration Notes

Este documento descreve apenas a integracao opcional de chat no [web_server.py](web_server.py). Ele nao e um
guia geral do projeto; para isso use [README.md](README.md).

## O Que Existe Hoje

- O endpoint `POST /api/chat` em [web_server.py](web_server.py) tenta usar Qwen quando `QWEN_API_KEY` estiver
  configurada.
- Se a chave nao estiver presente ou a chamada falhar, o servidor usa o fallback local de resposta.
- A integracao e opcional. Busca, ingestao, BM25, Elasticsearch, MCP e embeddings nao dependem de Qwen.

## Variaveis de Ambiente

Use estas chaves em `.env`:

```bash
QWEN_API_KEY=
QWEN_MODEL=qwen-plus
```

## Setup Real do Projeto

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 infra/infra_manager.py up
python3 web_server.py
```

## Teste Manual

```bash
curl -sS -X POST http://127.0.0.1:8000/api/chat \
  -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":"Resuma a busca atual"}]}'
```

## Limites

- Este repositorio nao contem um servidor Qwen local.
- O arquivo nao substitui [README.md](README.md) nem [PIPELINE.md](PIPELINE.md).

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
