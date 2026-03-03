# Dead Code Report

**Generated:** 2026-03-03
**Method:** Static import graph analysis + CLI entrypoint tracing + semantic search

---

## Methodology

1. Traced all CLI entrypoints (`harvest_cli.py`, `commitment_cli.py`, `schema_sync.py`, `historical_validate.py`, `extract_test.py`, `run_mock_crawl.py`, `test_commitment.py`, `test_seal_roundtrip.py`)
2. Built transitive import graph from each entrypoint
3. Cross-referenced every `.py` file against import graph
4. Verified with `grep` for dynamic references (string-based imports, subprocess calls)

---

## DEAD Code — Zero Active References

| File | LOC | Evidence |
|------|-----|---------|
| `crawler/engine.py` | 373 | No CLI imports. `HeadlessBrowserRuntime` raises `NotImplementedError`. |
| `crawler/pagination_strategies.py` | 72 | Only imported by `crawler/engine.py` (dead chain). |
| `crawler/dsl_validator.py` | 83 | Only imported by `crawler/engine.py` (dead chain). |
| `crawler/fake_browser.py` | 170 | No CLI imports. |
| `crawler/memory_budget.py` | 190 | No CLI imports. Only consumer of `psutil` dependency. |
| `crawler/memory_levels.py` | 60 | Only imported by `memory_budget.py` (dead chain). |
| `scripts/analyze_detail_pages.py` | 502 | One-off HTML analysis. |
| `scripts/check_user_agent_rotation.py` | 34 | Local test, no integration. |
| `scripts/explore_leiturajornal.py` | 181 | One-off HTML exploration. |
| `scripts/fake_browse_last_5y.py` | 52 | Fake browser simulation. |
| `scripts/leiturajornal_optimized_downloader.py` | 604 | HTML scraping downloader. |
| `scripts/leiturajornal_rate_limit_analysis.py` | 605 | Rate limit analysis. |
| `scripts/map_leiturajornal_boundaries.py` | 665 | Boundary mapping. |
| `scripts/precise_boundaries.py` | 166 | Boundary detection. |
| `scripts/rate_limit_test.py` | 187 | Rate limit test. |
| `scripts/simulate_fake_browser_last_5y.py` | 189 | Fake browser simulation. |
| `scripts/simulate_memory_budget.py` | 97 | Memory budget simulation (depends on dead `memory_budget.py`). |

**Total dead LOC: ~4,230**

---

## EXPERIMENTAL — Built But Not Integrated

| File | LOC | Status |
|------|-----|--------|
| `harvest/extractor.py` | 150 | Phase 3 extractor — no CLI imports. |
| `harvest/canonicalizer.py` | 85 | Phase 2 canonicalizer — no CLI imports. |
| `validation/json_extractor.py` | 577 | JSON extractor — internal refs only. |
| `validation/json_extractor_production.py` | 450 | Batch processor — no CLI imports. |
| `validation/benchmark_json_extraction.py` | 390 | Benchmark — no CLI imports. |
| `validation/cross_source_validator.py` | 1,100 | Cross-source validation — not integrated. |
| `validation/edition_freezer.py` | 489 | Duplicate of `harvest/freezer.py`. |
| `validation/platform_classifier.py` | 156 | HTML platform classification. |
| `inlabs_bulk/inlabs_client.py` | 565 | INLabs auth client — `requests` not in requirements.txt. |
| `inlabs_bulk/bulk_download.py` | 513 | INLabs bulk CLI — experimental. |

**Total experimental LOC: ~4,475**

---

## RESEARCH — One-off Analysis Scripts

| File | LOC | Status |
|------|-----|--------|
| `scripts/inlabs_auth_analysis.py` | 589 | INLabs auth research. |
| `scripts/inlabs_leiturajornal_comparison.py` | 738 | Source comparison. |
| `scripts/inlabs_session_manager.py` | 366 | Session management. |
| `scripts/inlabs_parser.py` | 316 | XML parser — **candidate for promotion**. |
| `scripts/probe_inlabs_availability.py` | 684 | Availability probe. |
| `scripts/probe_inlabs_extended.py` | 127 | Extended probe. |
| `scripts/probe_inlabs_historical.py` | 201 | Historical probe. |
| `scripts/measure_phase0.py` | 200 | Phase 0 metrics. |
| `analysis/analyze_inlabs.py` | ~300 | INLabs ZIP analysis — **has hardcoded credentials**. |
| `analysis/leiturajornal_parser.py` | 481 | HTML parser. |
| `analysis/detailed_xml_analysis.py` | 376 | XML structure analysis — **has useful schema insights**. |
| `analysis/test_leiturajornal_parser.py` | ~100 | HTML parser tests. |

**Total research LOC: ~4,478**

---

## Critical Anomalies

1. **`hostile_verify.py` MISSING** — Referenced by `commitment/chain.py:5` and `test_seal_roundtrip.py:261` via subprocess, but file does not exist in repository. This means `chain_anchor()` and `ingest_batch_sealed()` will fail at hostile verification step.

2. **Hardcoded credentials** in `analysis/analyze_inlabs.py` (lines 27-28) — username and password in plaintext.

3. **`requests` missing from `requirements.txt`** — Used by `inlabs_bulk/`, `analysis/`, `scripts/inlabs_session_manager.py`.

4. **`psutil` nearly orphaned** — Only consumer is dead `crawler/memory_budget.py`.

5. **Cross-package fragile dependency** — `validation/corpus_sampler.py` and `validation/edition_freezer.py` import `crawler/user_agent_rotator.py`.

---

## Summary

| Category | Files | LOC |
|----------|-------|-----|
| DEAD | 17 | ~4,230 |
| EXPERIMENTAL | 10 | ~4,475 |
| RESEARCH | 12 | ~4,478 |
| **Total removable** | **39** | **~13,183** |
