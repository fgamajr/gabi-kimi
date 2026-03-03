# Refactor Plan — Repository Consolidation

**Generated:** 2026-03-03
**Decision:** Bulk-only architecture (no freeze fallback)
**Method:** Classify → Propose → Archive → Validate

---

## Architecture Decision

Pivot from HTML scraping to **bulk XML ingestion** via in.gov.br public ZIP endpoint:

```
https://www.in.gov.br/documents/49035712/685674076/S0{section}{ddmmyyyy}.zip
```

ZIP → XML → Normalize → PostgreSQL → CRSS-1 Anchor

This eliminates: HTML parsing, JS scraping, canonicalization, rate limiting, User-Agent rotation.

---

## Target Directory Structure

```
/
├── ingest/                          # NEW — bulk XML pipeline
│   ├── __init__.py
│   ├── zip_downloader.py            # URL discovery + download
│   ├── xml_parser.py                # XML → dataclasses (from scripts/inlabs_parser.py)
│   └── normalizer.py                # Field normalization
│
├── harvest/                         # Reduced — reusable utilities only
│   ├── __init__.py
│   ├── date_selector.py             # Date range generation
│   └── model.py                     # Dataclasses (expanded for XML fields)
│
├── commitment/                      # UNTOUCHED
│   ├── __init__.py
│   ├── anchor.py
│   ├── chain.py
│   ├── crss1.py
│   ├── tree.py
│   └── verify.py
│
├── dbsync/                          # UNTOUCHED
│   ├── differ.py, executor.py, introspect.py
│   ├── loader.py, planner.py
│   ├── registry_ingest.py
│   ├── registry_schema.sql
│   └── schema_sync.py
│
├── validation/                      # Reduced — generic modules only
│   ├── identity_analyzer.py
│   ├── rules.py
│   ├── semantic_resolver.py
│   ├── completeness_validator.py
│   ├── reporter.py
│   └── extractor.py                 # To be rewritten for XML
│
├── utils/                           # NEW — extracted from crawler/
│   ├── observability.py             # Logfmt structured logging
│   └── user_agent_rotator.py        # HTTP User-Agent rotation
│
├── infra/                           # UNTOUCHED
├── governance/                      # Updated
├── docs/                            # Cleaned
├── proofs/                          # UNTOUCHED
├── tests/                           # Reorganized
│   ├── test_commitment.py
│   ├── test_seal_roundtrip.py
│   └── fixtures/xml_samples/
│
├── data/inlabs/                     # Local (gitignored)
├── examples/
│   └── sources_v3_model.yaml
├── archive_legacy/20260303/         # Safe archive of all removed files
│
├── commitment_cli.py                # KEEP
├── schema_sync.py                   # KEEP
├── sources_v3.yaml                  # KEEP
├── sources_v3.identity-test.yaml    # KEEP
├── requirements.txt                 # Updated
└── AGENTS.md                        # Updated
```

---

## Phase 1 — Safe Archive

All files moved to `archive_legacy/20260303/` preserving original directory structure.

### crawler/ → archive (entire directory)
- engine.py, crawl_engine.py, frontier.py, pagination_strategies.py
- mock_browser.py, fake_browser.py, memory_budget.py, memory_levels.py
- dsl_schema.py, dsl_loader.py, dsl_validator.py
- **Extract first:** observability.py → utils/, user_agent_rotator.py → utils/

### harvest/ freeze path → archive
- freezer.py, canonicalizer.py, extractor.py
- **Keep:** date_selector.py, model.py, __init__.py

### inlabs_bulk/ → archive (entire directory)

### validation/ HTML-specific → archive
- edition_freezer.py, platform_classifier.py, html_tools.py
- corpus_sampler.py, json_extractor.py, json_extractor_production.py
- benchmark_json_extraction.py, cross_source_validator.py
- JSON_EXTRACTOR.md, JSON_EXTRACTOR_SUMMARY.md

### Dead CLIs → archive
- run_mock_crawl.py, harvest_cli.py, extract_test.py, historical_validate.py

### scripts/ → archive (17 of 19 files)
- All DEAD scripts (11 files)
- All RESEARCH scripts (6 files)
- **Promote first:** inlabs_parser.py → ingest/xml_parser.py

### analysis/ → archive (HTML-specific + research)
- **Promote first:** INLABS_STRUCTURE_SUMMARY.json, INLABS_ZIP_STRUCTURE_REPORT.md → docs/
- **Promote first:** analysis/samples/*.xml → tests/fixtures/xml_samples/

### reports/ → archive (all)
### docs/ obsolete → archive
- CROSS_SOURCE_VALIDATION*.md, VALIDATION_TEST_RESULTS.md
- phase1_listing_freeze.md, alternative_dou_sources_catalog.md
- presentations/ (all)

### examples/ obsolete → archive
- dou_leiturajornal_dynamic.yaml, mock_crawl.yaml

---

## Phase 2 — Promotions

| Source | Destination | Rationale |
|--------|-------------|-----------|
| `scripts/inlabs_parser.py` | `ingest/xml_parser.py` | XML parser reference for new pipeline |
| `analysis/INLABS_STRUCTURE_SUMMARY.json` | `docs/xml_schema_reference.json` | XML schema documentation |
| `analysis/INLABS_ZIP_STRUCTURE_REPORT.md` | `docs/zip_structure_reference.md` | ZIP structure documentation |
| `analysis/analysis/samples/*.xml` | `tests/fixtures/xml_samples/` | Test fixtures |
| `crawler/observability.py` | `utils/observability.py` | Shared logging utility |
| `crawler/user_agent_rotator.py` | `utils/user_agent_rotator.py` | Shared HTTP utility |

---

## Phase 3 — New Module: ingest/

Minimal scaffolding for bulk XML pipeline:

- `ingest/__init__.py` — Package init
- `ingest/xml_parser.py` — Promoted from `scripts/inlabs_parser.py`, adapted
- `ingest/zip_downloader.py` — Stub for URL discovery + download
- `ingest/normalizer.py` — Stub for field normalization

Integration point: `ingest/` calls `dbsync.registry_ingest` for persistence and `commitment.anchor` for anchoring.

---

## Phase 4 — Import Fixes

1. Update any remaining `from crawler.observability` → `from utils.observability`
2. Update any remaining `from crawler.user_agent_rotator` → `from utils.user_agent_rotator`
3. Update `requirements.txt`: remove `psutil`, add `requests`
4. Update `AGENTS.md` for new structure

---

## Phase 5 — Validation

1. `python3 tests/test_commitment.py` — must pass
2. `python3 schema_sync.py plan --sources sources_v3.yaml` — must work
3. `python3 commitment_cli.py --help` — must work
4. `python3 -c "import commitment; import dbsync; import validation; import harvest"` — no errors
5. `python3 -m py_compile ingest/xml_parser.py` — compiles

---

## Risk Mitigation

- **No deletions** — everything goes to `archive_legacy/20260303/`
- **Git-trackable** — archive directory is committed, enabling `git log` recovery
- **Incremental** — each phase can be committed separately
- Commitment layer and dbsync are **never modified**
- `hostile_verify.py` bug tracked separately (out of scope)
