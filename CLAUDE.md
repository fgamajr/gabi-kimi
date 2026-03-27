# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

GABI — full-text search platform for Brazil's Diário Oficial da União (DOU). ~16M legal documents, 2002–2026. See @AGENTS.md for full architecture, data flow, and command reference.

## Build & Run

Everything runs in Docker. No host Python/Node required.

```bash
docker compose up --build          # Full stack
docker compose up -d mongo elasticsearch  # Storage only
docker compose logs -f backend     # Tail logs
```

### Backend (Python, inside container)

```bash
# Ingestion
docker compose exec backend python -m src.backend.ingest.sync_dou --year 2024
docker compose exec backend python -m src.backend.ingest.es_indexer backfill

# Lint & format
ruff check . --fix
ruff format .
```

### Frontend (TypeScript/React, inside container)

```bash
docker compose exec frontend sh -c "cd /workspace/src/frontend/app && npm run build"
docker compose exec frontend sh -c "cd /workspace/src/frontend/app && npm run lint"
```

## Code Style

### Python
- Ruff formatter + linter, 120-char line length
- Modern type hints: `str | None` not `Optional[str]`, `dict[str, Any]` not `Dict`
- Run Python modules with `-m` flag: `python -m src.backend.ingest.sync_dou`
- Imports: stdlib → third-party → local (absolute from `src/`)

### TypeScript/React
- ESLint configured; TailwindCSS + shadcn/ui patterns
- Use `@/` alias for imports from `src/`
- Functional components with hooks

## Key Gotchas

- **INLABS WAF blocks Hetzner datacenter IP** — solved via `INLABS_PROXY` (residential proxy in `.env`); Mac relay (`mac_daily_ingest.sh`) kept as fallback only
- **Vector search + reranker disabled by default** — BM25-only in production
- **Worker service** runs a continuous ES sync loop (30s polling); don't confuse with backend
- **MCP server** is a separate process at `ops/bin/mcp_es_server.py`, not part of the FastAPI app
- **SSR + SPA hybrid** — FastAPI serves SSR HTML for SEO at `/documento/` paths

## Subdirectory Instructions

For module-specific guidance, add CLAUDE.md files in subdirectories (e.g., `src/backend/CLAUDE.md`, `src/frontend/app/CLAUDE.md`). They load automatically when working in those directories.
