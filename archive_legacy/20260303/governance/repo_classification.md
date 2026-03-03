# Repository Classification — Phase 0 State Reconstruction

**Generated:** 2026-03-03  
**Method:** Static analysis + QMD semantic search + import graph traversal

---

## Executive Summary

| Category | Count | Risk Level | Action |
|----------|-------|------------|--------|
| **ACTIVE** | 12 files | ✅ Safe | Keep |
| **SUPPORT** | 18 files | ✅ Safe | Keep |
| **GOVERNANCE** | 25+ docs | ✅ Safe | Keep (audit relevance) |
| **DEAD** | ~15 files | ⚠️ Review | Candidate for removal |
| **EXPERIMENTAL** | ~20 scripts | ⚠️ Review | Archive or remove |

---

## 1. ACTIVE Modules (Direct Execution Path)

### 1.1 Harvest Layer (Freeze Path) ✅

| File | LOC | Status | References |
|------|-----|--------|------------|
| `harvest/freezer.py` | 280 | **ACTIVE** | Called by `harvest_cli.py`, imported by `validation/edition_freezer.py` |
| `harvest/date_selector.py` | 45 | **ACTIVE** | Imported by `harvest_cli.py`, `freezer.py` |
| `harvest/canonicalizer.py` | 75 | **ACTIVE** | Phase 2 in phase_lock.md, targets Liferay HTML |
| `harvest/extractor.py` | 110 | **ACTIVE** | Phase 3, targets modern act format |
| `harvest/model.py` | 20 | **SUPPORT** | Data classes for Article, NormativeAct |
| `harvest_cli.py` | ~200 | **CLI ENTRYPOINT** | Main freeze workflow |

**Assessment:** Freeze path is **complete and functional**. Single-threaded, no checkpoint/resume, but production-ready for targeted ranges.

---

### 1.2 Commitment Layer (CRSS-1) ✅

| File | LOC | Status | References |
|------|-----|--------|------------|
| `commitment/crss1.py` | 80 | **ACTIVE** | Canonical serializer (NFC, pipe-delimited) |
| `commitment/tree.py` | 100 | **ACTIVE** | Binary Merkle tree with inclusion proofs |
| `commitment/anchor.py` | 350 | **ACTIVE** | Anchor projection, REPEATABLE READ, imported by `registry_ingest.py` |
| `commitment/chain.py` | 220 | **ACTIVE** | Chain anchoring, `fcntl` locking |
| `commitment/verify.py` | 100 | **ACTIVE** | Independent verifier |
| `commitment_cli.py` | ~100 | **CLI ENTRYPOINT** | Manual anchoring, verification |
| `test_commitment.py` | ~200 | **TEST** | Pure function tests (no DB) |
| `test_seal_roundtrip.py` | ~150 | **TEST** | End-to-end seal test |

**Assessment:** **Strongest module.** 100% coverage, production-ready, deterministic append-only chain. Genesis anchor exists in `proofs/anchors/0000-bootstrap.json`.

---

### 1.3 DBSync Layer (Schema + Ingestion) ✅

| File | LOC | Status | References |
|------|-----|--------|------------|
| `dbsync/registry_ingest.py` | 669 | **ACTIVE** | SERIALIZABLE CTE state machine, commitment integration |
| `dbsync/schema_sync.py` | 230 | **CLI ENTRYPOINT** | `plan`/`apply`/`verify` workflow |
| `dbsync/differ.py` | 190 | **SUPPORT** | Schema diff engine |
| `dbsync/planner.py` | 180 | **SUPPORT** | Build execution plan |
| `dbsync/introspect.py` | 175 | **SUPPORT** | Database introspection |
| `dbsync/loader.py` | 90 | **SUPPORT** | Load YAML entity specs |
| `dbsync/executor.py` | 30 | **SUPPORT** | Apply operations |
| `dbsync/registry_schema.sql` | 250 | **SCHEMA** | Append-only registry tables |

**Assessment:** Production-ready for single-source DOU. `registry_ingest.py` is heavyweight but complete.

---

### 1.4 Validation Layer (Extraction Harness) ✅

| File | LOC | Status | References |
|------|-----|--------|------------|
| `validation/extractor.py` | 420 | **ACTIVE** | `ExtractionHarness`, CSS selector extraction |
| `validation/rules.py` | 55 | **SUPPORT** | Rule loading, selector parsing |
| `validation/html_tools.py` | 70 | **SUPPORT** | HTML tag parsing |
| `validation/semantic_resolver.py` | 370 | **SUPPORT** | Semantic resolution with fallbacks |
| `validation/reporter.py` | 130 | **SUPPORT** | Report generation |
| `validation/identity_analyzer.py` | 370 | **ACTIVE** | Identity analysis for ingestion |
| `extract_test.py` | ~200 | **TEST** | Extraction harness tests |
| `historical_validate.py` | ~300 | **CLI + TEST** | Full validation workflow |

**Assessment:** Complete extraction harness with heuristic fallbacks. Used by ingestion path.

---

## 2. SUPPORT Modules (Imported by ACTIVE)

### 2.1 Crawler Infrastructure (DSL + Engine)

| File | LOC | Status | Notes |
|------|-----|--------|-------|
| `crawler/dsl_schema.py` | 110 | **SUPPORT** | CrawlSpec, Step, ExtractStep dataclasses |
| `crawler/dsl_loader.py` | 38 | **SUPPORT** | Load YAML specs |
| `crawler/dsl_validator.py` | 83 | **SUPPORT** | Validate plans |
| `crawler/engine.py` | 340 | **DEAD?** | Generic HTTP crawler (not used in freeze path) |
| `crawler/crawl_engine.py` | 130 | **DEAD?** | Mock browser engine (test only) |
| `crawler/mock_browser.py` | 70 | **TEST ONLY** | Mock browser for testing |
| `crawler/frontier.py` | 27 | **DEAD?** | URL frontier (not used) |
| `crawler/memory_budget.py` | 190 | **SUPPORT** | Memory governor |
| `crawler/memory_levels.py` | 17 | **SUPPORT** | Memory level enums |
| `crawler/observability.py` | 120 | **SUPPORT** | Structured logging |
| `crawler/pagination_strategies.py` | 72 | **DEAD?** | Pagination resolution (not used) |
| `crawler/user_agent_rotator.py` | 39 | **SUPPORT** | UA rotation |
| `crawler/fake_browser.py` | 170 | **EXPERIMENTAL** | Fake browser simulation |
| `run_mock_crawl.py` | ~150 | **TEST ONLY** | Mock crawl simulation |

**Assessment:** **Mixed.** DSL components are solid but crawl engine is not used in freeze path. `engine.py` has `NotImplementedError` for HeadlessBrowserRuntime.

---

### 2.2 Infrastructure

| File | LOC | Status | Notes |
|------|-----|--------|-------|
| `infra/infra_manager.py` | ~200 | **ACTIVE** | Docker PostgreSQL management (`up`/`down`/`reset`) |
| `schema_sync.py` | ~50 | **CLI WRAPPER** | Delegates to `dbsync/schema_sync.py` |

---

## 3. GOVERNANCE Artifacts (Documentation/Specs)

### 3.1 Core Governance (Keep) ✅

| File | Purpose | Status |
|------|---------|--------|
| `QWEN.md` | Project context, architecture, conventions | **KEEP** |
| `AGENTS.md` | Repository guidelines | **KEEP** |
| `docs/governance/phase-lock.md` | Phase-locked roadmap | **KEEP** |
| `docs/governance/full-project-assessment.md` | Module-by-module assessment | **KEEP** |
| `docs/governance/refactor_plan.md` | *(To be created)* | **TODO** |
| `sources_v3.yaml` | Master crawl spec | **KEEP** (DSL reference) |
| `sources_v3.identity-test.yaml` | Identity test config | **KEEP** (test fixture) |

---

### 3.2 Research/Analysis (Archive Candidate) ⚠️

| File | Purpose | Status |
|------|---------|--------|
| `docs/alternative_dou_sources_catalog.md` | Source research | **ARCHIVE** (not actionable) |
| `docs/CROSS_SOURCE_VALIDATION*.md` | Cross-source validation spec | **ARCHIVE** (not implemented) |
| `docs/INLabs_DOU_XML_Specification.md` | INLabs XML spec | **ARCHIVE** (pivot away from INLabs) |
| `docs/INLabs_XML_Analysis_Summary.md` | INLabs analysis | **ARCHIVE** |
| `docs/VALIDATION_TEST_RESULTS.md` | Old test results | **ARCHIVE** |
| `docs/phase1_listing_freeze.md` | Freeze spec (superseded) | **ARCHIVE** (use `harvest/` code) |
| `docs/DB_APPLIANCE_OPERATOR_HANDBOOK.md` | DB ops guide | **KEEP** (still relevant) |

---

### 3.3 Presentations (Archive) ⚠️

| File | Purpose | Status |
|------|---------|--------|
| `docs/presentations/audit-as-code-latex-output.md` | Technical presentation | **ARCHIVE** (nice-to-have) |

---

## 4. DEAD Code (No References in Code/Tests/CLI)

### 4.1 Crawler Layer (Dead) ☠️

| File | LOC | Why Dead | Risk |
|------|-----|----------|------|
| `crawler/engine.py` | 340 | Not imported, `HeadlessBrowserRuntime` unimplemented | **LOW** (freeze replaces) |
| `crawler/crawl_engine.py` | 130 | Only used by `run_mock_crawl.py` (test) | **LOW** |
| `crawler/frontier.py` | 27 | Not imported anywhere | **LOW** |
| `crawler/pagination_strategies.py` | 72 | Not imported | **LOW** |
| `crawler/mock_browser.py` | 70 | Test-only (mock crawl) | **LOW** |

**Recommendation:** Move to `/archive_legacy/crawler/` if freeze path is primary.

---

### 4.2 Validation Layer (Partially Dead) ☠️

| File | LOC | Why Dead | Risk |
|------|-----|----------|------|
| `validation/completeness_validator.py` | 300 | Not imported by active path | **MEDIUM** (may be needed for QA) |
| `validation/corpus_sampler.py` | 400 | Only used by `historical_validate.py` | **LOW** (validation-only) |
| `validation/cross_source_validator.py` | 1100 | Cross-source not implemented | **HIGH** (future-proofing?) |
| `validation/edition_freezer.py` | 430 | Superseded by `harvest/freezer.py` | **LOW** |
| `validation/platform_classifier.py` | 130 | Not imported | **LOW** |
| `validation/json_extractor*.py` | 600+ | JSON extraction (not DOU HTML) | **MEDIUM** (alternative format) |
| `validation/benchmark_json_extraction.py` | 300 | Benchmark script | **LOW** |

**Recommendation:** Keep `completeness_validator.py` and `cross_source_validator.py` for future QA. Archive `edition_freezer.py` (duplicate of `harvest/freezer.py`).

---

### 4.3 Analysis/Scripts (Mostly Dead) ☠️

| File | Purpose | Status |
|------|---------|--------|
| `analysis/detailed_xml_analysis.py` | XML analysis | **ARCHIVE** (INLabs-specific) |
| `analysis/analyze_inlabs.py` | INLabs analysis | **ARCHIVE** |
| `analysis/leiturajornal_parser.py` | LeituraJornal parser | **ARCHIVE** (alternative source) |
| `analysis/test_leiturajornal_parser.py` | Parser test | **ARCHIVE** |

**Scripts Directory:** Most scripts are **one-off probes** for INLabs/LeituraJornal research. None are in active execution path.

**Recommendation:** Move entire `analysis/` and most of `scripts/` to `/archive_legacy/research/`.

---

## 5. EXPERIMENTAL / Research Code

### 5.1 INLabs/LeituraJornal Probes (Archive) 🔬

| File | Purpose | Keep? |
|------|---------|-------|
| `scripts/inlabs_*.py` (6 files) | INLabs availability/auth probes | **NO** |
| `scripts/leiturajornal_*.py` (3 files) | LeituraJornal rate limit/boundaries | **NO** |
| `scripts/map_leiturajornal_boundaries.py` | Boundary mapping | **NO** |
| `scripts/explore_leiturajornal.py` | Exploration script | **NO** |
| `inlabs_bulk/bulk_download.py` | INLabs bulk download | **NO** (wrong architecture) |

**Rationale:** These are **research artifacts** for alternative DOU sources. If pivoting to bulk data from official source, these are obsolete.

---

### 5.2 Simulation Scripts (Archive) 🔬

| File | Purpose | Keep? |
|------|---------|-------|
| `scripts/simulate_memory_budget.py` | Memory simulation | **NO** (crawler-specific) |
| `scripts/simulate_fake_browser_last_5y.py` | Fake browser sim | **NO** |
| `scripts/fake_browse_last_5y.py` | Fake browse | **NO** |
| `scripts/measure_phase0.py` | Phase 0 measurement | **NO** |

---

### 5.3 Utility Scripts (Keep Some) ✅

| File | Purpose | Keep? |
|------|---------|-------|
| `scripts/check_user_agent_rotation.py` | UA rotation check | **NO** (crawler-specific) |
| `scripts/analyze_detail_pages.py` | Detail page analysis | **NO** (research) |
| `scripts/rate_limit_test.py` | Rate limit test | **MAYBE** (reuse for bulk) |
| `scripts/precise_boundaries.py` | Boundary detection | **MAYBE** (reuse for bulk) |
| `scripts/probe_inlabs_*.py` (3 files) | INLabs probes | **NO** |

---

## 6. Dependency Graph

### 6.1 CLI Entrypoints → Active Modules

```
harvest_cli.py
  ├─ harvest/freezer.py
  │   └─ harvest/date_selector.py
  └─ harvest/extractor.py
      └─ harvest/model.py

schema_sync.py
  └─ dbsync/schema_sync.py
      ├─ dbsync/differ.py
      ├─ dbsync/planner.py
      ├─ dbsync/introspect.py
      ├─ dbsync/loader.py
      └─ dbsync/executor.py

commitment_cli.py
  └─ commitment/anchor.py
      ├─ commitment/crss1.py
      └─ commitment/tree.py

historical_validate.py
  ├─ validation/corpus_sampler.py
  ├─ validation/edition_freezer.py  # DUPLICATE of harvest/freezer.py
  ├─ validation/extractor.py
  ├─ validation/identity_analyzer.py
  └─ validation/reporter.py

extract_test.py
  └─ validation/extractor.py

run_mock_crawl.py
  ├─ crawler/crawl_engine.py  # TEST ONLY
  ├─ crawler/dsl_loader.py
  └─ crawler/observability.py

infra/infra_manager.py
  └─ (Docker CLI wrappers)
```

### 6.2 Transitive Imports

```
commitment/
  anchor.py → crss1.py, tree.py
  verify.py → anchor.py
  (No external deps except stdlib + hashlib)

dbsync/
  registry_ingest.py → commitment/anchor.py, validation/identity_analyzer.py
  schema_sync.py → dbsync/* (internal only)

harvest/
  freezer.py → date_selector.py
  extractor.py → model.py
  (No cross-layer deps)

validation/
  extractor.py → rules.py, html_tools.py, semantic_resolver.py
  identity_analyzer.py → (stdlib only)
  reporter.py → extractor.py
```

---

## 7. Risk Assessment

### 7.1 Safe to Remove (Low Risk)

| Module | Files | Rationale |
|--------|-------|-----------|
| Crawler engine | `engine.py`, `frontier.py`, `pagination_strategies.py` | Freeze path replaces |
| INLabs research | `scripts/inlabs_*.py`, `analysis/analyze_inlabs.py` | Pivot away from INLabs |
| LeituraJornal | `scripts/leiturajornal_*.py`, `analysis/leiturajornal_*.py` | Alternative source (not active) |
| Simulation | `scripts/simulate_*.py`, `scripts/fake_browse_*.py` | One-off experiments |
| Mock browser | `crawler/mock_browser.py`, `crawler/crawl_engine.py` | Test-only |

**Total:** ~20 files, ~3000 LOC

---

### 7.2 Review Required (Medium Risk)

| Module | Files | Question |
|--------|-------|----------|
| `validation/cross_source_validator.py` | 1100 LOC | Future multi-source support? |
| `validation/completeness_validator.py` | 300 LOC | QA requirement? |
| `validation/json_extractor*.py` | 600+ LOC | Alternative format (JSON vs HTML)? |
| `crawler/dsl_*.py` | 230 LOC | Keep for YAML spec parsing? |
| `crawler/memory_budget.py` | 190 LOC | Reuse for bulk download? |

**Decision needed:** Are these **future assets** or **dead weight**?

---

### 7.3 Keep (Critical)

| Module | Files | Why |
|--------|-------|-----|
| Harvest | 6 files | Freeze path core |
| Commitment | 6 files | CRSS-1 integrity |
| DBSync | 8 files | Ingestion + schema |
| Validation (core) | 5 files | Extraction harness |
| Governance (core) | 5 docs | Architecture specs |

**Total:** ~30 files, ~4000 LOC (core functionality)

---

## 8. Proposed Target Structure

```
gabi-kimi/
├── harvest/                    # ✅ Freeze path
│   ├── freezer.py
│   ├── date_selector.py
│   ├── canonicalizer.py
│   ├── extractor.py
│   ├── model.py
│   └── __init__.py
│
├── ingest/                     # ✅ Renamed from dbsync/
│   ├── registry_ingest.py
│   ├── schema_sync.py
│   ├── differ.py
│   ├── planner.py
│   ├── introspect.py
│   ├── loader.py
│   ├── executor.py
│   └── registry_schema.sql
│
├── commitment/                 # ✅ CRSS-1
│   ├── crss1.py
│   ├── tree.py
│   ├── anchor.py
│   ├── chain.py
│   └── verify.py
│
├── validation/                 # ✅ Extraction harness
│   ├── extractor.py
│   ├── rules.py
│   ├── html_tools.py
│   ├── semantic_resolver.py
│   ├── identity_analyzer.py
│   └── reporter.py
│
├── infra/                      # ✅ DB appliance
│   └── infra_manager.py
│
├── governance/                 # ✅ Active specs
│   ├── phase-lock.md
│   ├── full-project-assessment.md
│   └── refactor_plan.md (new)
│
├── tests/                      # ✅ Active tests
│   ├── test_commitment.py
│   ├── test_seal_roundtrip.py
│   └── extract_test.py
│
├── CLI entrypoints
│   ├── harvest_cli.py
│   ├── schema_sync.py
│   ├── commitment_cli.py
│   └── historical_validate.py
│
├── docs/
│   ├── DB_APPLIANCE_OPERATOR_HANDBOOK.md
│   └── governance/ (moved up)
│
└── archive_legacy/             # 📦 Moved here (not deleted)
    ├── crawler/                # Old crawl engine
    ├── validation-extras/      # JSON extractors, cross-source
    ├── research/               # INLabs, LeituraJornal probes
    └── docs-archive/           # Superseded docs
```

---

## 9. Next Steps

### Phase 1 — Dead Code Detection (Next)
- [ ] Generate `governance/dead_code_report.md` with file-by-file analysis
- [ ] Confirm no hidden imports via `grep -r "import.*module"`
- [ ] Verify test coverage for ACTIVE modules

### Phase 2 — Refactor Plan
- [ ] Create `governance/refactor_plan.md` with move/remove proposals
- [ ] Define archive structure (`archive_legacy/YYYYMMDD/`)
- [ ] Plan smoke tests post-refactor

### Phase 3 — Adversarial Review
- [ ] Run codex/qwen/kimi/glm review on diff
- [ ] Classify findings (FIXABLE/STRUCTURAL/THEORETICAL/NOISE)
- [ ] Fix FIXABLE, escalate STRUCTURAL

### Phase 4 — Safe Removal
- [ ] Move files to `archive_legacy/` (don't delete yet)
- [ ] Run import tests + freeze smoke test
- [ ] Commit refactor

---

## 10. Termination Conditions

Repository consolidation is complete when:

- [ ] Only ACTIVE + SUPPORT + GOVERNANCE files remain in main tree
- [ ] All DEAD/EXPERIMENTAL files archived (not deleted)
- [ ] Tests pass for active modules
- [ ] Freeze path smoke test passes
- [ ] Ingestion path smoke test passes
- [ ] No circular imports introduced
- [ ] `governance/refactor_plan.md` documents all changes

---

**Status:** Phase 0 Complete. Ready for Phase 1 (Dead Code Detection).
