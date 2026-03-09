# GABI — Busca Inteligente do Diário Oficial da União

## What This Is

A professional search and analysis platform for Brazil's Diário Oficial da União (DOU). Combines hybrid search (BM25 + vector + RRF), document visualization, analytics dashboards, and LLM-powered chat — all wrapped in a dark editorial UI built with React. The backend handles automated ingestion of government publications with cryptographic integrity (CRSS-1), admin document upload with background processing, and autonomous pipeline management via a React admin dashboard deployed on Fly.io.

## Core Value

Users can find any published legal act in the DOU quickly and read it in a clean, professional interface — search that actually works for legal documents.

## Requirements

### Validated

- ✓ Hybrid search with BM25 + vector + RRF reranking — existing
- ✓ Document viewer with editorial layout and TOC — existing
- ✓ Autocomplete and search suggestions — existing
- ✓ DOU section filtering (DO1, DO2, DO3, Extra) — existing
- ✓ Date range and art_type filtering — existing
- ✓ Analytics dashboard with temporal series — existing
- ✓ LLM chat with SSE streaming (Qwen) — existing
- ✓ Bearer token auth + session management — existing
- ✓ Automated ZIP ingestion pipeline from in.gov.br — existing
- ✓ Cryptographic commitment chain (CRSS-1) for data integrity — existing
- ✓ Elasticsearch indexing with Portuguese analyzer — existing
- ✓ Admin user/role/token management API — existing
- ✓ React frontend integrated with FastAPI backend — existing
- ✓ Media serving for document images — existing
- ✓ Admin upload pipeline (XML/ZIP via Tigris blob storage) — v1.0
- ✓ Background worker (ARQ + Redis) with deduplication and partial success — v1.0
- ✓ Job tracking with real-time SSE progress and retry — v1.0
- ✓ React admin UI (upload page, job dashboard, audit log) — v1.0
- ✓ Autonomous DOU pipeline (SQLite registry, Liferay discovery, multi-era extraction) — v1.0
- ✓ Fly.io 3-machine architecture (ES, Worker, Web) with .internal DNS — v1.0
- ✓ Admin dashboard (5-tab pipeline monitoring) — v1.0
- ✓ Worker proxy auth guard with rate limiting — v1.0
- ✓ Unified pipeline architectural reference document — v1.0
- ✓ Legacy Alpine.js frontend removed — v1.0

### Active

- [ ] Deduplication preview — show existing articles before processing
- [ ] Bulk job management — select multiple, retry all failed, clear completed
- [ ] Ingestion statistics dashboard — articles per day, error rates, processing duration
- [ ] Vite dev proxy configuration for local development

### Out of Scope

- Landing/marketing page — this is an operational tool, not a campaign
- Mobile native app — web-first, responsive design handles mobile
- Real-time collaborative editing — read-only document platform
- Public user registration — access controlled via admin-issued tokens
- In-browser document editor — read-only platform; editing violates CRSS-1 data integrity
- Scheduled upload from UI — automated pipeline already handles scheduling
- Email notifications — over-engineering for small admin team
- Upload from URL — adds complexity; admin can download locally first
- OCR / PDF-to-XML conversion — DOU publishes structured XML
- Public upload endpoint — admin-only; data quality risk
- Version rollback — registry is append-only (CRSS-1 sealed)

## Context

Shipped v1.0 with ~76,000 LOC (34k Python + 42k TypeScript).
Tech stack: FastAPI, React/Vite/Tailwind, Elasticsearch, PostgreSQL, Redis, SQLite, Fly.io.
Frontend was built with Lovable (nova-refine), source mirrored at github.com/fgamajr/nova-refine.git.
Design direction: Dark Operational Editorial — Nubank-inspired purple accent, cool navy backgrounds.
Fonts: Manrope (UI), Source Serif 4 (editorial), JetBrains Mono (code).
DOU XML format: `<article pubDate="DD/MM/YYYY">` with `id_materia`, `artType`, body content.
Deduplication uses natural_key_hash (type + number + year + organ cascade).

## Constraints

- **Deployment**: Fly.io — 3 machines (Web, Worker, ES) in `gru` region
- **Data integrity**: Registry tables are immutable (append-only, CRSS-1 sealed)
- **Auth**: Bearer tokens issued by admin, session cookies for frontend
- **Search**: Must support Portuguese with accent-insensitive matching (ASCII folding)
- **Budget**: Fly.io resource limits — ES 4GB, Worker 512MB, Web 512MB

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| React/Lovable over Alpine.js | Production-quality component system, TypeScript, better DX | ✓ Good — Alpine removed; React SPA only |
| Background processing for uploads | Don't block user on ingestion — return immediately after upload | ✓ Good — ARQ + Redis queue works reliably |
| Worker control table | Track job status, enable retry, surface errors to admin | ✓ Good — Full audit log with per-article breakdown |
| Fly.io blob storage for uploads | Native integration, no external S3 dependency | ✓ Good — Tigris S3-compatible via boto3 |
| Separate Fly.io machines | Avoid OOM on 512MB web machine; ES needs 4GB dedicated | ✓ Good — 3-machine architecture with .internal DNS |
| SQLite for pipeline registry | Worker is single-instance; SQLite WAL simpler than Postgres | ✓ Good — State machine with migration from JSON catalog |
| APScheduler for cron | Lightweight, in-process scheduler; no external service needed | ✓ Good — 5 cron jobs running autonomously |
| Liferay JSONWS for discovery | Official DOU publication API with structured metadata | ✓ Good — Rate-limited crawler with HEAD probe fallback |
| httpx proxy to worker.internal | Simple forwarding; worker is internal-only machine | ✓ Good — 10s timeout, 503 fallback, auth guard added |
| ZIP Slip protection | Security requirement for user-uploaded ZIP files | ✓ Good — Path traversal/absolute paths rejected before extract |
| RRF k=60 for hybrid search | Standard reciprocal rank fusion constant | — Pending validation |
| Enrichment via gpt-4o-mini | Cost-efficient for summarization at $2/day budget | — Pending implementation |

---
*Last updated: 2026-03-09 after v1.0 milestone*
