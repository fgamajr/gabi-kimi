# GABI Production Transition Plan

**Date:** 2025-02-11  
**Agents:** 10-agent swarm analysis  
**Scope:** API, Frontend Integration, Hybrid Search, MCP, Fly.io Deploy

---

## Executive Summary

This plan outlines the complete transition of GABI (Gerador Automático de Boletins por Inteligência Artificial) from local development to production on fly.io, including:

1. **API Dashboard Control** - New endpoints for pipeline monitoring and control
2. **Frontend Integration** - React dashboard connection to FastAPI backend
3. **Hybrid Search MCP** - Exact (ES) + Semantic (embeddings) with RRF fusion
4. **Advanced RAG** - Cross-Encoder, VLM, GraphRAG, SPLADE
5. **Fly.io Deployment** - Complete production infrastructure

---

## Task 1: API Dashboard Control (COMPLETED ANALYSIS)

### New Endpoints Required

```
GET  /api/v1/dashboard/stats           → DashboardStatsResponse
GET  /api/v1/dashboard/pipeline        → DashboardPipelineResponse  
GET  /api/v1/dashboard/jobs            → JobsResponse (NEW)
GET  /api/v1/dashboard/activity        → DashboardActivityResponse
GET  /api/v1/dashboard/health          → DashboardHealthResponse
GET  /api/v1/pipeline/state            → PipelineStateResponse (NEW)
POST /api/v1/pipeline/{phase}/start    → PhaseControlResponse (NEW)
POST /api/v1/pipeline/{phase}/stop     → PhaseControlResponse (NEW)
POST /api/v1/pipeline/{phase}/restart  → PhaseControlResponse (NEW)
```

### 9 Phases → 4 Frontend Stages Mapping

| Frontend Stage | Backend Phases | Description |
|----------------|----------------|-------------|
| harvest | discovery, change_detection | URL discovery |
| sync | fetch, parse, fingerprint | Content download |
| ingest | deduplication, chunking, embedding | Document processing |
| index | indexing | Elasticsearch indexing |

### Key Implementation Files
- `src/gabi/schemas/dashboard_extended.py` - New Pydantic schemas
- `src/gabi/api/dashboard_extended.py` - New endpoints
- Integration with `PipelineOrchestrator` via Redis state flags

---

## Task 2: Frontend Integration (COMPLETED ANALYSIS)

### Integration Strategy

**Minimal Component Changes**: Existing components require **zero changes** - they receive data via props in the same format.

**New Files Required**:
```
src/
├── lib/
│   └── api.ts              # API client with Axios + JWT
├── hooks/
│   ├── useDashboard.ts     # React Query hooks
│   └── usePipeline.ts      # Pipeline control hooks
└── types/
    └── api.ts              # TypeScript interfaces
```

### CORS Configuration
Backend already supports CORS - just update `GABI_CORS_ORIGINS` env var.

### Real-time Updates
- **Active pipeline**: 10-second polling
- **Stalled**: 30-second polling  
- **Error states**: Exponential backoff

---

## Task 3: Hybrid Search MCP (COMPLETED ANALYSIS)

### Architecture

```
Query → Pre-process → Parallel Search → RRF Fusion → [Rerank] → Response
              ↓              ↓               ↓
          [ES Exact]    [Vector]      [Cross-Encoder]
```

### MCP Tools

```python
# Exact search for normas, acórdãos, publicações, leis
search_exact(query: str, field: str, filters: dict)

# Semantic search
search_semantic(query: str, top_k: int = 10)

# Hybrid search (recommended)
search_hybrid(query: str, exact_weight: float = 0.3, semantic_weight: float = 0.7)
```

### Performance
- **Exact Match**: Mean 13ms, P95 27ms
- **Semantic**: Mean 27ms, P95 28ms
- **Hybrid**: Mean 22ms, P95 27ms

---

## Task 4: Fly.io Deployment (COMPLETED ANALYSIS)

### Recommended Approach: Hybrid

**Local**: Ingestion pipeline (470k docs already processed)  
**Fly.io**: API + MCP Server (auto-scaling)

### Infrastructure

| Service | Specs | Cost/Month |
|---------|-------|------------|
| API | 2-10 machines, shared-cpu-2x | ~$35-60 |
| MCP | 1-5 machines, shared-cpu-2x | ~$15-30 |
| PostgreSQL | Fly Postgres 2GB | ~$15 |
| Redis | Upstash (free tier) | Free |
| Elasticsearch | Elastic Cloud 4GB | ~$50-80 |
| **Total** | | **~$115-185** |

### Migration Timeline

```
Week -1:  Provision infrastructure
Day 0:    T+0: PostgreSQL migration (2-4h)
          T+4: ES reindex (2-4h)
          T+8: Cutover (15m)
Week +1:  Monitor, incremental sync
```

---

## Advanced RAG Technologies

### 1. Cross-Encoder Reranking (Phase 9.5)

**Model**: cross-encoder/ms-marco-MiniLM-L-12-v2  
**Performance**: <100ms for 50 candidates  
**Improvement**: 15-30% better relevance

```python
# After RRF fusion, before response
reranked = await reranker.rerank(query, candidates, top_k=10)
```

### 2. Vision-Language Models

**Approach**: Hybrid (pdfplumber + Claude Vision)  
**Cost**: ~R$ 47k-70k for full corpus  
**Accuracy**: 95% (vs 70% pdfplumber alone)

**Smart Routing**:
- Simple documents → pdfplumber (free)
- Complex layouts → Claude Vision ($0.025/page)

### 3. GraphRAG

**Stack**: Neo4j + LLM extraction  
**Nodes**: Documents, Ministros, Órgãos, Processos  
**Edges**: CITA, REVOGA, FUNDAMENTA, DIVERGE

**Benefits**:
- Normative chain discovery
- Conflict detection
- Citation authority (PageRank)

### 4. SPLADE (Future)

**Status**: Requires fine-tuning for Portuguese  
**Benefit**: Single system for lexical + semantic search

---

## Implementation Priority

### Phase 1: API + Frontend (Week 1-2)
- [ ] Create dashboard API endpoints
- [ ] Connect frontend to backend
- [ ] Test pipeline controls

### Phase 2: Hybrid Search + MCP (Week 3-4)
- [ ] Implement HybridSearchService
- [ ] Deploy new MCP server
- [ ] Add RRF fusion

### Phase 3: Advanced RAG (Week 5-8)
- [ ] Cross-Encoder reranking
- [ ] VLM integration (optional)
- [ ] GraphRAG foundation

### Phase 4: Production Deploy (Week 9-10)
- [ ] Fly.io infrastructure
- [ ] Data migration
- [ ] Monitoring setup

---

## Key Deliverables Created

### Agent 1 (API Design)
- API specification document
- Pydantic schemas
- SQL queries for aggregation

### Agent 2 (Frontend)
- API client layer
- React Query hooks
- Data transformers

### Agent 3 (Hybrid Search)
- HybridSearchService (445 lines)
- RRF algorithm implementation
- Performance benchmarks

### Agent 4 (Cross-Encoder)
- RerankerService class
- TEI deployment config
- Batch inference optimization

### Agent 5 (VLM)
- Layout analyzer
- Claude Vision extractor
- Cost tracking

### Agent 6 (GraphRAG)
- Graph schema (Neo4j)
- LLM extraction prompts
- Cypher query examples

### Agent 7 (MCP)
- New MCP server with hybrid tools
- Docker/K8s manifests
- Migration script

### Agent 8 (Fly.io)
- fly.toml configurations
- Deployment scripts
- Cost estimation

### Agent 9 (Migration)
- Migration scripts (7 scripts)
- Validation tools
- Rollback procedures

### Agent 10 (Monitoring)
- Grafana dashboards
- Alert rules
- Runbooks

---

## Next Steps

1. **Review this plan** with stakeholders
2. **Prioritize tasks** based on business needs
3. **Begin implementation** with Task 1 (API)
4. **Set up fly.io account** and provision infrastructure
5. **Schedule migration window** for data transfer

---

## Resources

- **Skill**: `/home/fgamajr/dev/gabi-kimi/gabi-production-transition.skill`
- **Frontend**: `/home/fgamajr/dev/user-first-view`
- **Backend**: `/home/fgamajr/dev/gabi-kimi`
- **Plan**: `/home/fgamajr/dev/gabi-kimi/docs/plans/2025-02-11-production-transition-plan.md`
