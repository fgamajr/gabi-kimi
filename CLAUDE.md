# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

GABI (Gestão Automatizada de Busca Inteligente) — full-text search platform for Brazil's Diário Oficial da União (DOU). Ingests ~16M legal documents (2002–2026) from `in.gov.br`, stores in MongoDB, indexes to Elasticsearch for BM25 search, and exposes search via MCP tools for Claude Code.

## Data Pipeline

```
in.gov.br ZIPs → sync_dou.py → MongoDB → es_indexer.py → Elasticsearch
                                                              ↑
                                              MCP Server (ops/bin/mcp_es_server.py)
```

## Commands

```bash
# Ingestion
python3 sync_dou.py --year 2024
python3 sync_dou.py --year 2024 --month 6

# Elasticsearch indexing
python3 -m src.backend.ingest.es_indexer backfill
python3 -m src.backend.ingest.es_indexer sync
python3 -m src.backend.ingest.es_indexer stats

# Lint & format (Python)
ruff check .
ruff check . --fix
ruff format .

# API server
python -m uvicorn src.backend.main:app --reload

# Frontend (genui-chat-app/)
cd genui-chat-app && npm run dev
```

No formal test suite. Ad-hoc tests in `ops/test_*.py`.

## Code Style

Detailed style guide in `AGENTS.md`. Key points:

- **Python 3.12+**, 120-char line length, Ruff for lint/format
- **Ruff ignored rules**: E402, E501
- **Import order**: future → stdlib → third-party → local (all alphabetical)
- **Local imports**: absolute paths from `src/` (e.g., `from src.backend.core.config import settings`)
- **Config**: Pydantic `BaseSettings` with `.env` file, single `settings` instance
- **Models**: Pydantic `BaseModel` with MongoDB `_id` alias mapping
- **CLI**: argparse with subcommands pattern
- **Logging**: `logging.getLogger(__name__)`, INFO level, stdout handler

## Architecture

### Backend (`src/backend/`)

| Module | Purpose |
|---|---|
| `core/config.py` | Pydantic Settings (Mongo, ES, paths) |
| `data/db.py` | MongoDB singleton connection |
| `data/models/document.py` | DouDocument, Reference, Enrichment models |
| `ingest/downloader.py` | Downloads ZIPs from in.gov.br via Liferay catalog |
| `ingest/dou_processor.py` | Parses ZIP→XML→DouDocument |
| `ingest/es_indexer.py` | Cursor-based MongoDB→ES bulk indexer |
| `search/es_index_v1.json` | ES mapping with `pt_folded` analyzer |
| `main.py` | FastAPI app |

### Key Files

- `sync_dou.py` — Main ingestion orchestrator (entry point)
- `ops/bin/mcp_es_server.py` — MCP server exposing 5 ES search tools
- `ops/data/dou_catalog_registry.json` — Maps YYYY-MM to Liferay folder IDs and ZIP filenames
- `src/backend/data/es_sync_cursor.json` — Cursor state for incremental ES sync

### Frontend (`genui-chat-app/`)

Separate Next.js 16 app with React 19, Tailwind v4, TypeScript. Has its own `package.json`.

Legacy frontend at `src/frontend/web/` (Vite + React 18 + Tailwind 3).

## Environment Variables

Defined in `.env` (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `MONGO_STRING` | `mongodb://localhost:27017/gabi_dou` | MongoDB URI |
| `DB_NAME` | `gabi_dou` | Database name |
| `ES_URL` | `http://localhost:9200` | Elasticsearch URL |
| `ES_INDEX` | `gabi_documents_v1` | ES index name |
| `DOU_DATA_PATH` | `/tmp/gabi-pipeline` | Temp download path |
| `ICLOUD_DATA_PATH` | — | ZIP archival (Parallels shared folder) |

## Infrastructure

- **MongoDB 7**: Docker container `gabi-mongo`, port 27017, volume at `/media/psf/gabi_mongo`
- **Elasticsearch 8.15.4**: Docker container `gabi-es`, port 9200, volume at `/media/psf/gabi_es`, security disabled
- Both use Parallels Desktop shared folders for persistent storage on macOS host
- Fly.io deployment was torn down — currently local-only
