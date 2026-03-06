# Full-Tree Cleanup Audit

> Last verified: 2026-03-06

Scope: `/home/parallels/dev/gabi-kimi`, recursively.

Audit policy:

- `ACTIVE`: imported, referenced, or invoked by the current code, config, tests, or operator scripts.
- `DEPRECATED`: stale output, cache, abandoned experiment, sidecar metadata, or unrelated leftover.
- `DUPLICATE`: alternate copy/wrapper/symlink/helper that overlaps an already active artifact.
- `UNKNOWN`: human documentation, governance, deployment support, or repo metadata that is not in the active runtime path and needs owner judgment.

High-cardinality subtree policy:

- Some trees are too large and low-signal to enumerate line-by-line in Markdown without producing a useless report.
- For these trees, children inherit the parent classification unless explicitly broken out below.
- This policy is applied to: `.git/**`, `.venv/**`, `.venv-macos/**`, `.trash_frontend/**`, `archive_legacy/**`, and `data/inlabs/**`.

## Global Summary

| Folder | Status mix | Notes |
|---|---|---|
| `.` root files | ACTIVE + DEPRECATED + DUPLICATE + UNKNOWN | Mixed runtime entrypoints, docs, screenshots, and helper notes |
| `.git/` | UNKNOWN | Opaque VCS metadata subtree |
| `.vscode/` | ACTIVE | Workspace MCP config |
| `.venv/` | ACTIVE | Current local Python environment |
| `.venv-macos/` | DEPRECATED | Alternate host-specific environment, not used on this machine |
| `.pytest_cache/` | DEPRECATED | Test cache only |
| `__pycache__/` and `*/__pycache__/` | DEPRECATED | Regenerable Python bytecode caches |
| `.trash_frontend/` | DEPRECATED | Soft-deleted frontend experiments and build outputs |
| `archive_legacy/` | DEPRECATED | Archived pre-consolidation codebase |
| `commitment/` | ACTIVE | CRSS-1 core |
| `config/` | ACTIVE | Operator and systemd config |
| `data/` | ACTIVE + DEPRECATED + DUPLICATE | Source assets and cursor state, plus experimental leftovers |
| `dbsync/` | ACTIVE | Declarative schema and ingestion engine |
| `deploy/` | ACTIVE | Deployment artifacts for Fly targets |
| `docs/` | UNKNOWN | Reference docs/specs |
| `governance/` | UNKNOWN | Audit and refactor documents |
| `infra/` | ACTIVE | Local Docker infra controls |
| `ingest/` | ACTIVE + DEPRECATED + UNKNOWN | Main pipeline plus a few exploratory helpers |
| `proofs/` | ACTIVE | Commitment vectors and bootstrap anchor |
| `scripts/` | ACTIVE + DEPRECATED + DUPLICATE + UNKNOWN | Operational scripts, caches, wrapper, and one-off repair tool |
| `search/` | ACTIVE + DEPRECATED | Search adapters and stale sidecars/caches |
| `tests/` | ACTIVE + DEPRECATED | Test scripts, fixtures, and caches |
| `web/` | ACTIVE + DUPLICATE | Current SPA plus unused alternate integrations |

## Root Files

Summary: `ACTIVE 10 | DEPRECATED 5 | DUPLICATE 2 | UNKNOWN 12`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `.env` | file | ACTIVE | `web_server.py`, `mcp_es_server.py`, `search/adapters.py` | Current runtime configuration for DB, ES, Redis, and embeddings. |
| `.env.example` | file | ACTIVE | `README.md`, `PIPELINE.md` | Canonical local config template. |
| `.gitignore` | file | UNKNOWN | none | Repo hygiene only; not executed. |
| `.mcp.json` | file | ACTIVE | MCP clients | Project-scoped MCP server configuration for `gabi-es`. |
| `AGENTS.md` | file | UNKNOWN | none | Agent policy, not runtime code. |
| `ARCHITECTURE_DIAGRAMS.md` | file | UNKNOWN | none | Architecture notes useful to humans only. |
| `AUTOMATION_README.md` | file | UNKNOWN | none | Operator documentation for the automation/orchestrator path. |
| `CODEX-ELASTIC-PLAN.MD` | file | UNKNOWN | `README.md`, `AUTOMATION_README.md` | Planning document still referenced in docs, but not runtime. |
| `CODEX-PLAN-REDIS.md` | file | UNKNOWN | none | Feature plan, not active execution. |
| `codex-plano-rag.md` | file | UNKNOWN | none | Current planning artifact for RAG phases. |
| `commitment_cli.py` | file | ACTIVE | operator CLI | Active CRSS-1 CLI entrypoint. |
| `COMPLETE_IMPLEMENTATION.md` | file | DUPLICATE | `AUTOMATION_README.md` | Overlaps `IMPLEMENTATION_SUMMARY.md` and automation docs. |
| `HANDOVER.md` | file | UNKNOWN | none | Historical/operator context, not runtime. |
| `IMPLEMENTATION_SUMMARY.md` | file | DUPLICATE | `COMPLETE_IMPLEMENTATION.md` | Near-duplicate implementation recap. |
| `mcp_es_server.py` | file | ACTIVE | `.mcp.json`, `.vscode/mcp.json` | Active MCP server for ES/hybrid retrieval. |
| `mcp_server.py` | file | ACTIVE | operator CLI | Alternate MCP server entrypoint still available. |
| `PIPELINE.md` | file | UNKNOWN | none | New runbook documentation, not executable. |
| `CLEANUP_AUDIT.md` | file | UNKNOWN | none | Audit document only. |
| `QMD_MCP_SETUP.md` | file | DEPRECATED | none | Documents a different MCP toolchain unrelated to GABI runtime. |
| `QUICK_REFERENCE.md` | file | UNKNOWN | none | Human quick reference, not runtime code. |
| `QWEN.md` | file | UNKNOWN | none | Assistant/project context note, not runtime code. |
| `README.md` | file | UNKNOWN | none | Primary repo documentation. |
| `requirements.txt` | file | ACTIVE | `.venv`, deploy/build steps | Root Python dependency set. |
| `schema_sync.py` | file | ACTIVE | operator CLI | Active shim to `dbsync.schema_sync`. |
| `sources_v3.identity-test.yaml` | file | ACTIVE | `tests/test_seal_roundtrip.py`, `scripts/deploy.sh`, `config/pipeline_config.example.yaml` | Identity contract for registry ingest and deployment. |
| `sources_v3.yaml` | file | ACTIVE | `schema_sync.py`, `dbsync/loader.py`, `config/pipeline_config.example.yaml` | Canonical declarative source schema manifest. |
| `antigravity.md` | file | DEPRECATED | none | Duplicates project/agent guidance already covered by `AGENTS.md` and `README.md`. |
| `Captura de Tela 2026-03-05 às 15.08.48.png` | file | DEPRECATED | none | Ad-hoc discussion screenshot, not used by code. |
| `image copy.png` | file | DEPRECATED | none | Ad-hoc discussion screenshot, not used by code. |
| `image.png` | file | DEPRECATED | none | Ad-hoc discussion screenshot, not used by code. |
| `instructor_a46l9irobhg0f5webscixp0bs_public_1748542336_07_-_007_-_A_Multi-Index_Rag_Pipeline_05.1748542336309.jpg` | file | DEPRECATED | none | External slide capture used only during discussion. |
| `instructor_a46l9irobhg0f5webscixp0bs_public_1748542336_07_-_007_-_A_Multi-Index_Rag_Pipeline_06.1748542336704.jpg` | file | DEPRECATED | none | External slide capture used only during discussion. |
| `instructor_a46l9irobhg0f5webscixp0bs_public_1748542337_07_-_007_-_A_Multi-Index_Rag_Pipeline_08.1748542337402.jpg` | file | DEPRECATED | none | External slide capture used only during discussion. |
| `instructor_a46l9irobhg0f5webscixp0bs_public_1748542337_07_-_007_-_A_Multi-Index_Rag_Pipeline_18.1748542337748.jpg` | file | DEPRECATED | none | External slide capture used only during discussion. |
| `instructor_a46l9irobhg0f5webscixp0bs_public_1748542338_07_-_007_-_A_Multi-Index_Rag_Pipeline_19.1748542338538.jpg` | file | DEPRECATED | none | External slide capture used only during discussion. |

## Hidden and Generated Trees

### `.git/`

Summary: `UNKNOWN subtree`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `.git/` | dir | UNKNOWN | git tooling | Version-control metadata; not part of runtime. |
| `.git/**` | subtree | UNKNOWN | git tooling | Opaque VCS internals; intentionally not quarantined. |

### `.vscode/`

Summary: `ACTIVE 1`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `.vscode/` | dir | ACTIVE | VS Code MCP host | Workspace editor config in active use. |
| `.vscode/mcp.json` | file | ACTIVE | VS Code chat/tools | Active MCP wiring for `gabi-es`. |

### `.venv/`

Summary: `ACTIVE subtree (4202 files, 508 dirs)`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `.venv/` | dir | ACTIVE | operator shell, `.vscode/mcp.json` | Current local Python environment used by commands and MCP launchers. |
| `.venv/**` | subtree | ACTIVE | operator shell, `.vscode/mcp.json` | Dependency tree required by the current machine. |

### `.venv-macos/`

Summary: `DEPRECATED subtree (5709 files, 425 dirs)`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `.venv-macos/` | dir | DEPRECATED | none | Alternate host-specific environment not used on this Linux machine. |
| `.venv-macos/**` | subtree | DEPRECATED | none | Entire macOS virtualenv tree is redundant locally. |

### Cache and Sidecar Trees

Summary: `DEPRECATED caches/sidecars`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `.pytest_cache/` | dir | DEPRECATED | none | Pytest cache only; script-based tests do not need it. |
| `.pytest_cache/**` | subtree | DEPRECATED | none | Regenerable test cache. |
| `__pycache__/` | dir | DEPRECATED | none | Root bytecode cache only. |
| `*/__pycache__/` | subtree | DEPRECATED | none | All bytecode caches are regenerable. |
| `._*` | subtree pattern | DEPRECATED | none | AppleDouble sidecars are metadata artifacts, not project assets. |

### `.trash_frontend/`

Summary: `DEPRECATED subtree (24054 files, 2218 dirs)`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `.trash_frontend/` | dir | DEPRECATED | none | Explicit trash area for superseded frontend experiments. |
| `.trash_frontend/dou_new_20260305_144454/` | dir | DEPRECATED | none | Old Next.js frontend plus build outputs and `node_modules`. |
| `.trash_frontend/web_20260305_144454/` | dir | DEPRECATED | none | Previous static web snapshot. |
| `.trash_frontend/**` | subtree | DEPRECATED | none | Entire subtree is outside the current served frontend path. |

### `archive_legacy/`

Summary: `DEPRECATED subtree (181 files, 24 dirs)`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `archive_legacy/` | dir | DEPRECATED | `governance/dead_code_report.md` | Archived legacy code explicitly marked non-active by governance. |
| `archive_legacy/20260303/extract_test.py` | file | DEPRECATED | none | Archived experimental script. |
| `archive_legacy/20260303/harvest_cli.py` | file | DEPRECATED | none | Archived legacy ingestion CLI. |
| `archive_legacy/20260303/historical_validate.py` | file | DEPRECATED | none | Archived validation helper. |
| `archive_legacy/20260303/run_mock_crawl.py` | file | DEPRECATED | none | Archived crawler harness. |
| `archive_legacy/**` | subtree | DEPRECATED | none | Entire legacy tree is superseded by `ingest/` and current pipeline code. |

## `commitment/`

Summary: `ACTIVE 6 | DEPRECATED 1`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `commitment/` | dir | ACTIVE | `dbsync/registry_ingest.py`, `commitment_cli.py`, tests | Core CRSS-1 package. |
| `commitment/__init__.py` | file | ACTIVE | package import chain | Package marker for active module imports. |
| `commitment/anchor.py` | file | ACTIVE | `dbsync/registry_ingest.py`, `commitment_cli.py` | Computes commitments from DB state. |
| `commitment/chain.py` | file | ACTIVE | `dbsync/registry_ingest.py` | Maintains append-only anchor chain. |
| `commitment/crss1.py` | file | ACTIVE | `commitment/anchor.py`, tests | Canonical serialization core. |
| `commitment/tree.py` | file | ACTIVE | `commitment/anchor.py`, tests | Merkle tree and proofs. |
| `commitment/verify.py` | file | ACTIVE | `commitment_cli.py`, tests | Independent proof verification. |
| `commitment/__pycache__/` | dir | DEPRECATED | none | Bytecode cache only. |

## `config/`

Summary: `ACTIVE 4`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `config/` | dir | ACTIVE | `ingest/orchestrator.py`, `scripts/deploy.sh` | Active operator/deploy config folder. |
| `config/pipeline_config.example.yaml` | file | ACTIVE | `ingest/orchestrator.py`, `AUTOMATION_README.md` | Template for orchestrator config. |
| `config/production.yaml` | file | ACTIVE | `ingest/orchestrator.py`, `scripts/deploy.sh` | Concrete production config example. |
| `config/systemd/gabi-ingest.service` | file | ACTIVE | `scripts/deploy.sh`, `AUTOMATION_README.md` | Systemd unit for orchestrator-based automation. |
| `config/systemd/gabi-ingest.timer` | file | ACTIVE | `scripts/deploy.sh`, `AUTOMATION_README.md` | Timer for orchestrator-based automation. |

## `data/`

Summary: `ACTIVE 7 | DEPRECATED 2 | DUPLICATE 2`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `data/` | dir | ACTIVE | multiple ingest/index scripts | Current operational data root. |
| `data/dou_catalog_registry.json` | file | ACTIVE | `ingest/catalog_scraper.py`, `ingest/sync_pipeline.py`, `ingest/zip_downloader.py` | Current source-of-truth monthly catalog registry. |
| `data/chunks_backfill_cursor.json` | file | ACTIVE | `scripts/backfill_chunks.py` | Default chunk-backfill cursor path. |
| `data/es_chunks_sync_cursor.json` | file | ACTIVE | `ingest/embedding_pipeline.py` | Default embedding sync cursor path. |
| `data/es_chunks_openai_cursor_384.json` | file | ACTIVE | current operator commands, `PIPELINE.md` | Active 384-dim vector backfill cursor. |
| `data/es_sync_cursor.json` | file | ACTIVE | `ingest/es_indexer.py` | Default Elasticsearch document sync cursor. |
| `data/inlabs/` | dir | ACTIVE | `ingest/zip_downloader.py`, `ingest/dou_ingest.py`, `ingest/sync_pipeline.py` | Live source asset store. |
| `data/inlabs/manifest.json` | file | ACTIVE | `ingest/zip_downloader.py` | Downloader/extraction manifest. |
| `data/inlabs/**` | subtree | ACTIVE | `ingest/zip_downloader.py`, `ingest/dou_ingest.py`, `ingest/bulk_pipeline.py` | 299,033 ZIP/XML source artifacts used by current ingestion flows. |
| `data/chunks_backfill_cursor_2002_foreground.json` | file | DEPRECATED | none | One-off experiment cursor from a foreground backfill run. |
| `data/chunks_backfill_cursor_bgtest.json` | file | DEPRECATED | none | One-off background test cursor. |
| `data/chunks_backfill_cursor_debug.json` | file | DEPRECATED | none | One-off debug cursor state. |
| `data/inlabs_2002_only/` | dir | DUPLICATE | none | Symlink mirror of 2002 ZIPs already present under `data/inlabs/`. |
| `data/inlabs_2002_only/**` | subtree | DUPLICATE | none | 36 symlinked duplicates of active source files. |

## `dbsync/`

Summary: `ACTIVE 10 | DEPRECATED 1`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `dbsync/` | dir | ACTIVE | `schema_sync.py`, `ingest/bulk_pipeline.py`, `ingest/bm25_indexer.py` | Active schema and ingestion engine package. |
| `dbsync/__init__.py` | file | ACTIVE | package import chain | Package marker for active imports. |
| `dbsync/bm25_schema.sql` | file | ACTIVE | `ingest/bm25_indexer.py` | Declares BM25 views/functions. |
| `dbsync/differ.py` | file | ACTIVE | `dbsync/schema_sync.py` | Schema diff logic. |
| `dbsync/dou_schema.sql` | file | ACTIVE | operator setup, `AGENTS.md`, `README.md` | Core operational schema, including `dou.document_chunk`. |
| `dbsync/download_registry_schema.sql` | file | ACTIVE | `scripts/deploy.sh`, `AUTOMATION_README.md` | Automation/download registry schema for orchestrator path. |
| `dbsync/executor.py` | file | ACTIVE | `dbsync/schema_sync.py` | Applies planned DDL. |
| `dbsync/introspect.py` | file | ACTIVE | `dbsync/schema_sync.py` | Reads live PG catalog. |
| `dbsync/loader.py` | file | ACTIVE | `dbsync/schema_sync.py` | Loads YAML model DSL. |
| `dbsync/planner.py` | file | ACTIVE | `dbsync/schema_sync.py` | Builds desired schema plans. |
| `dbsync/registry_ingest.py` | file | ACTIVE | `ingest/bulk_pipeline.py`, tests | Registry ingest/seal path. |
| `dbsync/registry_schema.sql` | file | ACTIVE | operator setup, tests | Append-only registry schema. |
| `dbsync/schema_sync.py` | file | ACTIVE | `schema_sync.py` | Main schema-sync CLI implementation. |
| `dbsync/__pycache__/` | dir | DEPRECATED | none | Bytecode cache only. |

## `deploy/`

Summary: `ACTIVE 7`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `deploy/` | dir | ACTIVE | operator deployment workflows | Active deployment support directory. |
| `deploy/postgres/Dockerfile` | file | ACTIVE | Fly/Postgres deploy | Active image build for hosted PostgreSQL. |
| `deploy/postgres/fly.toml` | file | ACTIVE | Fly/Postgres deploy | Active Fly manifest for DB deployment. |
| `deploy/postgres/pg_hba.conf` | file | ACTIVE | `deploy/postgres/Dockerfile` | Runtime auth config for deployed DB. |
| `deploy/postgres/postgresql.conf` | file | ACTIVE | `deploy/postgres/Dockerfile` | Runtime tuning for deployed DB. |
| `deploy/web/Dockerfile` | file | ACTIVE | Fly/Web deploy | Active image build for web server deployment. |
| `deploy/web/fly.toml` | file | ACTIVE | Fly/Web deploy | Active Fly manifest for web deployment. |
| `deploy/web/requirements.txt` | file | ACTIVE | `deploy/web/Dockerfile` | Container-specific dependency set for web image. |

## `docs/`

Summary: `UNKNOWN 5`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `docs/` | dir | UNKNOWN | none | Human reference docs only. |
| `docs/DB_APPLIANCE_OPERATOR_HANDBOOK.md` | file | UNKNOWN | none | Useful operator reference, not runtime. |
| `docs/INLabs_DOU_XML_Specification.md` | file | UNKNOWN | `docs/INLabs_XML_Analysis_Summary.md` | Source-format reference doc. |
| `docs/INLabs_XML_Analysis_Summary.md` | file | UNKNOWN | none | Analysis notes, not runtime. |
| `docs/xml_schema_reference.json` | file | UNKNOWN | none | Reference artifact only. |
| `docs/zip_structure_reference.md` | file | UNKNOWN | none | Reference doc for ZIP contents. |

## `governance/`

Summary: `UNKNOWN 3`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `governance/` | dir | UNKNOWN | none | Human audit/governance folder only. |
| `governance/dead_code_report.md` | file | UNKNOWN | none | Reference audit document. |
| `governance/refactor_plan.md` | file | UNKNOWN | none | Planning doc, not runtime. |
| `governance/repo_classification.md` | file | UNKNOWN | none | Static classification doc, not runtime. |

## `infra/`

Summary: `ACTIVE 3 | DEPRECATED 1`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `infra/` | dir | ACTIVE | operator setup | Local infra control package. |
| `infra/db_control.py` | file | ACTIVE | `infra/infra_manager.py` | Docker lifecycle logic. |
| `infra/docker-compose.yml` | file | ACTIVE | `infra/infra_manager.py` | Active local stack definition. |
| `infra/infra_manager.py` | file | ACTIVE | operator CLI | Active local infra entrypoint. |
| `infra/__pycache__/` | dir | DEPRECATED | none | Bytecode cache only. |

## `ingest/`

Summary: `ACTIVE 19 | DEPRECATED 2 | UNKNOWN 3`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `ingest/` | dir | ACTIVE | root entrypoints, scripts, tests | Main ingestion and indexing package. |
| `ingest/__init__.py` | file | ACTIVE | package import chain | Package marker. |
| `ingest/auto_discovery.py` | file | ACTIVE | `ingest/orchestrator.py`, docs | Discovery CLI used by automation path. |
| `ingest/bm25_indexer.py` | file | ACTIVE | operator CLI, `scripts/daily_sync.sh` | Active BM25 build/refresh/search tool. |
| `ingest/bulk_pipeline.py` | file | ACTIVE | operator CLI, `ingest/orchestrator.py`, tests | Registry/bulk ingestion path. |
| `ingest/catalog_scraper.py` | file | ACTIVE | `ingest/sync_pipeline.py`, operator CLI | Active catalog refresh tool. |
| `ingest/chunker.py` | file | ACTIVE | `scripts/backfill_chunks.py` | Active chunk generation for vector/hybrid retrieval. |
| `ingest/date_selector.py` | file | ACTIVE | `ingest/bulk_pipeline.py`, `ingest/orchestrator.py`, `ingest/zip_downloader.py` | Shared date-range logic. |
| `ingest/discovery_registry.py` | file | ACTIVE | `ingest/auto_discovery.py`, `scripts/deploy.sh` | Backing store for orchestrator discovery flow. |
| `ingest/dou_ingest.py` | file | ACTIVE | `ingest/sync_pipeline.py`, tests | Active operational ingest into `dou.*`. |
| `ingest/embedding_pipeline.py` | file | ACTIVE | operator CLI, `search/adapters.py` | Active vector index pipeline. |
| `ingest/es_indexer.py` | file | ACTIVE | operator CLI | Active Elasticsearch document indexer. |
| `ingest/html_extractor.py` | file | ACTIVE | `ingest/dou_ingest.py` | Active signatures/media/reference extraction. |
| `ingest/identity_analyzer.py` | file | ACTIVE | `dbsync/registry_ingest.py` | Active identity/hash support. |
| `ingest/multipart_merger.py` | file | ACTIVE | `ingest/dou_ingest.py` | Active multipart article merge logic. |
| `ingest/normalizer.py` | file | ACTIVE | `ingest/bulk_pipeline.py` | Active normalization bridge for registry ingest. |
| `ingest/orchestrator.py` | file | ACTIVE | `config/systemd/gabi-ingest.service`, docs | Active automation/orchestrator path. |
| `ingest/sync_pipeline.py` | file | ACTIVE | operator CLI, `scripts/daily_sync.sh` | Active operational sync path for `dou.*`. |
| `ingest/xml_parser.py` | file | ACTIVE | `ingest/dou_ingest.py`, `ingest/bulk_pipeline.py`, tests | Active XML parser. |
| `ingest/zip_downloader.py` | file | ACTIVE | `ingest/bulk_pipeline.py`, `ingest/sync_pipeline.py` | Active download and extraction helper. |
| `ingest/discovery_probe.py` | file | UNKNOWN | none | Exploratory diagnostic CLI, not in the active runbook. |
| `ingest/media_backfill.py` | file | UNKNOWN | none | Manual remediation utility, not in active pipeline. |
| `ingest/sample_download.py` | file | UNKNOWN | none | Sampling/analysis helper, not in active pipeline. |
| `ingest/._embedding_pipeline.py` | file | DEPRECATED | none | AppleDouble sidecar for `embedding_pipeline.py`. |
| `ingest/__pycache__/` | dir | DEPRECATED | none | Bytecode cache only. |

## `proofs/`

Summary: `ACTIVE 4`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `proofs/` | dir | ACTIVE | tests, commitment workflows | Active proof/vectors directory. |
| `proofs/anchors/0000-bootstrap.json` | file | ACTIVE | `commitment/chain.py` | Bootstrap anchor chain state. |
| `proofs/anchors/0000-bootstrap.records` | file | ACTIVE | `commitment/chain.py` | Bootstrap anchor records. |
| `proofs/crss1-golden/canonical_records.txt` | file | ACTIVE | `tests/test_commitment.py` | Golden test vector. |
| `proofs/crss1-golden/envelope.json` | file | ACTIVE | `tests/test_commitment.py`, `tests/test_seal_roundtrip.py` | Golden commitment envelope. |

## `scripts/`

Summary: `ACTIVE 5 | DEPRECATED 1 | DUPLICATE 1 | UNKNOWN 1`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `scripts/` | dir | ACTIVE | operator workflows | Operational script directory. |
| `scripts/backfill_chunks.py` | file | ACTIVE | operator CLI, `PIPELINE.md` | Active chunk backfill for `dou.document_chunk`. |
| `scripts/backfill_embeddings.py` | file | DUPLICATE | `codex-plano-rag.md` | Thin wrapper around `ingest.embedding_pipeline`, functionally redundant. |
| `scripts/daily_sync.sh` | file | ACTIVE | `README.md`, `scripts/gabi-sync@.service` | Current daily sync automation for `sync_pipeline` + BM25 refresh. |
| `scripts/deploy.sh` | file | ACTIVE | operator deployment | Active deployment helper. |
| `scripts/gabi-sync@.service` | file | ACTIVE | systemd/local automation | Local service wrapper around `daily_sync.sh`. |
| `scripts/gabi-sync@.timer` | file | ACTIVE | systemd/local automation | Timer wrapper around `gabi-sync@.service`. |
| `scripts/reprocess_2002.py` | file | UNKNOWN | none | One-off repair utility, not in the current standard pipeline. |
| `scripts/__pycache__/` | dir | DEPRECATED | none | Bytecode cache only. |

## `search/`

Summary: `ACTIVE 5 | DEPRECATED 2`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `search/` | dir | ACTIVE | `web_server.py`, `mcp_es_server.py` | Active search package. |
| `search/__init__.py` | file | ACTIVE | package import chain | Package marker. |
| `search/adapters.py` | file | ACTIVE | `web_server.py`, `mcp_es_server.py` | Core PG/ES/hybrid retrieval adapters. |
| `search/es_chunks_v1.json` | file | ACTIVE | `ingest/embedding_pipeline.py` | Active chunk/vector index mapping. |
| `search/es_index_v1.json` | file | ACTIVE | `ingest/es_indexer.py` | Active document index mapping. |
| `search/redis_signals.py` | file | ACTIVE | `web_server.py` | Active Redis-backed query-assist layer. |
| `search/._adapters.py` | file | DEPRECATED | none | AppleDouble sidecar for `adapters.py`. |
| `search/__pycache__/` | dir | DEPRECATED | none | Bytecode cache only. |

## `tests/`

Summary: `ACTIVE 8 | DEPRECATED 1`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `tests/` | dir | ACTIVE | operator validation | Active script-based test suite. |
| `tests/__init__.py` | file | ACTIVE | package import chain | Package marker. |
| `tests/test_bulk_pipeline.py` | file | ACTIVE | operator validation | Validates bulk pipeline behavior. |
| `tests/test_commitment.py` | file | ACTIVE | operator validation | Validates CRSS-1 core. |
| `tests/test_dou_ingest.py` | file | ACTIVE | operator validation | Validates `dou.*` ingest path. |
| `tests/test_seal_roundtrip.py` | file | ACTIVE | operator validation | Validates ingest + seal roundtrip. |
| `tests/test_search_adapters.py` | file | ACTIVE | operator validation | Validates ES/hybrid retrieval behavior. |
| `tests/fixtures/xml_samples/` | dir | ACTIVE | `tests/test_dou_ingest.py`, `README.md`, `AGENTS.md` | Active XML fixtures for parser/ingest checks. |
| `tests/fixtures/xml_samples/*.xml` | subtree | ACTIVE | `tests/test_dou_ingest.py`, `README.md` | Real XML fixture corpus used by tests and manual parse checks. |
| `tests/__pycache__/` | dir | DEPRECATED | none | Bytecode cache only. |

## `web/`

Summary: `ACTIVE 1 | DUPLICATE 5`

| Path | Type | Status | referenced_by | Justification |
|---|---|---|---|---|
| `web/` | dir | ACTIVE | `web_server.py` | Static frontend directory currently served by the API server. |
| `web/index.html` | file | ACTIVE | `web_server.py`, `README.md` | Current SPA entrypoint. |
| `web/index-with-viewer.html` | file | DUPLICATE | none | Alternate page variant duplicating `index.html` plus viewer ideas, not served. |
| `web/document-viewer.html` | file | DUPLICATE | none | Standalone viewer fragment overlapping current frontend behavior. |
| `web/integration_html.html` | file | DUPLICATE | none | Integration helper markup not referenced by the served app. |
| `web/integration_layer.js` | file | DUPLICATE | none | Enhancement layer not loaded by `index.html`. |
| `web/integration_styles.css` | file | DUPLICATE | none | Style helper not loaded by `index.html`. |
