# GABI — Busca Inteligente do Diário Oficial da União

## What This Is

A professional search and analysis platform for Brazil's Diário Oficial da União (DOU). Combines hybrid search (BM25 + vector + RRF), document visualization, analytics dashboards, and LLM-powered chat — all wrapped in a dark editorial UI built with React/Lovable. The backend handles automated ingestion of government publications with cryptographic integrity (CRSS-1).

## Core Value

Users can find any published legal act in the DOU quickly and read it in a clean, professional interface — search that actually works for legal documents.

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

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
- ✓ React/Lovable frontend integrated with FastAPI backend — existing
- ✓ Media serving for document images — existing

### Active

<!-- Current scope. Building toward these. -->

- [ ] Admin page with document upload (individual XML or ZIP)
- [ ] Upload to Fly.io blob storage with immediate user release
- [ ] Background worker: unzip → deduplicate → ingest or reject
- [ ] Worker control table for tracking background job status
- [x] Remove legacy Alpine.js frontend (`web/index.html`) (Phase 10)
- [ ] Vite dev proxy configuration for local development
- [ ] Polish frontend: fix remaining integration issues

### Out of Scope

<!-- Explicit boundaries. Includes reasoning to prevent re-adding. -->

- Landing/marketing page — this is an operational tool, not a campaign
- Mobile native app — web-first, responsive design handles mobile
- Real-time collaborative editing — read-only document platform
- Public user registration — access controlled via admin-issued tokens

## Context

- Frontend was built with Lovable (nova-refine), source mirrored at github.com/fgamajr/nova-refine.git
- Backend runs on Fly.io with PostgreSQL, Elasticsearch, and Redis
- Fly.io has blob storage service available for document uploads
- Ingestion pipeline already handles XML parsing, normalization, deduplication via hashes
- Design direction: Dark Operational Editorial — Nubank-inspired purple accent, cool navy backgrounds
- Fonts: Manrope (UI), Source Serif 4 (editorial), JetBrains Mono (code)
- DOU XML format: `<article pubDate="DD/MM/YYYY">` with `id_materia`, `artType`, body content
- Deduplication uses natural_key_hash (type + number + year + organ cascade)

## Constraints

- **Deployment**: Fly.io — backend serves React SPA at `/` and `/dist/`
- **Data integrity**: Registry tables are immutable (append-only, CRSS-1 sealed)
- **Auth**: Bearer tokens issued by admin, session cookies for frontend
- **Search**: Must support Portuguese with accent-insensitive matching (ASCII folding)
- **Budget**: Fly.io resource limits — background workers must be efficient

## Key Decisions

<!-- Decisions that constrain future work. Add throughout project lifecycle. -->

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| React/Lovable over Alpine.js | Production-quality component system, TypeScript, better DX | Phase 10: Alpine removed; React SPA only |
| Background processing for uploads | Don't block user on ingestion — return immediately after upload | — Pending |
| Worker control table | Track job status, enable retry, surface errors to admin | — Pending |
| Fly.io blob storage for uploads | Native integration, no external S3 dependency | — Pending |

---
*Last updated: 2026-03-08 after initialization*
