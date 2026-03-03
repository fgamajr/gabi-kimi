# Refactor Plan — Bulk-Data-First Architecture

> Generated: 2026-03-03 — Phase 2 Architecture Simplification

## Motivation

Discovery of the public Liferay document library endpoint at `in.gov.br/documents/`
eliminates the need for HTML scraping, authenticated APIs, and JavaScript token
extraction. ZIP bundles containing structured XML are available per section per day
via deterministic URLs.

This reduces pipeline complexity by ~70% compared to the prior HTML scraping path.

## Target Directory Structure

```
gabi-kimi/
├── ingest/                        # Bulk XML ingestion pipeline
│   ├── __init__.py
│   ├── bulk_pipeline.py           # NEW: Main orchestrator CLI
│   ├── xml_parser.py              # Parse INLabs DOU XML → DOUArticle
│   ├── zip_downloader.py          # EXPANDED: URL gen + HTTP download + extraction
│   ├── normalizer.py              # EXPANDED: DOUArticle → registry record bridge
│   ├── date_selector.py           # DateRange utility
│   └── identity_analyzer.py       # Identity config + hash analysis
│
├── commitment/                    # CRSS-1 commitment scheme (UNTOUCHED)
│   ├── __init__.py
│   ├── crss1.py
│   ├── tree.py
│   ├── anchor.py
│   ├── chain.py
│   └── verify.py
│
├── dbsync/                        # PostgreSQL schema management
│   ├── __init__.py
│   ├── schema_sync.py
│   ├── loader.py
│   ├── planner.py
│   ├── introspect.py
│   ├── differ.py
│   ├── executor.py
│   ├── registry_ingest.py         # EXPANDED: accept direct records from bulk pipeline
│   └── registry_schema.sql
│
├── infra/                         # Docker PostgreSQL appliance
│   ├── db_control.py
│   ├── docker-compose.yml
│   └── infra_manager.py
│
├── tests/                         # Test suite
│   ├── __init__.py
│   ├── test_commitment.py
│   ├── test_seal_roundtrip.py
│   ├── test_bulk_pipeline.py      # NEW: bulk pipeline tests
│   └── fixtures/xml_samples/
│
├── data/inlabs/                   # Downloaded ZIP bundles + manifest
├── proofs/                        # CRSS-1 anchors + golden vectors
├── governance/                    # Active governance artifacts
│   ├── repo_classification.md
│   ├── dead_code_report.md
│   └── refactor_plan.md
│
├── docs/                          # Technical documentation
├── archive_legacy/                # Archived pre-consolidation code
│
├── schema_sync.py                 # CLI shim
├── commitment_cli.py              # CLI for CRSS-1
├── sources_v3.yaml                # Declarative PG schema
├── sources_v3.identity-test.yaml  # Identity hash strategies
├── requirements.txt
└── AGENTS.md
```

## Changes Required

### Modified Files

| File | Change | Risk |
|------|--------|------|
| `ingest/zip_downloader.py` | Add HTTP download, tags API, ZIP extraction, all 6 sections | LOW — existing URL gen preserved, new code additive |
| `ingest/normalizer.py` | Add `article_to_ingest_record()` bridge function | LOW — existing functions preserved |
| `dbsync/registry_ingest.py` | Add `ingest_records()` accepting pre-computed dicts | LOW — existing `ingest_batch()` refactored to use it |

### New Files

| File | Purpose |
|------|---------|
| `ingest/bulk_pipeline.py` | Orchestrator: discover→download→extract→parse→normalize→ingest→seal |
| `tests/test_bulk_pipeline.py` | Tests for parsing, normalization, and extraction |
| `governance/repo_classification.md` | Module classification |
| `governance/dead_code_report.md` | Dead code analysis |
| `governance/refactor_plan.md` | This document |

### Files NOT Modified

- `commitment/` — entire package untouched (Phase-Lock v2)
- `infra/` — infrastructure untouched
- `tests/test_commitment.py` — pure function tests untouched
- `tests/test_seal_roundtrip.py` — integration test untouched
- `schema_sync.py` — CLI shim untouched
- `commitment_cli.py` — CLI untouched

## New Ingestion Pipeline Flow

```
┌─────────────────┐
│  Date Range      │
│  (CLI input)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────────┐
│ Tags API         │────▶│ Special Edition   │
│ /o/tagsRest/     │     │ Detection         │
└────────┬────────┘     └──────────────────┘
         │
         ▼
┌─────────────────┐
│ Build Targets    │  S01{ddmmyyyy}.zip, S02..., S03...
│ (URL generation) │  + extras if tags indicate
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Download ZIPs    │  HTTP GET → data/inlabs/{date}_{section}.zip
│ (requests +      │  SHA-256 integrity check
│  retry + UA rot) │  Skip already-downloaded (manifest check)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Extract XML      │  zipfile → temp dir → *.xml files
│ from ZIPs        │  Skip image files (*.png, *.jpg)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Parse XML        │  INLabsXMLParser → DOUArticle dataclasses
│ (xml_parser)     │  Validation + skip malformed
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Normalize        │  DOUArticle → registry ingest record dict
│ (normalizer)     │  Compute identity hashes (natural_key, content, etc.)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Ingest to PG     │  SERIALIZABLE CTE state machine
│ (registry_ingest)│  INSERT...ON CONFLICT classification
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ CRSS-1 Seal      │  Commitment root + Merkle tree
│ (anchor + chain) │  Anchor chain append
└─────────────────┘
```

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| folderId changes per year | MEDIUM | Tags API probe + fallback patterns |
| Extra edition URL pattern unknown | LOW | 404 handling + INLabs fallback |
| Rate limiting by CDN (Azion) | LOW | User-Agent rotation + delay between requests |
| Public endpoint discontinued | LOW | INLabs authenticated API preserved in archive_legacy |

## Scope Limitations

This refactor is limited to:
- Dead code removal (already done → archive_legacy/)
- Structure simplification (wire existing modules together)
- Pipeline completion (stub → working code)

**Not** in scope:
- Feature redesign
- Schema changes
- Commitment layer modifications
- New extraction features (NER, embeddings, etc.)
