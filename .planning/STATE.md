# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-12)

**Core value:** Legal professionals and AI agents find the most relevant DOU documents by combining keyword precision (BM25) with meaning-based retrieval (semantic vectors), reranked for quality — across all 7M documents.
**Current focus:** Phase 1 — Infrastructure Upgrade

## Current Position

Phase: 1 of 5 (Infrastructure Upgrade)
Plan: 0 of 3 in current phase
Status: Ready to plan
Last activity: 2026-03-12 — Roadmap created, all 28 requirements mapped across 5 phases

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**
- Total plans completed: 0
- Average duration: -
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**
- Last 5 plans: -
- Trend: -

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Pre-Phase 1]: ES native kNN over external vector DB — already have ES 8.x, fewer moving parts
- [Pre-Phase 1]: Cohere Rerank over RRF-only — better result quality for Portuguese legal text
- [Pre-Phase 1]: Upgrade existing MCP tools, do not add new tools — maintain backward compatibility

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1]: ES JVM heap currently at 512MB — MUST be raised to 4GB+ before any kNN workload (circuit breaker will OOM otherwise)
- [Phase 1]: `dense_vector` cannot be added to existing index mapping — full reindex to v2 required, irreversible
- [Phase 2]: ES cluster license tier unconfirmed — if Basic, RRF retriever unavailable; convex combination fallback required in Phase 3
- [Phase 2]: Embedding model lock-in risk — validate Cohere embed-multilingual-v3.0 on 10K DOU sample BEFORE starting 7M backfill
- [Phase 3]: kNN filter placement is a silent failure mode — filters must be inside `knn.filter`, not outer `bool.filter`

## Session Continuity

Last session: 2026-03-12
Stopped at: Roadmap creation complete — ready to plan Phase 1
Resume file: None
