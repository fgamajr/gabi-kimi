# Gabi-DOU

## What This Is

Gabi-DOU is a brownfield full-text search platform for Brazil's Diario Oficial da Uniao. It already ingests DOU ZIP archives into MongoDB, indexes the corpus into Elasticsearch, exposes a FastAPI search API and MCP server, and serves a React search interface on top of that data.

This project initialization is for taking the existing local Docker-first system to a production-ready deployment that can run reliably, securely, and repeatedly outside the developer machine while preserving the current ingestion and search workflow.

## Core Value

Users can reliably search the official DOU corpus with trustworthy results and current data, without the platform becoming fragile to deploy or operate.

## Requirements

### Validated

- ✓ Ingest DOU source archives from `in.gov.br`, parse documents, and persist them in MongoDB for the 2002-2026 corpus window covered by the current pipeline — existing
- ✓ Index stored DOU documents into Elasticsearch and serve BM25-based search over the indexed corpus — existing
- ✓ Expose backend endpoints for search, autocomplete, document retrieval, stats, and search-type metadata through FastAPI — existing
- ✓ Provide a browser UI with homepage stats, search, result filtering, autocomplete, and document detail navigation — existing
- ✓ Run the platform locally through Docker Compose with separate frontend, backend, worker, MongoDB, and Elasticsearch services — existing
- ✓ Expose an MCP search surface for AI-agent workflows over the DOU corpus — existing

### Active

- [ ] Deploy the existing stack to a production topology with hardened networking, persistent data volumes, and a stable public entrypoint
- [ ] Secure production runtime configuration, secrets, and internal services so MongoDB, Elasticsearch, and auxiliary services are not publicly exposed
- [ ] Make recurring ingest and Elasticsearch sync production-safe with scheduling, observability, failure handling, and recovery procedures
- [ ] Add production readiness verification covering deploy, health, search behavior, and data freshness before cutover
- [ ] Establish a repeatable release and operations path from local development to production updates

### Out of Scope

- Major application replatforming away from the current Docker, FastAPI, MongoDB, Elasticsearch, and React architecture — productionization should harden the existing system first
- Expanding the product into new data domains beyond the DOU corpus — the current milestone is about shipping the existing platform safely
- Large new end-user feature bets unrelated to production readiness, such as account systems, billing, or non-search collaboration features — these would hide the deployment and operations work that must land first

## Context

The repository is already a working brownfield codebase with ingestion, indexing, API, frontend, and MCP surfaces. The local stack runs through Docker Compose, and the repository now also contains early production-oriented artifacts such as `docker-compose.prod.yml`, container entry scripts for production services, nginx reverse-proxy configuration, MongoDB auth bootstrap, host-hardening scripts, and rolling ingest automation.

The immediate problem is not "what should this product be?" but "what must exist so this product can survive outside local development?" That means the planning emphasis should be on infrastructure boundaries, deployment sequencing, data durability, service health, observability, operational runbooks, and safe cutover, while keeping the existing search and ingest behavior intact.

There is no existing `.planning/codebase/` map in this repository. For this initialization, validated requirements are inferred directly from the current repo structure and runtime files instead of waiting on a separate mapping pass.

## Constraints

- **Tech stack**: Preserve the current Python, FastAPI, MongoDB, Elasticsearch, React, Tailwind, and Docker Compose stack unless a later phase proves a change is necessary — the shortest path to production is to harden what already works
- **Deployment model**: The repo is designed to run container-first, with no required host Python or Node toolchain — production should keep that operator model simple
- **Data scale**: The corpus is large and continuously updated, so storage, indexing, and recovery choices must assume high document counts and long-running ingest jobs
- **Security**: Internet-facing deployment must not expose internal data services directly, and runtime secrets cannot live in committed files — production risk is otherwise unacceptable
- **Brownfield reality**: The working tree already contains unrelated in-progress production files from the user — planning must coexist with that work and not rewrite it

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Treat this as brownfield productionization, not a greenfield rewrite | The repo already has a working ingestion, search, API, UI, and MCP baseline | — Pending |
| Keep Docker Compose as the initial production orchestration surface | The repo already encodes service boundaries and operator workflows there | — Pending |
| Keep Elasticsearch BM25 as the required retrieval baseline in production | Search already works on BM25 today; hybrid and reranker paths can remain optional enhancements | — Pending |
| Prioritize deployment safety, service isolation, and ingest operations before new product features | The user goal is explicitly "from local to production" | — Pending |
| Skip separate codebase mapping during initialization | The repo is understandable enough to initialize planning now, and the goal is to unblock roadmap creation in this turn | ⚠️ Revisit |

---
*Last updated: 2026-03-17 after initialization*
