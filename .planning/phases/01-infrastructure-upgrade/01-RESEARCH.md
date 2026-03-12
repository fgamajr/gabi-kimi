# Phase 1: Infrastructure Upgrade - Research

**Researched:** 2026-03-12
**Domain:** Elasticsearch 8.15 — JVM heap, dense_vector index, reindex API, alias swap
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Heap Upgrade (INFRA-01)**
- ES JVM heap must go from 512MB → 4GB+ (512MB is FATAL for kNN)
- Requires `docker stop gabi-es && docker rm gabi-es` then recreate with `-e "ES_JAVA_OPTS=-Xms4g -Xmx4g"`
- Keep same image: `docker.elastic.co/elasticsearch/elasticsearch:8.15.4`
- Keep same volume: `-v /media/psf/gabi_es:/usr/share/elasticsearch/data`
- Keep same config: `discovery.type=single-node`, `xpack.security.enabled=false`
- VM needs 8GB+ RAM allocated in Parallels

**Index v2 Mapping (INFRA-02)**
- New index `gabi_documents_v2` with ALL v1 BM25 fields PLUS:
  - `embedding`: dense_vector, 1024 dims, int8_hnsw, cosine similarity
  - `embedding_status`: keyword field
  - `embedding_model`: keyword field
- dense_vector CANNOT be added to existing index → full reindex required
- Mapping file: create `es_index_v2.json` in `src/backend/search/`

**Reindex v1 → v2 (INFRA-04)**
- Use ES `_reindex` API: source v1, dest v2
- Documents land with `embedding` null — filled in Phase 2
- BM25 search works immediately on v2
- Zero downtime — v1 stays available during reindex
- Doc count parity: v2 count must match v1

**Alias Swap (INFRA-03)**
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

### Deferred Ideas (OUT OF SCOPE)

- Embedding backfill (Phase 2)
- Hybrid search implementation (Phase 3)
- FastAPI endpoints (Phase 4)
- MCP tool upgrades (Phase 5)
- Multi-agent validation pipelines (out of scope for GSD planning)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INFRA-01 | ES JVM heap increased from 512MB to 4GB+ before any kNN workload | Docker recreate with ES_JAVA_OPTS=-Xms4g -Xmx4g; verify via GET /_nodes/stats/jvm |
| INFRA-02 | New ES index `gabi_documents_v2` created with `dense_vector` field (HNSW, int8 quantization) | ES 8.15 dense_vector mapping with int8_hnsw type; cosine similarity; mapping extends v1 |
| INFRA-03 | Alias `gabi_documents` points to v2 index; all consumers use alias | Atomic _aliases API swap; both MCP server and es_indexer already support alias via ES_INDEX env var |
| INFRA-04 | All existing BM25 data reindexed from v1 to v2 with zero downtime | _reindex API with wait_for_completion=false; slices=auto; refresh_interval=-1 during reindex |
</phase_requirements>

---

## Summary

Phase 1 upgrades Elasticsearch infrastructure to support vector workloads without breaking existing BM25 search. The core challenge is a sequence dependency: heap must be increased first (512MB will OOM on any kNN operation), then the v2 index can be created, then data reindexed from v1 to v2, then the alias atomically swapped.

All four operations are well-supported by ES 8.15 native APIs. The `dense_vector` mapping with `int8_hnsw` is the ES 8.15 default for float vectors and reduces memory footprint by ~75% compared to raw float32. The `_reindex` API with `wait_for_completion=false` allows async reindex of the ~7M document corpus without blocking consumers. The `_aliases` atomic swap ensures zero downtime for the cutover.

The two consumers that hardcode the index name are `ops/bin/mcp_es_server.py` (uses `ES_INDEX` env var, defaulting to `gabi_documents_v1`) and `src/backend/ingest/es_indexer.py` (same pattern). Both must be updated to target the alias `gabi_documents` rather than a versioned index name. The `es_indexer.py` already has an `ES_ALIAS` env var stub but it only adds the alias — it still writes to `ES_INDEX` directly.

**Primary recommendation:** Execute in strict sequence: (1) recreate Docker container with 4GB heap, (2) create v2 index from new mapping file, (3) run async reindex with performance settings, (4) verify doc count parity, (5) atomic alias swap, (6) update env vars to target alias.

---

## Standard Stack

### Core
| Library / API | Version | Purpose | Why Standard |
|---------------|---------|---------|--------------|
| ES `_reindex` API | 8.15 native | Copy all docs from v1 to v2 | Official ES API, handles field mapping changes, parallelizable with slices=auto |
| ES `_aliases` API | 8.15 native | Atomic alias swap | Single-request atomicity; no downtime window |
| ES `dense_vector` field | 8.15 native | Store 1024-dim embeddings | Only way to enable kNN search in ES; cannot retrofit existing index |
| Docker `ES_JAVA_OPTS` env var | — | Override JVM heap at container start | Standard ES Docker pattern; overrides all other JVM settings |

### Supporting
| Tool | Purpose | When to Use |
|------|---------|-------------|
| ES Tasks API (`GET /_tasks/{task_id}`) | Monitor async reindex progress | After launching `_reindex?wait_for_completion=false` |
| ES `_nodes/stats/jvm` | Verify heap allocation | Immediately after container recreate to confirm 4GB |
| ES `_count` API | Document count parity check | After reindex completes, before alias swap |

### Installation
No new packages needed. All operations use the existing `httpx` HTTP client already present in the codebase (`ops/bin/mcp_es_server.py`, `src/backend/ingest/es_indexer.py`).

---

## Architecture Patterns

### Recommended File Structure Changes
```
src/backend/search/
├── es_index_v1.json      # existing — do NOT modify
└── es_index_v2.json      # NEW — v1 fields + dense_vector + embedding_status + embedding_model

ops/
└── setup_elasticsearch.sh  # NEW or UPDATE — docker recreate script
```

### Pattern 1: ES Docker Container Recreate
**What:** Stop existing container (data volume persists), remove container, recreate with new env vars
**When to use:** Any time ES JVM settings need changing; settings cannot be changed on a running container

```bash
# Stop and remove container (volume at /media/psf/gabi_es is untouched)
docker stop gabi-es
docker rm gabi-es

# Recreate with 4GB heap — same image, same volume, same config
docker run -d \
  --name gabi-es \
  -p 9200:9200 \
  -e discovery.type=single-node \
  -e xpack.security.enabled=false \
  -e "ES_JAVA_OPTS=-Xms4g -Xmx4g" \
  -v /media/psf/gabi_es:/usr/share/elasticsearch/data \
  docker.elastic.co/elasticsearch/elasticsearch:8.15.4

# Verify heap
curl -s http://localhost:9200/_nodes/stats/jvm | python3 -m json.tool | grep heap_max_in_bytes
```

**Verification:** `heap_max_in_bytes` should be >= 4294967296 (4GB).

### Pattern 2: v2 Index Mapping with dense_vector
**What:** ES 8.15 `dense_vector` field with `int8_hnsw` index type; all v1 BM25 fields preserved exactly

```json
{
  "settings": {
    "index": {
      "number_of_shards": 1,
      "number_of_replicas": 0,
      "refresh_interval": "1s"
    },
    "analysis": {
      "analyzer": {
        "pt_folded": {
          "tokenizer": "standard",
          "filter": ["lowercase", "asciifolding"]
        }
      }
    }
  },
  "mappings": {
    "dynamic": false,
    "properties": {
      "doc_id":          { "type": "keyword" },
      "identifica":      { "type": "text", "analyzer": "pt_folded",
                           "fields": { "keyword": { "type": "keyword", "ignore_above": 1024 } } },
      "ementa":          { "type": "text", "analyzer": "pt_folded" },
      "body_plain":      { "type": "text", "analyzer": "pt_folded" },
      "art_type":        { "type": "text", "analyzer": "pt_folded",
                           "fields": { "keyword": { "type": "keyword", "ignore_above": 256 } } },
      "art_category":    { "type": "text", "analyzer": "pt_folded",
                           "fields": { "keyword": { "type": "keyword", "ignore_above": 512 } } },
      "issuing_organ":   { "type": "text", "analyzer": "pt_folded",
                           "fields": { "keyword": { "type": "keyword", "ignore_above": 1024 } } },
      "edition_section": { "type": "keyword" },
      "pub_date":        { "type": "date", "format": "strict_date_optional_time||yyyy-MM-dd" },
      "document_number": { "type": "keyword" },
      "document_year":   { "type": "integer" },
      "page_number":     { "type": "keyword" },
      "edition_number":  { "type": "keyword" },
      "source_zip":      { "type": "keyword" },
      "embedding": {
        "type": "dense_vector",
        "dims": 1024,
        "index": true,
        "similarity": "cosine",
        "index_options": { "type": "int8_hnsw" }
      },
      "embedding_status": { "type": "keyword" },
      "embedding_model":  { "type": "keyword" }
    }
  }
}
```

Source: [ES 8.15 dense_vector docs](https://www.elastic.co/guide/en/elasticsearch/reference/8.15/dense-vector.html) — HIGH confidence

### Pattern 3: Async Reindex with Performance Settings
**What:** Disable refresh and replicas during reindex, then restore; launch async to avoid HTTP timeout on ~7M docs
**When to use:** Large corpus reindex where real-time visibility during operation is not required

```python
# Step A: create v2 index with refresh_interval=-1 for reindex speed
PUT /gabi_documents_v2/_settings
{
  "index.refresh_interval": "-1",
  "index.number_of_replicas": 0
}

# Step B: launch async reindex
POST /_reindex?wait_for_completion=false&slices=auto
{
  "source": { "index": "gabi_documents_v1" },
  "dest":   { "index": "gabi_documents_v2" }
}
# Returns: { "task": "aBcDeFgH:123" }

# Step C: monitor
GET /_tasks/aBcDeFgH:123

# Step D: restore settings after task completes
PUT /gabi_documents_v2/_settings
{ "index.refresh_interval": "1s" }

# Step E: force merge (optional, improves kNN query performance)
POST /gabi_documents_v2/_forcemerge?max_num_segments=1
```

Source: [ES 8.15 reindex API docs](https://www.elastic.co/guide/en/elasticsearch/reference/8.15/docs-reindex.html) — HIGH confidence

### Pattern 4: Atomic Alias Swap
**What:** Remove alias from v1 and add to v2 in a single atomic request
**When to use:** Cutover after reindex completes and doc count parity is verified

```python
POST /_aliases
{
  "actions": [
    { "remove": { "index": "gabi_documents_v1", "alias": "gabi_documents" } },
    { "add":    { "index": "gabi_documents_v2", "alias": "gabi_documents" } }
  ]
}
```

Source: [ES 8.15 aliases API docs](https://www.elastic.co/guide/en/elasticsearch/reference/8.15/indices-aliases.html) — HIGH confidence

**Verification after swap:**
```bash
curl -s http://localhost:9200/gabi_documents | python3 -m json.tool
# Should show: "gabi_documents_v2": { "aliases": { "gabi_documents": {} } }
```

### Pattern 5: Consumer Update (alias targeting)
**What:** Both consumers currently default `ES_INDEX=gabi_documents_v1`. After alias swap, env must target alias.
**When to use:** After alias swap is verified

Changes required:
- `src/backend/core/config.py`: Change `ES_INDEX` default from `gabi_documents_v1` to `gabi_documents`
- `ops/bin/mcp_es_server.py`: Change `os.getenv("ES_INDEX", "gabi_documents_v1")` default to `gabi_documents`
- `.env` (if exists): Update `ES_INDEX=gabi_documents`

The MCP server uses `ES_INDEX` directly as the index target. The `es_indexer.py` uses `ES_INDEX` for writes and has an unused `ES_ALIAS` field. For Phase 1, the indexer can continue writing to `gabi_documents_v1` or be updated to write to v2 directly — using alias for writes is also valid since the alias resolves to one index.

### Anti-Patterns to Avoid
- **Changing heap on running container:** ES JVM settings cannot be changed without restart; hot-reload is not supported.
- **Adding `dense_vector` to v1 via PUT mapping:** ES rejects this — dense_vector cannot be added to existing indices. The only path is a new index + reindex.
- **Alias swap before parity check:** Swapping alias before verifying doc count parity risks serving incomplete data.
- **Setting Xms != Xmx:** ES requires min and max heap to be identical to prevent heap resizing pauses.
- **Reindex with `wait_for_completion=true` on 7M docs:** Will timeout the HTTP connection (~2+ hours for large corpus). Always use `wait_for_completion=false`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async reindex with progress tracking | Custom Mongo-cursor batch copy loop | ES `_reindex?wait_for_completion=false` + Tasks API | Native API handles bulk transfers, retry, slicing; custom loop cannot beat ES internal transfer speed |
| Atomic alias swap | Two separate requests with sleep | `_aliases` API with multi-action body | Two requests create a window where alias points to neither index; `_aliases` is explicitly atomic |
| Index creation from mapping file | Inline mapping in Python | Load `es_index_v2.json` from disk (same pattern as existing `es_indexer.py`) | Consistent with existing codebase pattern at `_MAPPING_PATH` |

**Key insight:** ES 8.15 handles all Phase 1 operations natively. The implementation is orchestration of existing APIs, not new code.

---

## Common Pitfalls

### Pitfall 1: OOM During kNN After Heap Increase
**What goes wrong:** Even at 4GB heap, if ES container also competes with MongoDB (15GB data) on an 8GB VM, OOM kills can still occur.
**Why it happens:** The CONTEXT.md notes "ES and Mongo have crashed before (OOM)." Both services running simultaneously on a shared-folder VM is tight.
**How to avoid:** Verify VM has 8GB+ allocated in Parallels before proceeding. After container recreate, run a health check with `GET /_nodes/stats/jvm` before any kNN test queries. Do not run kNN benchmark queries while ingest is active.
**Warning signs:** Container logs show `java.lang.OutOfMemoryError`; container exits unexpectedly.

### Pitfall 2: dense_vector Field Not Indexed (Missing `"index": true`)
**What goes wrong:** Omitting `"index": true` in the dense_vector mapping creates a stored-only vector field — kNN queries fail with "field is not indexed."
**Why it happens:** `"index": true` is documented as the default in current ES, but it is explicit in `int8_hnsw` configurations.
**How to avoid:** Always include `"index": true` explicitly in `es_index_v2.json`.
**Warning signs:** `POST /gabi_documents_v2/_knn_search` returns 400 with "field [embedding] is not indexed."

### Pitfall 3: Reindex Leaves Embedding Field as `null` but Breaks Cosine Similarity
**What goes wrong:** Documents with `embedding: null` do not cause mapping errors, but if anything writes a float32 array before Phase 2, mixing null and non-null vectors can cause unexpected kNN behavior.
**Why it happens:** Reindex copies all v1 fields; `embedding` is absent from v1 docs, so it lands as null/missing in v2. This is intentional and fine for Phase 1.
**How to avoid:** Confirm this is expected. Do NOT write any partial embeddings to v2 during Phase 1. Phase 2 owns the embedding backfill.
**Warning signs:** BM25 searches still work; kNN searches return 0 results (expected in Phase 1 — no embeddings yet).

### Pitfall 4: Alias Already Exists on v1 Before Swap
**What goes wrong:** If `gabi_documents` alias was previously added to v1 (via `es_indexer.py`'s `ensure_index` with `ES_ALIAS`), the "add" action in the swap may fail or create a write-conflict.
**Why it happens:** `es_indexer.py` has `self.alias = os.getenv("ES_ALIAS")` which adds the alias if set. Current default is None/empty so alias likely does NOT exist on v1 yet.
**How to avoid:** Before swap, verify alias state: `GET /_aliases/gabi_documents`. If it already resolves to v1, the remove+add swap will work correctly. If it doesn't exist, only the "add" action is needed.
**Warning signs:** `_aliases` API returns 404 or conflict on the remove action.

### Pitfall 5: MCP Server and es_indexer Use Hardcoded Default Index Names
**What goes wrong:** After alias swap, if the consumers still use `ES_INDEX=gabi_documents_v1`, they bypass the alias entirely and continue hitting v1.
**Why it happens:** Both files default to `gabi_documents_v1` in their `os.getenv()` calls. Env var must be updated.
**How to avoid:** After alias swap, update `ES_INDEX` env var (in `.env` or process environment) to `gabi_documents`. Verify by restarting MCP server and running a BM25 query — check which index the request hits via ES slow logs or `_search?explain=true`.
**Warning signs:** `es_health()` MCP tool still reports `"index": "gabi_documents_v1"`.

---

## Code Examples

### Verify JVM Heap After Container Recreate
```bash
# Source: ES /_nodes/stats/jvm API
curl -s http://localhost:9200/_nodes/stats/jvm | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
  nodes=d['nodes']; \
  [print(n['name'], n['jvm']['mem']['heap_max_in_bytes']) for n in nodes.values()]"
# Expected: heap_max_in_bytes >= 4294967296
```

### Create v2 Index from File
```python
# Source: mirrors existing es_indexer.py pattern at _MAPPING_PATH
import json, httpx
from pathlib import Path

mapping = json.loads(Path("src/backend/search/es_index_v2.json").read_text())
resp = httpx.put("http://localhost:9200/gabi_documents_v2", json=mapping)
resp.raise_for_status()
print(resp.json())
```

### Launch Async Reindex and Poll
```python
import httpx, time, json

client = httpx.Client(timeout=30)

# Optimize v2 for bulk load
client.put("http://localhost:9200/gabi_documents_v2/_settings",
           json={"index.refresh_interval": "-1"})

# Launch async reindex
resp = client.post(
    "http://localhost:9200/_reindex?wait_for_completion=false&slices=auto",
    json={"source": {"index": "gabi_documents_v1"},
          "dest":   {"index": "gabi_documents_v2"}}
)
task_id = resp.json()["task"]
print(f"Reindex task: {task_id}")

# Poll until complete
while True:
    status = client.get(f"http://localhost:9200/_tasks/{task_id}").json()
    if status.get("completed"):
        print("Done:", json.dumps(status["task"]["status"], indent=2))
        break
    created = status.get("task", {}).get("status", {}).get("created", "?")
    print(f"  created so far: {created}")
    time.sleep(30)

# Restore settings
client.put("http://localhost:9200/gabi_documents_v2/_settings",
           json={"index.refresh_interval": "1s"})
```

### Doc Count Parity Check
```python
import httpx

client = httpx.Client()
v1 = client.get("http://localhost:9200/gabi_documents_v1/_count").json()["count"]
v2 = client.get("http://localhost:9200/gabi_documents_v2/_count").json()["count"]
print(f"v1={v1}  v2={v2}  match={v1==v2}")
assert v1 == v2, f"Count mismatch: v1={v1} v2={v2}"
```

### Atomic Alias Swap
```python
import httpx

resp = httpx.post("http://localhost:9200/_aliases", json={
    "actions": [
        {"remove": {"index": "gabi_documents_v1", "alias": "gabi_documents"}},
        {"add":    {"index": "gabi_documents_v2", "alias": "gabi_documents"}}
    ]
})
resp.raise_for_status()
print(resp.json())  # {"acknowledged": true}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `float` dense_vector (raw fp32) | `int8_hnsw` quantized vectors | ES 8.12+ | 4x memory reduction; minor accuracy trade-off acceptable for DOU retrieval |
| `ES_JAVA_OPTS` in docker run | Bind-mounted `jvm.options.d/` file for production | ES 8.x docs recommendation | For this single-node dev/local setup, `ES_JAVA_OPTS` is the right choice — simpler and explicitly approved for non-production |
| Synchronous reindex (`wait_for_completion=true`) | Async reindex + Tasks API | ES 5.1+ | Required for large corpora; 7M docs will take hours |

**Deprecated/outdated:**
- `ES_HEAP_SIZE` env var: Replaced by `ES_JAVA_OPTS=-Xms{n}g -Xmx{n}g`; do not use `ES_HEAP_SIZE`.
- ELSER sparse vectors for Portuguese: Confirmed out of scope — English-only per project decisions.

---

## Open Questions

1. **Does `gabi_documents` alias already exist on v1?**
   - What we know: `es_indexer.py` has `ES_ALIAS` env var support but default is empty; alias was likely never created
   - What's unclear: Runtime state of the live ES instance
   - Recommendation: First task in the plan should probe `GET /_aliases` and conditionally handle both "alias exists" and "alias does not exist" cases

2. **Parallels VM RAM allocation — is it already at 8GB+?**
   - What we know: CONTEXT.md says "VM needs 8GB+ RAM allocated in Parallels"; previous OOM incidents occurred
   - What's unclear: Current VM memory setting
   - Recommendation: Add a pre-flight check step that reads `/proc/meminfo` to confirm available RAM before Docker recreate

3. **Reindex duration estimate for ~7M docs**
   - What we know: v1 index is ~8-12 GB; single-node ES; `slices=auto` on single shard = 1 slice (no parallelism benefit)
   - What's unclear: Actual throughput on this ARM VM with Parallels shared folder I/O
   - Recommendation: Estimate 2-4 hours conservatively; plan step should include a monitoring loop and not assume fast completion

4. **es_indexer.py alias write behavior**
   - What we know: `es_indexer.py` writes to `ES_INDEX` env var target; after Phase 1, new DOU ingest should go to v2
   - What's unclear: Whether to update `ES_INDEX` default to alias now or leave it pointing to `gabi_documents_v2` explicitly
   - Recommendation: Update `ES_INDEX` default to `gabi_documents` (the alias) in all consumers — this is the Phase 1 deliverable for INFRA-03

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | None (no formal test suite) — ad-hoc scripts in `ops/test_*.py` |
| Config file | None |
| Quick run command | `curl -s http://localhost:9200/_cluster/health` |
| Full suite command | See Phase gate checks below |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INFRA-01 | Heap >= 4GB on all nodes | smoke | `curl -s http://localhost:9200/_nodes/stats/jvm \| python3 -c "import json,sys; d=json.load(sys.stdin); h=[n['jvm']['mem']['heap_max_in_bytes'] for n in d['nodes'].values()]; assert all(x>=4294967296 for x in h), h"` | ❌ Wave 0 |
| INFRA-02 | v2 index exists with dense_vector field | smoke | `curl -s http://localhost:9200/gabi_documents_v2/_mapping \| python3 -c "import json,sys; m=json.load(sys.stdin); assert 'embedding' in m['gabi_documents_v2']['mappings']['properties']"` | ❌ Wave 0 |
| INFRA-03 | Alias resolves to v2; BM25 query returns results | smoke | `curl -s 'http://localhost:9200/gabi_documents/_search?q=decreto&size=1' \| python3 -c "import json,sys; d=json.load(sys.stdin); assert d['hits']['total']['value']>0"` | ❌ Wave 0 |
| INFRA-04 | Doc count parity v1 == v2 | smoke | `python3 -c "import httpx; v1=httpx.get('http://localhost:9200/gabi_documents_v1/_count').json()['count']; v2=httpx.get('http://localhost:9200/gabi_documents_v2/_count').json()['count']; assert v1==v2, f'{v1} != {v2}'"` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `curl -s http://localhost:9200/_cluster/health | python3 -m json.tool`
- **Per wave merge:** Run all 4 smoke checks above sequentially
- **Phase gate:** All 4 smoke checks green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `ops/test_infra_phase1.py` — covers INFRA-01 through INFRA-04 smoke checks
- [ ] No framework install needed — stdlib + httpx already present

---

## Sources

### Primary (HIGH confidence)
- [ES 8.15 dense_vector field type](https://www.elastic.co/guide/en/elasticsearch/reference/8.15/dense-vector.html) — int8_hnsw mapping, dims, similarity, index options
- [ES 8.15 reindex API](https://www.elastic.co/guide/en/elasticsearch/reference/8.15/docs-reindex.html) — async reindex, slices, refresh_interval optimization
- [ES 8.15 aliases API](https://www.elastic.co/guide/en/elasticsearch/reference/8.15/indices-aliases.html) — atomic add/remove actions

### Secondary (MEDIUM confidence)
- [ES memory management blog](https://www.elastic.co/blog/managing-and-troubleshooting-elasticsearch-memory) — circuit breaker defaults, heap sizing guidelines
- [Zero downtime reindex pattern](https://betterprogramming.pub/how-i-reindex-elasticsearch-without-downtime-6e8a6a512070) — alias-based reindex strategy (cross-verified with official docs)

### Tertiary (LOW confidence)
- None — all critical claims verified against official ES 8.15 documentation

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all APIs are ES 8.15 native; verified against official docs
- Architecture: HIGH — patterns derived directly from official API docs and existing codebase
- Pitfalls: HIGH (OOM) / MEDIUM (alias state) — OOM from project history; alias state needs runtime verification

**Research date:** 2026-03-12
**Valid until:** 2026-06-12 (ES 8.15.x is stable; no planned breaking changes to kNN or alias APIs in this window)
