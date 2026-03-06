> Last verified: 2026-03-06

# Documentation Reconciliation

This file summarizes the documentation reconciliation pass against the current repository state.

## Scope

Updated in place:

- `README.md`
- `AGENTS.md`
- `AUTOMATION_README.md`
- `QUICK_REFERENCE.md`
- `ARCHITECTURE_DIAGRAMS.md`
- `docs/runbooks/PIPELINE.md`
- `CLEANUP_AUDIT.md`
- `QWEN.md`
- `HANDOVER.md`
- `CODEX-ELASTIC-PLAN.MD`
- `CODEX-PLAN-REDIS.md`
- `codex-plano-rag.md`
- `COMPLETE_IMPLEMENTATION.md`
- `IMPLEMENTATION_SUMMARY.md`
- `QMD_MCP_SETUP.md`
- `antigravity.md`
- `docs/DB_APPLIANCE_OPERATOR_HANDBOOK.md`
- `docs/INLabs_DOU_XML_Specification.md`
- `docs/INLabs_XML_Analysis_Summary.md`
- `docs/zip_structure_reference.md`
- `governance/dead_code_report.md`
- `governance/refactor_plan.md`
- `governance/repo_classification.md`
- `.env.example`
- `config/pipeline_config.example.yaml`
- `config/production.yaml`
- `config/sources/sources_v3.yaml`
- `config/sources/sources_v3.identity-test.yaml`
- `ops/local/docker-compose.yml`

## Reconciliation Summary

### Main project docs

| File | Change summary | Rationale |
|---|---|---|
| `README.md` | Rewritten around the current ingest, retrieval, MCP, and setup flow. | The old overview no longer matched the active code paths. |
| `AGENTS.md` | Updated project overview, search stack, scripts section, and env block. | Agent guidance referenced outdated env names and incomplete search architecture. |
| `AUTOMATION_README.md` | Rewritten to distinguish `sync_pipeline`, `bulk_pipeline`, and orchestrator automation. | The automation story had drifted from the actual modules on disk. |
| `QUICK_REFERENCE.md` | Rewritten with commands that work against the current repo. | Previous quickstart commands were stale or incomplete. |
| `ARCHITECTURE_DIAGRAMS.md` | Replaced with current ASCII diagrams for ingest, indexing, hybrid retrieval, and serving. | The old diagrams no longer described the live topology. |
| `docs/runbooks/PIPELINE.md` | Added verification marker and aligned env/config examples with current code. | Runbook needed to match the real stages and active flags. |
| `CLEANUP_AUDIT.md` | Added verification marker. | Audit is now part of the current documentation set. |
| `docs/meta/DOCS_RECONCILIATION.md` | Added. | Provides an explicit ledger of what changed and why. |

### Runtime and integration docs

| File | Change summary | Rationale |
|---|---|---|
| `QWEN.md` | Rewritten as a narrow note for the optional `POST /api/chat` Qwen integration. | It previously read like a general project guide and used obsolete setup steps. |
| `docs/DB_APPLIANCE_OPERATOR_HANDBOOK.md` | Updated to reflect PostgreSQL + Elasticsearch + Redis under `ops/local/docker-compose.yml`. | The handbook was effectively PostgreSQL-only while the stack is now broader. |
| `ops/local/docker-compose.yml` | Added a verification marker comment. | Config docs now carry the same reconciliation marker as markdown docs. |

### Reference/spec docs

| File | Change summary | Rationale |
|---|---|---|
| `docs/INLabs_DOU_XML_Specification.md` | Added verification marker and clarified that it is a technical reference, not an operator guide. | Prevents this file from being mistaken for the pipeline runbook. |
| `docs/INLabs_XML_Analysis_Summary.md` | Added verification marker and narrowed scope to sample-based analysis. | Keeps the document useful without overstating it as canonical spec. |
| `docs/zip_structure_reference.md` | Added verification marker and linked it back to the active downloader. | Needed a clear bridge from analysis doc to implementation. |

### Historical plan/status docs

| File | Change summary | Rationale |
|---|---|---|
| `HANDOVER.md` | Replaced with a short historical snapshot note. | Original content described a one-off machine and branch state. |
| `CODEX-ELASTIC-PLAN.MD` | Replaced with a historical migration summary pointing to current docs. | The migration is largely implemented, so the old phased plan was misleading. |
| `CODEX-PLAN-REDIS.md` | Replaced with a historical snapshot note. | Redis-backed query assist is already wired in code. |
| `codex-plano-rag.md` | Reduced to a backlog snapshot with current implementation status. | Keeps useful RAG planning context without masquerading as live docs. |
| `COMPLETE_IMPLEMENTATION.md` | Replaced with an obsolete snapshot marker. | Previous “complete” claims no longer match the project state. |
| `IMPLEMENTATION_SUMMARY.md` | Replaced with an obsolete snapshot marker. | Duplicated and contradicted the current runbooks. |
| `QMD_MCP_SETUP.md` | Replaced with an obsolete external-tool note. | `qmd` is not part of the active repo architecture. |
| `antigravity.md` | Replaced with a duplicate-guidance marker pointing to `AGENTS.md`. | The repository should have one primary agent guide. |

### Governance docs

| File | Change summary | Rationale |
|---|---|---|
| `governance/dead_code_report.md` | Reduced to a historical snapshot pointer to `CLEANUP_AUDIT.md`. | The newer cleanup audit supersedes the earlier narrow report. |
| `governance/refactor_plan.md` | Reduced to a historical snapshot pointer to current architecture docs. | The plan is no longer the current operating state. |
| `governance/repo_classification.md` | Reduced to a historical snapshot pointer to `CLEANUP_AUDIT.md`. | The recursive cleanup audit is the more current classification source. |

### Config and schema docs

| File | Change summary | Rationale |
|---|---|---|
| `.env.example` | Rewritten to include only env vars actually consumed by current code. | Deprecated flags and stale names had accumulated. |
| `config/pipeline_config.example.yaml` | Reduced to only fields parsed by `src/backend/ingest/orchestrator.py`. | The example listed unsupported fields. |
| `config/production.yaml` | Reduced to only fields parsed by `src/backend/ingest/orchestrator.py`. | Same mismatch as the example config. |
| `config/sources/sources_v3.yaml` | Added verification marker comment. | Schema source is part of the documented operator surface. |
| `config/sources/sources_v3.identity-test.yaml` | Added verification marker comment. | Same reason as above. |

## Obsolete docs flagged for quarantine

These were not deleted, but they should be moved out of the active doc surface in a future cleanup pass:

- `HANDOVER.md`
- `COMPLETE_IMPLEMENTATION.md`
- `IMPLEMENTATION_SUMMARY.md`
- `QMD_MCP_SETUP.md`
- `antigravity.md`
- `CODEX-ELASTIC-PLAN.MD`
- `CODEX-PLAN-REDIS.md`
- `governance/dead_code_report.md`
- `governance/refactor_plan.md`
- `governance/repo_classification.md`

## Validation notes

- Updated docs now carry `Last verified: 2026-03-06`.
- Removed stale references to old env flags such as `SEARCH_ANALYTICS_ENABLED`, `PG_DB`, and `USE_CONTEXTUAL_EMBEDDINGS`.
- Historical documents that could not be kept accurate without carrying stale references were collapsed into explicit snapshot markers instead.
