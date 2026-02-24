Claude’s Plan
GABI-SYNC: Modular Architecture Refactoring Plan
Context
The GABI-KIMI codebase evolved into a monolith where pipeline stages, API, search, infra, and orchestration are all tightly coupled in src/gabi/. Key violations:

sync.py (1585 lines) orchestrates ALL pipeline phases in one function
fetcher.py (1558 lines) mixes HTTP, SSRF, circuit breaker, streaming
parser.py (1994 lines) bundles CSV, HTML, PDF, JSON parsers
Docker infra is all-or-nothing (can't run without ES/TEI)
No clear boundaries between discovery, ingestion, and orchestration
Current state: All old code archived in old_python_implementation/. Root is clean (just sources.yaml).

Goal: Build 5 core apps with strict separation of concerns, reusing battle-tested code from the archive.

Stack: Python + FastAPI + Celery + SQLAlchemy + asyncpg (same as before, restructured).

New Directory Structure

gabi-kimi/
├── old_python_implementation/       # Archived (git-tracked, read-only reference)
├── sources.yaml                     # Source definitions (stays at root)
│
├── src/gabi/
│   ├── __init__.py                  # Package root
│   ├── types.py                     # Shared enums/type aliases (from old types.py)
│   ├── exceptions.py                # Exception hierarchy (from old exceptions.py)
│   │
│   ├── contracts/                   # APP 1: GABI-CONTRACTS
│   │   ├── __init__.py              # Re-exports all contracts
│   │   ├── discovery.py             # DiscoveredURL, DiscoveryResult
│   │   ├── fetch.py                 # FetchMetadata, FetchedContent, StreamingFetchedContent
│   │   ├── parse.py                 # ParsedDocument, ParseResult, StreamingParseChunk
│   │   ├── fingerprint.py           # DocumentFingerprint, DuplicateCheckResult
│   │   ├── chunk.py                 # Chunk, ChunkingResult
│   │   ├── embed.py                 # EmbeddedChunk, EmbeddingResult
│   │   └── index.py                 # IndexDocument, IndexChunk, IndexingResult
│   │
│   ├── infra/                       # APP 2: GABI-INFRA
│   │   ├── __init__.py
│   │   ├── config.py                # Pydantic Settings (from old config.py)
│   │   ├── db.py                    # SQLAlchemy async engine + sessions (from old db.py)
│   │   ├── celery_app.py            # Celery configuration (from old worker.py)
│   │   └── logging.py               # Structured logging (from old logging_config.py)
│   │
│   ├── models/                      # Shared ORM models (from old models/)
│   │   ├── __init__.py
│   │   ├── base.py                  # DeclarativeBase + mixins
│   │   ├── source.py                # SourceRegistry
│   │   ├── document.py              # Document
│   │   ├── chunk.py                 # DocumentChunk (with embedding vector)
│   │   ├── execution.py             # ExecutionManifest
│   │   └── dlq.py                   # DLQMessage
│   │
│   ├── discover/                    # APP 3: GABI-DISCOVER
│   │   ├── __init__.py
│   │   ├── engine.py                # DiscoveryEngine (from old pipeline/discovery.py)
│   │   ├── config.py                # DiscoveryConfig
│   │   └── change_detection.py      # ChangeDetector (from old pipeline/change_detection.py)
│   │
│   ├── ingest/                      # APP 4: GABI-INGEST
│   │   ├── __init__.py
│   │   ├── fetcher/                 # HTTP content fetcher (from old pipeline/fetcher.py)
│   │   │   ├── __init__.py          # Re-exports ContentFetcher, FetcherConfig
│   │   │   ├── config.py            # FetcherConfig, FormatType, MAGIC_BYTES
│   │   │   ├── http_client.py       # Core fetch() logic
│   │   │   ├── streaming.py         # fetch_streaming() + queue-based architecture
│   │   │   └── ssrf.py              # SSRF protection + IP validation
│   │   │
│   │   ├── parser/                  # Multi-format parsers (from old pipeline/parser.py)
│   │   │   ├── __init__.py          # Re-exports get_parser, register_parser
│   │   │   ├── base.py              # BaseParser ABC + security constants
│   │   │   ├── csv_parser.py        # CSVParser + streaming parse
│   │   │   ├── html_parser.py       # HTMLParser
│   │   │   ├── pdf_parser.py        # PDFParser
│   │   │   ├── json_parser.py       # JSONParser
│   │   │   └── registry.py          # ParserRegistry + get_parser()
│   │   │
│   │   ├── fingerprint.py           # Fingerprinter (from old pipeline/fingerprint.py)
│   │   ├── deduplication.py         # Deduplicator (from old pipeline/deduplication.py)
│   │   ├── chunker.py               # Chunker (from old pipeline/chunker.py)
│   │   └── transforms.py            # Data transforms (from old pipeline/transforms.py)
│   │
│   └── sync/                        # APP 5: GABI-SYNC (orchestrator)
│       ├── __init__.py
│       ├── pipeline_runner.py       # _run_sync_pipeline - main orchestration
│       ├── memory.py                # Memory monitoring utilities
│       ├── error_classifier.py      # Error classification + DLQ helpers
│       ├── tasks.py                 # Celery tasks: sync_source_task
│       └── control.py               # Pipeline state control
│
├── docker-compose.yml               # With profiles: core, full, embed, index
├── pyproject.toml                   # Poetry config
├── alembic/                         # DB migrations (copied from old)
├── alembic.ini
├── scripts/
│   ├── start.sh                     # Bootstrap (from old, updated for profiles)
│   ├── seed_sources.py              # Seed sources from sources.yaml
│   └── dev.sh                       # Developer orchestrator
├── tests/
│   ├── unit/
│   │   ├── contracts/
│   │   ├── discover/
│   │   ├── ingest/
│   │   └── sync/
│   └── integration/
└── .env.example
Dependency Graph (strict layering - NO upward imports)

gabi.types + gabi.exceptions    (layer 0 - zero deps)
         |
    gabi.contracts              (layer 1 - pure dataclasses, depends on types only)
         |
    gabi.infra                  (layer 2 - config, db, celery, logging)
         |
    gabi.models                 (layer 3 - ORM models, depends on infra + types)
       / \
gabi.discover  gabi.ingest      (layer 4 - domain logic)
       \ /
    gabi.sync                   (layer 5 - orchestration, depends on ALL above)
Rule: A module can only import from its own layer or lower layers. Never upward.

Docker Compose Profile Strategy

# Profile "core" - minimum viable (PG + Redis only)
# Profile "embed" - adds TEI service
# Profile "index" - adds Elasticsearch
# Profile "full" - everything (PG + Redis + TEI + ES)
This means gabi.sync can run with just --profile core for discovery + ingestion + PG storage. Embeddings and ES indexing become optional plugins activated by source config + Docker profile.

Implementation Steps (ordered)
Step 1: Scaffold project + GABI-CONTRACTS
What: Create pyproject.toml, src/gabi/__init__.py, types.py, exceptions.py, contracts/
Source: Split old_python_implementation/src/gabi/pipeline/contracts.py (698 lines) into ~7 focused modules
Test: pytest tests/unit/contracts/ - pure Python, no infra needed
Risk: LOW - pure dataclasses with no dependencies

Step 2: GABI-INFRA
What: Create infra/config.py, infra/db.py, infra/celery_app.py, infra/logging.py
Source: From old config.py, db.py, worker.py, logging_config.py
Test: pytest tests/unit/infra/ + verify DB connection
Risk: LOW - standalone infrastructure code

Step 3: ORM Models + Migrations
What: Create models/ with source.py, document.py, chunk.py, execution.py, dlq.py
Source: From old models/ (mostly copy, trim unused)
Also: Copy alembic/ directory and alembic.ini, update import paths
Test: alembic upgrade head + verify tables created
Risk: LOW-MEDIUM - must verify migrations still work

Step 4: GABI-DISCOVER
What: Create discover/engine.py, discover/config.py, discover/change_detection.py
Source: From old pipeline/discovery.py + pipeline/change_detection.py
Test: Unit tests for URL pattern generation, static URL discovery
Risk: LOW - self-contained discovery logic

Step 5: GABI-INGEST (fetcher)
What: Split old pipeline/fetcher.py (1558 lines) into ingest/fetcher/ with 4 focused modules
Source: http_client.py (core fetch), streaming.py (queue-based streaming), ssrf.py (protection), config.py (settings)
Test: Unit tests for fetch, streaming, SSRF validation
Risk: MEDIUM - most complex file split, streaming must keep working

Step 6: GABI-INGEST (parser)
What: Split old pipeline/parser.py (1994 lines) into ingest/parser/ with per-format parsers
Source: csv_parser.py (including streaming), html_parser.py, pdf_parser.py, json_parser.py, registry.py
Test: Unit tests for each parser format independently
Risk: MEDIUM - must preserve streaming CSV parser behavior

Step 7: GABI-INGEST (remaining)
What: Move fingerprint.py, deduplication.py, chunker.py, transforms.py to ingest/
Source: Direct copies from old pipeline/ with updated imports
Test: Unit tests for fingerprinting, dedup, chunking
Risk: LOW - simple moves with import updates

Step 8: GABI-SYNC (orchestrator)
What: Refactor old tasks/sync.py (1585 lines) into sync/pipeline_runner.py, sync/memory.py, sync/error_classifier.py, sync/tasks.py
Source: The hardest split - must extract clean interfaces from the monolithic orchestrator
Key refactoring: Create PipelineComponents dataclass for dependency injection:


@dataclass
class PipelineComponents:
    fetcher: ContentFetcher
    fingerprinter: Fingerprinter
    deduplicator: Deduplicator
    chunker: Chunker
    embedder: Optional[Embedder]  # None when embed not available
Test: Integration test: discover + fetch + parse + fingerprint + dedup + chunk + index (no embeddings)
Risk: HIGH - this is the integration point where everything comes together

Step 9: Docker Compose + Scripts + E2E
What: Create docker-compose.yml with profiles, scripts/start.sh, scripts/seed_sources.py
Source: From old docker-compose.yml and scripts/
Test: docker compose --profile core up + seed_sources.py + run full tcu_normas ingestion
Risk: MEDIUM - Docker networking and health checks

Verification Plan
After all steps:

Unit tests pass: pytest tests/unit/ -v
Infrastructure boots: docker compose --profile core up -d (PG + Redis only)
Migrations work: alembic upgrade head
Sources seeded: python scripts/seed_sources.py
Full ingestion works: Run tcu_normas ingestion with streaming, verify:
Memory stays <300MB
All pipeline phases complete: discover -> fetch -> parse -> fingerprint -> dedup -> chunk -> index
Documents in PostgreSQL: SELECT COUNT(*) FROM documents WHERE source_id = 'tcu_normas'
Each app testable independently: pytest tests/unit/contracts/, pytest tests/unit/ingest/, etc.
Key Files to Reference from Old Implementation
Old Path	Purpose	Lines
old_python_implementation/src/gabi/pipeline/contracts.py	All data contracts	698
old_python_implementation/src/gabi/pipeline/fetcher.py	HTTP fetch + streaming	1558
old_python_implementation/src/gabi/pipeline/parser.py	Multi-format parsers	1994
old_python_implementation/src/gabi/tasks/sync.py	Pipeline orchestration	1585
old_python_implementation/src/gabi/pipeline/discovery.py	URL discovery	~400
old_python_implementation/src/gabi/config.py	Settings	~300
old_python_implementation/src/gabi/db.py	Database	~200
old_python_implementation/src/gabi/models/*.py	ORM models	~2500
old_python_implementation/docker-compose.yml	Docker config	~200
old_python_implementation/pyproject.toml	Dependencies	~100
Future Pluggable Apps (NOT in this plan)
These will be added later as separate apps following the same pattern:

gabi.embed/ - TEI embeddings (requires --profile embed Docker)
gabi.index/ - Elasticsearch indexing (requires --profile index Docker)
gabi.search/ - Hybrid search services
gabi.api/ - FastAPI REST endpoints
gabi.mcp/ - MCP server for Claude integration