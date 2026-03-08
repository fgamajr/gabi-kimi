# Technology Stack

**Analysis Date:** 2026-03-08

## Languages

**Primary:**
- Python 3.12+ (3.13 in production Docker) - Backend API, ingestion pipeline, MCP servers, search adapters
- TypeScript 5.8 - Frontend SPA (React)

**Secondary:**
- SQL - PostgreSQL schema definitions (`src/backend/dbsync/*.sql`)
- YAML - Pipeline and source configuration (`config/`)
- HTML/CSS - Frontend templates and styling

## Runtime

**Backend:**
- CPython 3.12 (development), 3.13 (production Docker image `python:3.13-slim`)
- ASGI via Uvicorn

**Frontend:**
- Node.js (Vite dev server on port 8080)
- Bun available (lockfiles `bun.lock`, `bun.lockb` present alongside `package-lock.json`)

**Package Managers:**
- pip (backend) - `requirements.txt` at root and `ops/deploy/web/requirements.txt`
- npm / bun (frontend) - `src/frontend/web/package.json`
- Lockfiles: `package-lock.json` and `bun.lock` both present

## Frameworks

**Core:**
- FastAPI >= 0.115 - Web API server (`src/backend/apps/web_server.py`)
- React 18.3 - Frontend SPA (`src/frontend/web/`)
- Pydantic >= 2.0 - Request/response validation in FastAPI

**UI:**
- Tailwind CSS 3.4 - Utility-first styling (`src/frontend/web/tailwind.config.ts`)
- shadcn/ui (Radix UI primitives) - Component library (`src/frontend/web/src/components/ui/`)
- Framer Motion 12 - Animations
- Recharts 2.15 - Data visualization / charts
- Lucide React 0.462 - Icon library

**Testing:**
- Vitest 3.2 - Frontend test runner (`src/frontend/web/vitest.config.ts`)
- Testing Library (React 16 + jest-dom 6) - Component testing
- jsdom 20 - DOM environment for tests

**Build/Dev:**
- Vite 5.4 - Frontend build tool with SWC plugin (`@vitejs/plugin-react-swc`)
- ESLint 9 + typescript-eslint 8 - Linting (`src/frontend/web/eslint.config.js`)
- PostCSS + Autoprefixer - CSS processing
- lovable-tagger 1.1 - Dev-mode component tagging plugin

## Key Dependencies

**Critical (Backend):**
- `psycopg2-binary` >= 2.9 - PostgreSQL driver (sync, used throughout backend)
- `httpx` >= 0.27 - HTTP client for Elasticsearch, DashScope Qwen API, embedding APIs
- `redis` >= 5.0 - Query analytics, caching, rate limiting (sync + async)
- `mcp` >= 1.26.0 - Model Context Protocol server SDK (`FastMCP`)
- `python-dotenv` - Environment variable loading from `.env`

**Critical (Frontend):**
- `@tanstack/react-query` 5.83 - Server state management / data fetching
- `react-router-dom` 6.30 - Client-side routing
- `zod` 3.25 - Schema validation
- `react-hook-form` 7.61 + `@hookform/resolvers` - Form handling
- `sonner` 1.7 - Toast notifications

**Infrastructure (Backend):**
- `beautifulsoup4` >= 4.14 - HTML extraction from DOU documents
- `reportlab` >= 4.4 - PDF generation
- `pyyaml` >= 6.0 - YAML config parsing
- `loguru` >= 0.7 - Structured logging (root requirements.txt)

**Infrastructure (Frontend):**
- `cmdk` 1.1 - Command palette component
- `vaul` 0.9 - Drawer/bottom sheet component
- `embla-carousel-react` 8.6 - Carousel
- `date-fns` 3.6 - Date formatting
- `tailwind-merge` 2.6 + `class-variance-authority` 0.7 + `clsx` 2.1 - className utilities (shadcn pattern)

## Configuration

**Environment:**
- `.env` file present at project root (loaded via `python-dotenv` / `load_dotenv()`)
- `.env.example` present for reference
- Frontend env: `VITE_API_BASE_URL` (build-time, via Vite `import.meta.env`)

**Key Backend Env Vars:**
- `PG_DSN` or `PGHOST`/`PGPORT`/`PGDATABASE`/`PGUSER`/`PGPASSWORD` - PostgreSQL connection
- `QWEN_API_KEY`, `QWEN_MODEL` - DashScope Qwen chat API
- `ES_URL`, `ES_INDEX`, `ES_USERNAME`, `ES_PASSWORD` - Elasticsearch connection
- `REDIS_URL` - Redis connection
- `SEARCH_BACKEND` - Backend selector (`pg` or `es` or `hybrid`)
- `EMBED_PROVIDER`, `EMBED_MODEL`, `EMBED_API_KEY`, `EMBED_BASE_URL` - Embedding pipeline
- `GABI_API_TOKENS` - API authentication tokens (CSV)
- `GABI_AUTH_SECRET` - Session signing secret
- `GABI_ALLOWED_HOSTS`, `GABI_CORS_ORIGINS` - Security configuration
- `FLY_APP_NAME` - Fly.io detection (disables local-dev auth bypass)

**Build:**
- `src/frontend/web/vite.config.ts` - Vite build config (base path `/dist/`, manual chunk splitting)
- `src/frontend/web/tsconfig.json` - TypeScript config (lenient: `noImplicitAny: false`, `strictNullChecks: false`)
- `src/frontend/web/tailwind.config.ts` - Tailwind with HSL CSS variable design tokens
- `src/frontend/web/postcss.config.js` - PostCSS with Tailwind + Autoprefixer
- `config/production.yaml` - Pipeline orchestrator config
- `config/sources/sources_v3.yaml` - DOU source definitions

## Platform Requirements

**Development:**
- Python 3.12+
- Node.js (or Bun) for frontend
- PostgreSQL (default: localhost:5433, database `gabi`)
- Redis (optional, degrades gracefully - `redis://localhost:6379/0`)
- Elasticsearch (optional, for hybrid search - `http://localhost:9200`)

**Production (Fly.io):**
- 3 Fly.io apps in `gru` (Sao Paulo) region:
  - `gabi-dou-web` - FastAPI backend (shared-cpu-2x, 512MB)
  - `gabi-dou-frontend` - Nginx static frontend (shared-cpu-1x, 256MB)
  - `gabi-dou-db` - PostgreSQL 16 (shared-cpu-4x, 1GB, persistent volume)
- Redis: `gabi-dou-redis.internal` (Fly internal networking)
- Docker: `python:3.13-slim` base image for backend
- Systemd timers for automated daily ingestion (`config/systemd/gabi-ingest.timer`)

---

*Stack analysis: 2026-03-08*
