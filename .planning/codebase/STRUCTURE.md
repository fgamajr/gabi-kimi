# Codebase Structure

**Analysis Date:** 2026-03-11

## Directory Layout

```
gabi-kimi/
├── .agents/                  # AI agent skills and configurations
│   └── skills/mcp/           # MCP-related skills
├── .claude/                  # Claude Code settings
├── .cursor/                  # Cursor IDE settings
├── .dev/                     # Development tooling (not production code)
│   ├── bench/                # Search benchmark framework
│   ├── mcp/                  # Development MCP server (dev-converge)
│   ├── json-render-mcp/      # JSON rendering MCP server
│   ├── ui-copilot-mcp/       # UI assistance MCP server
│   └── shannon/              # Shannon helper MCP server
├── .planning/                # Planning documents and codebase analysis
│   └── codebase/             # Architecture and structure docs
├── archive_legacy/           # Deprecated code (not in use)
│   └── src/backend/          # Legacy backend implementations
├── docs/                     # Project documentation
├── ops/                      # Operational scripts and data
│   ├── bin/                  # Executable scripts (MCP server)
│   ├── data/                 # Catalog registry, cursor state
│   └── sql/                  # SQL schemas (export tooling)
├── src/                      # Main source code
│   └── backend/              # Backend Python modules
│       ├── api/              # FastAPI routes (placeholder)
│       ├── core/             # Configuration
│       ├── data/             # Database, models
│       ├── ingest/           # Ingestion pipeline
│       ├── search/           # ES mappings
│       ├── services/         # Business logic (placeholder)
│       └── utils/            # Utilities (placeholder)
├── sync_dou.py               # Main ingestion orchestrator
├── .env                      # Environment variables (not committed)
├── .env.example              # Environment template
├── .mcp.json                 # MCP server configurations
├── AGENTS.md                 # AI coding agent guidelines
├── README.md                 # Project overview
└── requirements.txt          # Python dependencies
```

## Directory Purposes

### `src/backend/`
- Purpose: Core backend logic for DOU processing and search
- Contains: Python modules organized by layer
- Key files: `core/config.py`, `data/db.py`, `ingest/*.py`

### `src/backend/core/`
- Purpose: Centralized configuration management
- Contains: Pydantic Settings class
- Key files: `config.py`

### `src/backend/data/`
- Purpose: Database connections and data models
- Contains: MongoDB singleton, Pydantic models
- Key files: `db.py`, `models/document.py`

### `src/backend/ingest/`
- Purpose: Data ingestion pipeline components
- Contains: Downloaders, processors, indexers
- Key files: `downloader.py`, `dou_processor.py`, `es_indexer.py`

### `src/backend/search/`
- Purpose: Search infrastructure definitions
- Contains: Elasticsearch index mappings
- Key files: `es_index_v1.json`

### `ops/`
- Purpose: Operational scripts and runtime data
- Contains: Shell scripts, MCP server, test utilities
- Key files: `bin/mcp_es_server.py`, `setup_elasticsearch.sh`

### `ops/data/`
- Purpose: Runtime data files
- Contains: Catalog registry, cursor state
- Key files: `dou_catalog_registry.json`

### `.dev/`
- Purpose: Development and benchmarking tools
- Contains: MCP servers for AI development, benchmark framework
- Not part of production deployment

### `archive_legacy/`
- Purpose: Deprecated code preserved for reference
- Contains: Old backend implementations with Postgres, workers
- Not in active use

## Key File Locations

### Entry Points
- `sync_dou.py`: Main ingestion orchestrator
- `src/backend/main.py`: FastAPI application
- `ops/bin/mcp_es_server.py`: MCP search server

### Configuration
- `src/backend/core/config.py`: Settings class definition
- `.env`: Environment variables (secrets, paths)
- `.env.example`: Environment template
- `.mcp.json`: MCP server configurations

### Core Logic
- `src/backend/ingest/downloader.py`: ZIP download from in.gov.br
- `src/backend/ingest/dou_processor.py`: XML parsing and document creation
- `src/backend/ingest/es_indexer.py`: MongoDB to Elasticsearch sync

### Data Definitions
- `src/backend/data/models/document.py`: DouDocument Pydantic model
- `src/backend/search/es_index_v1.json`: Elasticsearch mapping
- `ops/data/dou_catalog_registry.json`: DOU catalog (folder IDs, filenames)

### State Files
- `src/backend/data/es_sync_cursor.json`: ES sync cursor state
- `ops/data/ingest_progress.log`: Ingestion progress log

## Naming Conventions

### Files
- **Python modules**: `snake_case.py` (e.g., `dou_processor.py`, `es_indexer.py`)
- **Configuration**: `snake_case.json` (e.g., `es_index_v1.json`)
- **Shell scripts**: `snake_case.sh` (e.g., `setup_elasticsearch.sh`)
- **Markdown**: `UPPERCASE.md` for docs (e.g., `ARCHITECTURE.md`)

### Directories
- **Python packages**: `snake_case/` (e.g., `ingest/`, `data/`)
- **Operational**: Short names (`ops/`, `bin/`)
- **Hidden**: Dot-prefix for tooling (`.dev/`, `.agents/`)

### Code Elements
- **Classes**: `PascalCase` (e.g., `DouDocument`, `ESClient`, `MongoDB`)
- **Functions**: `snake_case` (e.g., `parse_date()`, `generate_id()`)
- **Constants**: `UPPER_SNAKE` (e.g., `BASE_URL`, `GROUP_ID`, `_MAPPING_PATH`)
- **Private functions**: Leading underscore (e.g., `_log()`, `_mongo_to_es()`)

## Where to Add New Code

### New Ingestion Stage
- Implementation: `src/backend/ingest/<stage_name>.py`
- Integration: Import in `sync_dou.py` and add to pipeline

### New Search Feature
- MCP tool: `ops/bin/mcp_es_server.py` (add function, decorate with `@mcp.tool()`)
- ES mapping: `src/backend/search/es_index_v1.json` (add fields)
- Indexer: `src/backend/ingest/es_indexer.py` (update `_mongo_to_es()`)

### New Document Field
- Model: `src/backend/data/models/document.py` (add to DouDocument)
- Processor: `src/backend/ingest/dou_processor.py` (extract in `process_xml()`)
- ES mapping: `src/backend/search/es_index_v1.json` (add field definition)
- Indexer: `src/backend/ingest/es_indexer.py` (include in `_mongo_to_es()`)

### New MCP Server
- Implementation: `ops/bin/<server_name>.py` or `.dev/<name>/`
- Configuration: Add to `.mcp.json` under `mcpServers`

### New Utility Script
- Operational: `ops/<script_name>.py`
- Development: `.dev/<script_name>.py`

### Tests
- Location: Co-located with source (e.g., `src/backend/ingest/test_es_indexer.py`)
- Pattern: `test_<module_name>.py`
- Note: Current project has ad-hoc tests in `ops/test_*.py`

## Special Directories

### `.dev/mcp/runs/`
- Purpose: MCP development run artifacts
- Contains: JSON logs, diffs, metrics from AI agent runs
- Generated: Yes (by dev-converge MCP server)
- Committed: Yes (for run history)

### `archive_legacy/`
- Purpose: Deprecated code reference
- Contains: Old implementations with Postgres, workers, web frontend
- Generated: No
- Committed: Yes (for reference only)
- Note: Do not modify; kept for historical context

### `ops/data/`
- Purpose: Runtime data files
- Contains:
  - `dou_catalog_registry.json`: Scraped catalog of DOU ZIPs
  - `ingest_progress.log`: Ingestion progress
- Generated: Partially (registry scraped, log created during runs)
- Committed: Yes

### `src/backend/data/es_sync_cursor.json`
- Purpose: ES sync high-water mark
- Contains: Last indexed MongoDB `_id`
- Generated: Yes (by es_indexer.py)
- Committed: No (in `.gitignore`? No - currently committed)
- Note: Should be in `.gitignore` for multi-instance deployments

## Import Paths

All imports use absolute paths from `src/`:

```python
# Correct
from src.backend.core.config import settings
from src.backend.data.db import MongoDB
from src.backend.data.models.document import DouDocument

# Incorrect (relative imports)
from ..core.config import settings
from .db import MongoDB
```

This enables:
- Running scripts from project root: `python3 sync_dou.py`
- Running modules: `python3 -m src.backend.ingest.es_indexer backfill`

---

*Structure analysis: 2026-03-11*
