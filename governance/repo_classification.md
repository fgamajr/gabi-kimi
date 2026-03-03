# Repository Module Classification

> Generated: 2026-03-03 — Phase 0 State Reconstruction

## Classification Legend

| Status | Meaning |
|--------|---------|
| **ACTIVE** | Called in execution path (CLI, import chain, or pipeline) |
| **SUPPORT** | Imported by ACTIVE modules (utilities, package markers) |
| **GOVERNANCE** | Documentation, specs, or configuration files |
| **DEAD** | No references in code, CLI, or tests |
| **EXPERIMENTAL** | Not integrated into any active pipeline |

---

## Module Classification

### `ingest/` — Bulk XML Ingestion Pipeline

| Module | Status | Rationale |
|--------|--------|-----------|
| `ingest/__init__.py` | SUPPORT | Package marker |
| `ingest/xml_parser.py` | ACTIVE | Core XML→DOUArticle parser; imported by normalizer |
| `ingest/normalizer.py` | ACTIVE | DOUArticle→PG schema transform; bridge to registry_ingest |
| `ingest/zip_downloader.py` | ACTIVE | URL generation + HTTP download for DOU ZIPs |
| `ingest/date_selector.py` | ACTIVE | DateRange utility; imported by zip_downloader |
| `ingest/identity_analyzer.py` | ACTIVE | Identity config loader + hash analysis; imported by registry_ingest |
| `ingest/bulk_pipeline.py` | ACTIVE | Main orchestrator CLI: download→extract→parse→normalize→ingest→seal |

### `commitment/` — CRSS-1 Commitment Scheme

| Module | Status | Rationale |
|--------|--------|-----------|
| `commitment/__init__.py` | SUPPORT | Package marker |
| `commitment/crss1.py` | ACTIVE | Canonical serialization; tested in test_commitment |
| `commitment/tree.py` | ACTIVE | Merkle tree + inclusion proofs; tested |
| `commitment/anchor.py` | ACTIVE | Commitment computation from DB; used by registry_ingest + CLI |
| `commitment/chain.py` | ACTIVE | Append-only anchor chain; used by registry_ingest |
| `commitment/verify.py` | ACTIVE | Independent envelope verifier; used by commitment_cli |

### `dbsync/` — Declarative PostgreSQL Schema Management

| Module | Status | Rationale |
|--------|--------|-----------|
| `dbsync/__init__.py` | SUPPORT | Package marker |
| `dbsync/schema_sync.py` | ACTIVE | CLI for schema plan/apply/verify |
| `dbsync/loader.py` | ACTIVE | YAML→model spec loader |
| `dbsync/planner.py` | ACTIVE | Model spec→desired PG plan |
| `dbsync/introspect.py` | ACTIVE | Live PG catalog introspection |
| `dbsync/differ.py` | ACTIVE | Desired vs existing schema diff |
| `dbsync/executor.py` | ACTIVE | DDL execution in transaction |
| `dbsync/registry_ingest.py` | ACTIVE | SERIALIZABLE CTE ingestion engine + commitment sealing |

### `infra/` — Docker PostgreSQL Appliance

| Module | Status | Rationale |
|--------|--------|-----------|
| `infra/db_control.py` | ACTIVE | Docker container lifecycle |
| `infra/infra_manager.py` | ACTIVE | CLI wrapper for db_control |

### Top-Level Entrypoints

| Module | Status | Rationale |
|--------|--------|-----------|
| `schema_sync.py` | ACTIVE | CLI shim → dbsync.schema_sync.main() |
| `commitment_cli.py` | ACTIVE | CLI for CRSS-1 compute/verify |

### `tests/`

| Module | Status | Rationale |
|--------|--------|-----------|
| `tests/__init__.py` | SUPPORT | Package marker |
| `tests/test_commitment.py` | ACTIVE | 28 pure function tests for CRSS-1 |
| `tests/test_seal_roundtrip.py` | ACTIVE | Integration: ingest→seal→verify roundtrip |

### Configuration & Data

| File | Status | Rationale |
|------|--------|-----------|
| `sources_v3.yaml` | GOVERNANCE | Declarative PG schema definition |
| `sources_v3.identity-test.yaml` | GOVERNANCE | Identity hash strategy definition |
| `requirements.txt` | GOVERNANCE | Python dependencies |
| `AGENTS.md` | GOVERNANCE | Repository guidelines |
| `proofs/` | GOVERNANCE | CRSS-1 anchor chain + golden test vectors |
| `data/inlabs/` | ACTIVE | Downloaded ZIP bundles + manifest |

### `archive_legacy/` — Archived Pre-Consolidation Code

| Directory | Status | Rationale |
|-----------|--------|-----------|
| `archive_legacy/20260303/` | EXPERIMENTAL | Entire legacy crawler/HTML scraping path, archived |

---

## Dependency Graph

```
schema_sync.py ──→ dbsync.schema_sync ──→ dbsync.{loader,planner,introspect,differ,executor}

commitment_cli.py ──→ commitment.{anchor,verify} ──→ commitment.{crss1,tree}

ingest.bulk_pipeline ──→ ingest.zip_downloader ──→ ingest.date_selector
                     ──→ ingest.xml_parser
                     ──→ ingest.normalizer ──→ ingest.xml_parser
                     ──→ dbsync.registry_ingest ──→ commitment.{anchor,chain}
                                                ──→ ingest.identity_analyzer

infra.infra_manager ──→ infra.db_control
```

## Summary

- **22 active Python modules** (non-`__init__`)
- **5 support modules** (`__init__.py` markers)
- **0 dead modules** in active codebase
- **1 archived directory** (`archive_legacy/20260303/`)
- All active modules are wired into the dependency graph
