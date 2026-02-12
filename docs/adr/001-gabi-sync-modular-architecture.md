# ADR 001: GABI-SYNC Modular Architecture

**Status:** Proposed  
**Date:** 2026-02-12  
**Author:** GABI Team  
**Decision:** Adopt modular architecture with strict layering  

## Context

GABI-KIMI evolved into a monolith where pipeline stages, API, search, infra, and orchestration are tightly coupled. Key problems:

- `sync.py` (1,585 lines) orchestrates ALL pipeline phases in one function
- `fetcher.py` (1,558 lines) mixes HTTP, SSRF, circuit breaker, streaming
- `parser.py` (1,994 lines) bundles CSV, HTML, PDF, JSON parsers
- Docker infra is all-or-nothing (can't run without ES/TEI)
- No clear boundaries between discovery, ingestion, and orchestration

The codebase is **battle-tested and works**, but violates Separation of Concerns, making it:
- Hard to test (requires full infrastructure)
- Hard to modify (changes ripple through codebase)
- Hard to understand (new developers need weeks)
- Hard to scale (can't deploy components independently)

## Decision

Adopt a **strictly layered modular architecture** with 6 layers (0-5) where each layer can only import from lower layers.

### Architecture Overview

```
Layer 0: Foundation (types, exceptions) - Zero dependencies
Layer 1: Contracts (dataclasses) - Depends only on Layer 0
Layer 2: Infrastructure (config, db, celery, logging) - Depends on 0,1
Layer 3: Models (ORM) - Depends on 0,1,2
Layer 4: Domain Apps (discover, ingest) - Depends on 0,1,2,3
Layer 5: Orchestration (sync) - Depends on ALL layers
```

### Directory Structure

```
src/gabi/
├── types.py              # Layer 0: Enums, type aliases
├── exceptions.py         # Layer 0: Exception hierarchy
│
├── contracts/            # Layer 1: Data contracts
│   ├── discovery.py      #   DiscoveredURL, DiscoveryConfig
│   ├── fetch.py          #   FetchedContent, FetchConfig
│   ├── parse.py          #   ParsedDocument, ParseConfig
│   ├── fingerprint.py    #   DocumentFingerprint
│   ├── chunk.py          #   Chunk, ChunkingResult
│   ├── embed.py          #   EmbeddedChunk, EmbeddingResult
│   └── index.py          #   IndexDocument, IndexingResult
│
├── infra/                # Layer 2: Infrastructure
│   ├── config.py         #   Pydantic Settings
│   ├── db.py             #   SQLAlchemy async engine
│   ├── celery_app.py     #   Celery configuration
│   └── logging.py        #   Structured logging
│
├── models/               # Layer 3: ORM Models
│   ├── base.py           #   DeclarativeBase
│   ├── source.py         #   SourceRegistry
│   ├── document.py       #   Document
│   ├── chunk.py          #   DocumentChunk
│   ├── execution.py      #   ExecutionManifest
│   └── dlq.py            #   DLQMessage
│
├── discover/             # Layer 4a: Discovery App
│   ├── engine.py         #   DiscoveryEngine
│   ├── config.py         #   DiscoveryConfig
│   └── change_detection.py
│
├── ingest/               # Layer 4b: Ingestion App
│   ├── fetcher/          #   HTTP content fetcher
│   │   ├── config.py
│   │   ├── http_client.py
│   │   ├── streaming.py
│   │   └── ssrf.py
│   ├── parser/           #   Multi-format parsers
│   │   ├── base.py
│   │   ├── csv_parser.py
│   │   ├── html_parser.py
│   │   ├── pdf_parser.py
│   │   ├── json_parser.py
│   │   └── registry.py
│   ├── fingerprint.py
│   ├── deduplication.py
│   ├── chunker.py
│   └── transforms.py
│
└── sync/                 # Layer 5: Orchestration
    ├── __init__.py
    ├── pipeline_runner.py    # Main orchestration
    ├── pipeline_components.py # DI container
    ├── memory.py
    ├── error_classifier.py
    ├── tasks.py              # Celery tasks
    └── control.py            # Pipeline state control
```

## Consequences

### Positive

1. **Testability**: Each module can be unit tested in isolation
2. **Clarity**: Clear boundaries make code easier to understand
3. **Maintainability**: Changes are localized to specific modules
4. **Scalability**: Apps can be deployed independently in future
5. **Onboarding**: New developers can learn one app at a time

### Negative

1. **Verbosity**: More files, more imports
2. **Refactoring Cost**: ~56 hours to migrate existing code
3. **Integration Complexity**: Must define stable interfaces between apps
4. **Performance**: Minimal overhead from module boundaries (negligible)

## Implementation Strategy

### Phase 1: Foundation (Week 1)
- Create `contracts/`, `types.py`, `exceptions.py`
- Port from `old_python_implementation/src/gabi/pipeline/contracts.py`
- **Deliverable**: Contracts module with 100% test coverage

### Phase 2: Infrastructure (Week 1)
- Create `infra/`, `models/`
- Port from `config.py`, `db.py`, `worker.py`
- **Deliverable**: Docker compose with PG + Redis only

### Phase 3: Discovery App (Week 2)
- Create `discover/`
- Port from `pipeline/discovery.py`, `pipeline/change_detection.py`
- **Deliverable**: Can discover URLs from sources.yaml

### Phase 4: Ingestion Apps (Week 3)
- Create `ingest/fetcher/` (split `fetcher.py`)
- Create `ingest/parser/` (split `parser.py`)
- Port remaining: `fingerprint.py`, `deduplication.py`, `chunker.py`
- **Deliverable**: Can fetch + parse + fingerprint + dedup + chunk

### Phase 5: Orchestration (Week 4)
- Create `sync/` with DI container pattern
- Refactor `tasks/sync.py` into focused modules
- **Deliverable**: Full pipeline works end-to-end

### Phase 6: Integration (Week 5)
- Docker compose profiles: core, embed, index
- Scripts: `dev.sh`, `start.sh`
- Tests: Integration + E2E
- **Deliverable**: Production-ready system

## Boundary Rules

### Import Rules (Strict)

```python
# ✅ ALLOWED: Import from lower layer
# In gabi/ingest/fetcher/http_client.py:
from gabi.contracts.fetch import FetchConfig          # Layer 1 ← OK
from gabi.infra.config import settings               # Layer 2 ← OK
from gabi.models.document import Document            # Layer 3 ← OK

# ❌ FORBIDDEN: Import from same or higher layer
from gabi.sync.pipeline_runner import PipelineRunner  # Layer 5 ← VIOLATION!
from gabi.ingest.parser.csv_parser import CSVParser   # Same layer sibling ← VIOLATION!
```

### Dependency Injection Pattern

```python
# gabi/sync/pipeline_components.py
@dataclass
class PipelineComponents:
    """Dependency injection container.
    
    Allows mocking any component in tests.
    Enables optional features (embed, index).
    """
    discovery_engine: DiscoveryEngine
    fetcher: ContentFetcher
    parser: ContentParser
    fingerprinter: Fingerprinter
    deduplicator: Deduplicator
    chunker: Chunker
    embedder: Optional[Embedder] = None      # Optional!
    indexer: Optional[Indexer] = None         # Optional!
```

## Docker Compose Profiles

```yaml
# Profile "core" - minimum viable (PG + Redis only)
docker compose --profile core up

# Profile "embed" - adds TEI for embeddings
docker compose --profile core --profile embed up

# Profile "index" - adds Elasticsearch
docker compose --profile core --profile index up

# Profile "full" - everything
docker compose --profile full up
```

This allows:
- Running discovery + ingestion + PG storage without ES/TEI
- Adding ES/TEI only when needed
- Testing with minimal infrastructure

## Sources.yaml v2

See `sources_v2.yaml` for new structure. Key changes:

1. **Clear phase separation**: discovery, fetch, parse, transform, pipeline
2. **Field-level configuration**: Each field declares transforms, storage, indexing
3. **Transform registry**: Reusable transforms defined centrally
4. **Validation rules**: Declarative validation
5. **Pipeline enablement**: Per-phase enable/disable

## Alternatives Considered

### Option A: Keep Monolith
- **Pros**: Zero refactoring cost
- **Cons**: Technical debt compounds, eventually unmanageable
- **Verdict**: Rejected - codebase is already hard to modify

### Option B: Microservices
- **Pros**: True independence, different languages/stacks possible
- **Cons**: Operational complexity, network latency, needs k8s
- **Verdict**: Rejected - overkill for current scale, team size = 1

### Option C: Modular Monolith (Selected)
- **Pros**: Code organization benefits, can extract to services later
- **Cons**: Still deployed as unit (for now)
- **Verdict**: Accepted - best balance for current situation

## Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Refactoring introduces bugs | High | High | Comprehensive test suite before each phase |
| Takes longer than estimated | Medium | Medium | Work in phases, can stop after any phase |
| Interfaces between apps unstable | Medium | High | Start with simple interfaces, evolve as needed |
| Performance regression | Low | Medium | Benchmark before/after, streaming must stay constant-memory |

## Success Criteria

After implementation:

1. ✅ Unit tests pass: `pytest tests/unit/ -v`
2. ✅ Infrastructure boots: `docker compose --profile core up -d`
3. ✅ Migrations work: `alembic upgrade head`
4. ✅ Sources seeded: `python scripts/seed_sources.py`
5. ✅ Full ingestion works: Run tcu_normas with streaming, verify:
   - Memory stays <300MB (587MB file)
   - All phases complete
   - Documents in PostgreSQL
6. ✅ Each app testable independently
7. ✅ No import cycles: `python -c "import gabi"` succeeds

## References

- Original codebase: `old_python_implementation/`
- Migration plan: `claude_plan.md`
- New source definitions: `sources_v2.yaml`
- Clean Architecture (Uncle Bob): https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html
- Modular Monoliths (Simon Brown): https://simonbrown.je/2021/05/30/modular-monoliths.html
