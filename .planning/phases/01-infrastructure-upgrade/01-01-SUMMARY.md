---
phase: 01-infrastructure-upgrade
plan: 01
subsystem: infra
tags: [elasticsearch, docker, dense_vector, knn, hybrid-search]

# Dependency graph
requires: []
provides:
  - "ES container gabi-es running with 4GB JVM heap (heap_max=4294967296)"
  - "gabi_documents_v2 index with dense_vector(1024d, int8_hnsw, cosine) field"
  - "All v1 BM25 fields preserved identically in v2 mapping"
  - "ops/setup_elasticsearch.sh updated with 4GB heap"
  - "src/backend/search/es_index_v2.json created with embedding fields"
affects: [02-reindex, 03-hybrid-search, 04-mcp-upgrade, 05-api-layer]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ES index versioning: v1 (BM25-only) vs v2 (BM25+dense_vector) — never mutate mappings, always create new index"
    - "dense_vector field requires explicit index:true or kNN queries will be rejected"

key-files:
  created:
    - src/backend/search/es_index_v2.json
  modified:
    - ops/setup_elasticsearch.sh

key-decisions:
  - "ES_JAVA_OPTS set to -Xms4g -Xmx4g — minimum required heap for kNN workloads on 7M documents"
  - "dense_vector dims=1024 with int8_hnsw quantization — matches Cohere embed-multilingual-v3.0 output dimension, int8 reduces memory 4x vs float32"
  - "explicit index:true on dense_vector field — omitting it creates stored-only field that silently rejects kNN queries"

patterns-established:
  - "Index mapping v2 pattern: copy all v1 fields identically, then append new fields — preserves BM25 compatibility"
  - "Volume permissions for Parallels shared folders: use busybox docker run to chown to uid 1000 before ES start"

requirements-completed: [INFRA-01, INFRA-02]

# Metrics
duration: 4min
completed: 2026-03-12
---

# Phase 1 Plan 01: ES Heap Upgrade and v2 Index Creation Summary

**ES container recreated with 4GB JVM heap and gabi_documents_v2 index created with dense_vector(1024d, int8_hnsw, cosine) field alongside all preserved v1 BM25 fields**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-03-12T14:44:27Z
- **Completed:** 2026-03-12T14:48:30Z
- **Tasks:** 1 of 2 (Task 2 is checkpoint:human-verify)
- **Files modified:** 2

## Accomplishments
- Updated `ops/setup_elasticsearch.sh` heap from 512MB to 4GB (ES_JAVA_OPTS=-Xms4g -Xmx4g)
- Created `src/backend/search/es_index_v2.json` with all v1 BM25 fields plus embedding (dense_vector 1024d int8_hnsw cosine), embedding_status (keyword), embedding_model (keyword), and explicit refresh_interval 1s
- Recreated Docker container `gabi-es` and verified heap_max_in_bytes=4294967296 via /_nodes/stats/jvm
- Created `gabi_documents_v2` ES index and verified dense_vector mapping with 1024 dims

## Task Commits

Each task was committed atomically:

1. **Task 1: Upgrade ES heap to 4GB and create v2 index mapping file** - `333ca134` (feat)

**Plan metadata:** (pending — after Task 2 checkpoint approval)

## Files Created/Modified
- `ops/setup_elasticsearch.sh` - Updated Docker run command: ES_JAVA_OPTS from -Xms512m -Xmx512m to -Xms4g -Xmx4g
- `src/backend/search/es_index_v2.json` - New v2 index mapping: all v1 fields + dense_vector(1024d, int8_hnsw, cosine) + embedding_status + embedding_model + refresh_interval 1s

## Decisions Made
- 4GB heap minimum for kNN workloads — ES circuit breaker OOMs on any kNN query with 512MB heap
- int8_hnsw quantization — reduces memory footprint 4x vs float32 HNSW with acceptable quality loss for legal text retrieval
- `index: true` is explicit on dense_vector field — omitting it creates a stored-only field that silently rejects all kNN queries

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed Parallels shared folder permission preventing ES container start**
- **Found during:** Task 1 (Step C: Recreate Docker container)
- **Issue:** `/media/psf/gabi_es` owned by root (uid 0), ES process runs as uid 1000 (elasticsearch user). Container exited immediately with `failed to obtain node locks` / `AccessDeniedException` on `/usr/share/elasticsearch/data/node.lock`.
- **Fix:** Used `docker run --rm -v /media/psf/gabi_es:/mnt busybox chown -R 1000:0 /mnt` to fix ownership without requiring sudo on host. Verified dir writable by current user (uid 1000) before starting ES.
- **Files modified:** None (filesystem permission change only)
- **Verification:** ES container started and passed heap verification
- **Committed in:** 333ca134 (Task 1 commit — no file change needed)

---

**Total deviations:** 1 auto-fixed (Rule 3 - blocking)
**Impact on plan:** Required fix to get ES running. No scope creep. The permission issue is a one-time setup artifact of fresh Parallels shared folder mounts.

## Issues Encountered
- Parallels shared folder `/media/psf/gabi_es` not writable by ES container user (uid 1000) — resolved with busybox chown workaround without requiring sudo.
- v1 index does not exist in this fresh ES instance (shared volume was empty). This is expected — previous data was in a separate volume or never existed here. Plan 02 will create v1 index during backfill from MongoDB.

## User Setup Required
None — no external service configuration required. The busybox chown fix was applied automatically.

## Next Phase Readiness
- ES running with 4GB heap — ready for kNN workloads
- `gabi_documents_v2` empty index ready to receive reindexed data from Plan 02
- `gabi_documents_v1` does not yet exist in this instance — Plan 02 (reindex) will need to create v1 first via `es_indexer backfill`, then reindex to v2
- No blockers for Phase 1 Plan 02 (reindex MongoDB → v1, then v1 → v2)

---
*Phase: 01-infrastructure-upgrade*
*Completed: 2026-03-12*
