# GABI DOU Search Quality Research — Reranker vs BM25 Optimization

**Date**: 2026-03-18
**Method**: Triangular consensus panel (qwen3-max, kimi-k2.5, claude-sonnet-4.5)
**Benchmark**: 10 representative queries against 16M DOU documents

## Executive Summary

**UNANIMOUS VERDICT**: Do not enable neural re-ranking on current infrastructure. Implement mandatory instrumentation (Phase 0), then surgical BM25 fixes (Phase 1). Neural re-ranking becomes viable only after infrastructure upgrade (>=32GB RAM) AND empirical validation of semantic gaps post-BM25 optimization (MRR@10 between 0.80-0.85).

**CRITICAL FINDING**: The system suffers from **measurement blindness** — no query logging, click-through tracking, or relevance metrics exist. Phase 0 instrumentation is the mandatory first step before any algorithmic changes.

## Benchmark Results (Current BM25 Pipeline)

| # | Query | Total | Latency | Rating | Issue |
|---|-------|-------|---------|--------|-------|
| 1 | licitação dispensa emergencial saúde | 5683 | 960ms | Excellent | Relevant dispensas |
| 2 | nomeação cargo comissionado DAS-5 | 1494 | 225ms | Good | DAS portarias |
| 3 | portaria suspensão benefício INSS | 1221 | 227ms | Excellent | INSS portarias |
| 4 | edital concurso público analista | 3 | 1078ms | Warning | Too restrictive (phrase-first) |
| 5 | resolução ANEEL tarifa energia | 6157 | 218ms | Good | ANEEL resolutions |
| 6 | acórdão TCU irregularidade convênio | 2754 | 196ms | Poor | Editais instead of Acórdãos |
| 7 | decreto regulamentação LGPD | 218 | 137ms | Mediocre | No actual decreto |
| 8 | aviso audiência pública meio ambiente | 567 | 203ms | Good | Audiência pública notices |
| 9 | instrução normativa receita federal IRPF | 443 | 209ms | Excellent | IN RFB about IRPF |
| 10 | contrato emergencial pandemia COVID | 1590 | 111ms | Poor | Aditivos, not contracts |

**Score: 5 excellent, 2 good, 1 mediocre, 2 poor**

## Critical Bugs Identified

### 1. art_type case sensitivity (CRITICAL)
`art_type` is a keyword field with inconsistent casing (Portaria/PORTARIA/PORTARIAS). Breaks 5x boost logic. Fix: add `art_type.normalized` with lowercase normalizer + `_update_by_query`.

### 2. Fallback query loses filters (HIGH)
Two-pass cascade drops art_type filters when falling back from phrase to bag-of-words. Query #10 returns aditivos instead of contratos.

### 3. No query analytics (HIGH)
Cannot compute MRR@10, NDCG@10, or validate improvements. Blocks all success measurement.

### 4. Phrase-first cascade brittleness (MEDIUM)
Binary threshold (<3 results) is too aggressive. Query #4 returns only 3 results.

### 5. Missing document-type extraction (MEDIUM)
Query classifier doesn't extract document types from natural language ("contrato emergencial" should boost contratos).

## Phased Roadmap

### Phase 0: Instrumentation (1 week) — MANDATORY
- Query logging middleware (FastAPI → MongoDB async)
- Offline evaluation pipeline (MRR@10, NDCG@10)
- Expand benchmark to 30 queries with human relevance judgments
- **Gate**: Baseline MRR@10 measured

### Phase 1: BM25 Hardening (2-3 weeks)
- Fix 1.1: art_type normalization (multi-field mapping + update_by_query)
- Fix 1.2: Replace cascade with proximity-based single query (slop=3, tie_breaker=0.3)
- Fix 1.3: Document-type extraction with term filter injection (~30 regex patterns)
- Fix 1.4: Explicit field weighting (identifica^3, ementa^1, texto^0.5)
- Fix 1.5: Docker memory limits (ES: 10G, MongoDB: 4G)
- **Target**: MRR@10 >= 0.80

### Phase 2: Validation (1 week)
- Re-run 30-query benchmark with human judgments
- Monitor p95 latency, memory, zero-result rate for 7 days
- **Go/no-go**:
  - STOP if MRR@10 >= 0.85 (BM25 sufficient)
  - PROCEED to Phase 3A if 0.80 <= MRR@10 < 0.85 with confirmed semantic gaps
  - ESCALATE if MRR@10 < 0.80

### Phase 3A: Semantic Enhancements (conditional, 2 weeks)
- Curated legal synonym expansion (search-time only, max 200 entries)
  - "lgpd, lei geral de proteção de dados, lei 13709"
  - "tcu, tribunal de contas da união"
  - Quarterly review by legal experts
- Optional negative boosting for disambiguation (Query #10 pattern)

### Phase 3B: Neural Re-Ranking (conditional, 3-4 weeks)
**Prerequisites (ALL must be met)**:
1. Infrastructure upgrade to >=32GB RAM (~+€40/month)
2. Phase 2 MRR@10 between 0.80-0.85 with confirmed semantic gaps
3. Offline validation: ΔMRR@10 >= 0.07 on failure queries
4. Latency validation: reranker adds <300ms on CPU for top-100

**Implementation**: qwen3-reranker-0.6B with 2 CPU cores, 4GB mem_limit, 2s timeout, async httpx adapter, A/B test (50/50 split, 2 weeks, >=1000 queries/arm)

**Rollback trigger**: p95 > 1.5s OR OOM rate > 0.1%

## Cost-Benefit Analysis

| Phase | Dev Hours | Infra Cost | Expected MRR@10 Gain | ROI |
|-------|-----------|------------|---------------------|-----|
| 0 + 1 (BM25) | 100h | €0 | +0.15-0.20 | HIGH |
| 3A (Synonyms) | 36h | €0 | +0.05-0.10 | MEDIUM |
| 3B (Reranker) | 60h | +€40/month | +0.07-0.12 | LOW-MEDIUM |

## Final Recommendation

**EXECUTE NOW**: Phase 0 → Phase 1 → Phase 2
**CONDITIONAL**: Phase 3A only if 0.80 <= MRR@10 < 0.85
**DEFER**: Phase 3B until infrastructure upgrade + empirical validation
**TIMELINE**: 5-11 weeks depending on conditional phases
