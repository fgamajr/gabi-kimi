# Phase 1: Infrastructure Upgrade - Context

**Gathered:** 2026-03-12
**Status:** Ready for planning
**Source:** User-provided orchestration spec

<domain>
## Phase Boundary

Elasticsearch infrastructure ready for vector workloads: JVM heap at 4GB+, v2 index with dense_vector field exists, all v1 BM25 data available in v2, all consumers point to alias.

**Current state:**
- MongoDB: 16,305,252 DOU documents (2002-01 to 2026-02), ~15 GB
- Elasticsearch: container `gabi-es` on localhost:9200 (8.15.4, single-node, **512MB heap — FATAL for kNN**)
- ES data: macOS host via Parallels shared folder `/media/psf/gabi_es`
- Platform: Ubuntu 24.04 VM (Parallels, ARM/aarch64)

</domain>

<decisions>
## Implementation Decisions

### Heap Upgrade (INFRA-01)
- ES JVM heap must go from 512MB → 4GB+ (512MB is FATAL for kNN)
- Requires `docker stop gabi-es && docker rm gabi-es` then recreate with `-e "ES_JAVA_OPTS=-Xms4g -Xmx4g"`
- Keep same image: `docker.elastic.co/elasticsearch/elasticsearch:8.15.4`
- Keep same volume: `-v /media/psf/gabi_es:/usr/share/elasticsearch/data`
- Keep same config: `discovery.type=single-node`, `xpack.security.enabled=false`
- VM needs 8GB+ RAM allocated in Parallels

### Index v2 Mapping (INFRA-02)
- New index `gabi_documents_v2` with ALL v1 BM25 fields PLUS:
  - `embedding`: dense_vector, 1024 dims, int8_hnsw, cosine similarity
  - `embedding_status`: keyword field
  - `embedding_model`: keyword field
- dense_vector CANNOT be added to existing index → full reindex required
- Mapping file: create `es_index_v2.json` in `src/backend/search/`

### Reindex v1 → v2 (INFRA-04)
- Use ES `_reindex` API: source v1, dest v2
- Documents land with `embedding` null — filled in Phase 2
- BM25 search works immediately on v2
- Zero downtime — v1 stays available during reindex
- Doc count parity: v2 count must match v1

### Alias Swap (INFRA-03)
- Alias `gabi_documents` must resolve to v2 (not v1)
- Atomic alias swap via `_aliases` API (remove v1, add v2 in single action)
- All consumers (MCP server, FastAPI) use alias — no hardcoded index names
- Existing BM25 queries must return correct results through alias

### Claude's Discretion
- Order of operations within the phase (heap first is mandatory, rest flexible)
- Whether to create a script or manual steps for the docker recreate
- v2 mapping settings (shards, replicas, refresh interval during reindex)
- Whether to update `es_indexer.py` to target v2 or rely on alias
- Error handling if reindex fails partway

</decisions>

<specifics>
## Specific Ideas

- Docker run command: `docker run -d --name gabi-es -p 9200:9200 -e discovery.type=single-node -e xpack.security.enabled=false -e "ES_JAVA_OPTS=-Xms4g -Xmx4g" -v /media/psf/gabi_es:/usr/share/elasticsearch/data docker.elastic.co/elasticsearch/elasticsearch:8.15.4`
- Verify heap: `GET /_nodes/stats/jvm` → heap_max >= 4GB
- Verify alias: `GET /gabi_documents` → resolves to v2
- Memory constraint: ES and Mongo have crashed before (OOM) — 4GB heap on a shared VM needs careful RAM allocation
- Existing v1 mapping reference: `src/backend/search/es_index_v1.json`
- Storage estimate: v2 with vectors will be ~40-44 GB on `/media/psf/gabi_es` (but vectors empty until Phase 2, so Phase 1 adds ~same as v1 = ~8-12 GB more)

</specifics>

<deferred>
## Deferred Ideas

- Embedding backfill (Phase 2)
- Hybrid search implementation (Phase 3)
- FastAPI endpoints (Phase 4)
- MCP tool upgrades (Phase 5)
- Multi-agent validation pipelines (out of scope for GSD planning)

</deferred>

---

*Phase: 01-infrastructure-upgrade*
*Context gathered: 2026-03-12 via user-provided orchestration spec*
