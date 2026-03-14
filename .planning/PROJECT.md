# GABI — Hybrid Search Milestone

## What This Is

GABI (Gestao Automatizada de Busca Inteligente) is a full-text search platform for Brazil's Diario Oficial da Uniao (DOU). It ingests ~7M legal documents (2002-2026) from in.gov.br, stores them in MongoDB, indexes to Elasticsearch for BM25 search, and exposes search via MCP tools for Claude Code. This milestone adds semantic vector search alongside existing BM25, fuses results with Cohere Rerank, and exposes hybrid search through both FastAPI REST endpoints and upgraded MCP tools.

## Core Value

Legal professionals and AI agents can find the most relevant DOU documents by combining keyword precision (BM25) with meaning-based retrieval (semantic vectors), reranked for quality — across all 7M documents.

## Requirements

### Validated

- ✓ DOU ZIP ingestion pipeline (sync_dou.py) — existing
- ✓ MongoDB document storage with Pydantic models — existing
- ✓ Elasticsearch BM25 indexing with Portuguese analyzer — existing
- ✓ MCP server with 5 search tools (es_search, es_suggest, es_facets, es_document, es_health) — existing
- ✓ Cursor-based incremental ES sync — existing
- ✓ FastAPI application skeleton — existing
- ✓ Deterministic document IDs and upsert logic — existing

### Active

- [ ] Elasticsearch dense_vector field and kNN search capability
- [ ] Embedding generation pipeline for all 7M documents
- [ ] Hybrid BM25 + kNN search query composition
- [ ] Cohere Rerank integration for result fusion
- [ ] FastAPI search endpoints exposing hybrid search
- [ ] Upgraded MCP tools using hybrid search backend
- [ ] Incremental embedding sync for new documents

### Out of Scope

- Frontend search UI — no web interface changes in this milestone
- MongoDB Atlas Search — using ES-native kNN instead
- Local cross-encoder models — using Cohere Rerank API
- GPU infrastructure — ES handles vector search natively
- Authentication/authorization changes — internal tool

## Context

- ES 8.15.4 already deployed locally via Docker with security disabled
- MongoDB has ~7M documents with optional `embedding` field already in the Pydantic model
- Existing MCP server at `ops/bin/mcp_es_server.py` uses httpx for ES communication
- ES index mapping (`es_index_v1.json`) currently has no dense_vector field
- The codebase already has references to OpenAI embedding API in archive_legacy and env vars (`EMBED_API_KEY`, `OPENAI_API_KEY`)
- Cohere Rerank supports Portuguese text
- ES 8.x supports native kNN with HNSW algorithm and `dense_vector` field type

## Constraints

- **Search engine**: Elasticsearch 8.x native kNN — no external vector DB
- **Reranker**: Cohere Rerank API — requires `COHERE_API_KEY` env var
- **Embedding model**: ES ELSER or external model via OpenAI-compatible API — must handle Portuguese legal text well
- **Scale**: Must work across all ~7M documents — embedding pipeline must be batch-friendly and resumable
- **Backward compatibility**: Existing BM25 search must continue to work; hybrid is additive

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| ES native kNN over external vector DB | Already have ES 8.x, fewer moving parts, co-located with BM25 index | — Pending |
| Cohere Rerank over RRF-only | Better result quality for Portuguese legal text, acceptable API cost | — Pending |
| Upgrade existing MCP tools over new tools | Maintain backward compatibility, single search interface | — Pending |
| Full stack (not MVP subset) | User wants all 7M docs embedded and hybrid search in production | — Pending |

---
*Last updated: 2026-03-12 after initialization*
