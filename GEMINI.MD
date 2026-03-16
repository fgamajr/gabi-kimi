# GABI - Project Context & Gemini CLI Guidelines

This file contains foundational mandates, architectural context, and development guidelines for the GABI (Busca Inteligente no Diário Oficial da União) project. **Gemini CLI must adhere to these instructions when operating within this repository.**

## Project Overview
GABI is a full-text search platform and AI-agent tooling suite for Brazil's Official Gazette (DOU). It processes documents from 2002–2026 (~7M documents).
- **Data Flow:** `in.gov.br` (Liferay ZIPs) -> Parsed via Python -> MongoDB (Source of truth) -> Elasticsearch BM25 (Search Index) -> API/MCP.

## Tech Stack & Project Structure
- **Backend (`src/backend/`):** Python, FastAPI, MongoDB (`gabi_dou`), Elasticsearch 8.15.4.
- **Frontend (`src/frontend/app/`):** React 18, TypeScript, Vite, Tailwind CSS 3, shadcn/ui (in `components/ui`).
- **Ops & Scripts (`ops/`):** Operational scripts, MCP server (`ops/bin/mcp_es_server.py`), and test harnesses.
- **Documentation (`docs/`):** Execution plans, Liferay details, and v2 reindexing schema specifications.

## Engineering Directives & Execution Rules

### 1. Execution Environment (Docker-First)
- **Do not run Python scripts directly on the host** if it is an SMB-mounted view (e.g., macOS connecting to Linux). Cross-filesystem behavior and stale `__pycache__` can cause false failures.
- **Always use Docker Compose** to execute backend and ingestion scripts. 
  - *Example:* `docker compose exec backend python -m src.backend.ingest.sync_dou`
- Standard container names are: `gabi-kimi-mongo`, `gabi-kimi-elasticsearch`, `gabi-kimi-backend`, `gabi-kimi-frontend`.

### 2. Testing Protocol
- When testing API changes, use the adversarial test suite via the remote runner or Docker:
  - *Remote Runner:* `ops/bin/run_adversarial_remote.sh`
  - *Docker Exec:* `docker compose exec backend python ops/test_api_adversarial.py`
- Frontend tests are run using Vitest (`vitest.config.ts`).

### 3. Reindex V2 Initiative (In Progress)
- The project is currently transitioning to a "V2" schema for better field extraction.
- **Mandate:** Before modifying ingestion, parsing, or Elasticsearch mappings, consult the documents in `docs/REINDEX_V2_*.md`. 
- The V2 pipeline uses `src.backend.ingest.reindex_v2` and tests via a "canary" index before touching the main data.

### 4. Database Interaction
- **MongoDB** is the primary document store. The `documents` collection is the source of truth.
- **Elasticsearch** is purely an index. It is synchronized using cursor-based pagination via `src/backend/ingest/es_indexer.py`.
- If schema changes are made, the ES index must be recreated/backfilled via the indexer script.

### 5. AI Tooling & Local Repo Index
- The project includes a Model Context Protocol (MCP) server for Claude/Gemini interactions (`ops/bin/mcp_es_server.py`), exposing 5 tools for querying the DOU corpus.
- There is a local codebase assistance index stored under `.ai/` (managed by `src.backend.repo_index`). Ignore `.ai/` changes in source control.

### 6. Code Style & Conventions
- **Python:** Use strong typing. Keep FastAPI routes clean and delegate business logic to `services/` or `core/`.
- **Frontend:** Adhere to functional React components, hooks, and strict TypeScript. Use the existing `shadcn/ui` components located in `src/frontend/app/src/components/ui/` instead of installing new component libraries.
