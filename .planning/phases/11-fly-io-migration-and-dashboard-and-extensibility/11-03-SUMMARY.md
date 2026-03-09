---
phase: 11-fly-io-migration-and-dashboard-and-extensibility
plan: 03
subsystem: pipeline
tags: [asyncio, aiosqlite, chardet, httpx, elasticsearch, zip, xml-parser]

requires:
  - phase: 11-02
    provides: "SQLite Registry with state machine and conftest fixtures"
provides:
  - "5 pipeline phase modules: discovery, downloader, extractor, ingestor, verifier"
  - "run_discovery: Liferay JSONWS crawler with HEAD probe fallback"
  - "run_download: rate-limited ZIP downloader with SHA256 hashing"
  - "run_extract: multi-era ZIP extractor with chardet encoding detection and ZIP Slip protection"
  - "run_ingest: XML parser + ES bulk indexer (no PostgreSQL)"
  - "run_verify: post-ingest ES doc count verification with 5% tolerance"
affects: [11-04-scheduler, 11-05-admin-dashboard]

tech-stack:
  added: [chardet]
  patterns: [async pipeline modules with Registry state machine, TDD with mocked external deps]

key-files:
  created:
    - src/backend/worker/pipeline/__init__.py
    - src/backend/worker/pipeline/discovery.py
    - src/backend/worker/pipeline/downloader.py
    - src/backend/worker/pipeline/extractor.py
    - src/backend/worker/pipeline/ingestor.py
    - src/backend/worker/pipeline/verifier.py
    - tests/test_pipeline/test_discovery.py
    - tests/test_pipeline/test_downloader.py
    - tests/test_pipeline/test_extractor.py
    - tests/test_pipeline/test_ingestor.py
    - tests/test_pipeline/test_verifier.py
  modified: []

key-decisions:
  - "Used chardet for encoding detection with latin-1 fallback when confidence < 0.8"
  - "ZIP Slip protection via path validation (reject absolute paths and .. components)"
  - "Bulk batch size of 300 docs for ES indexing to balance throughput and memory"
  - "5% tolerance on doc count verification to account for dedup"
  - "Discovery uses asyncio.Semaphore(5) for concurrent request limiting"

patterns-established:
  - "Pipeline module pattern: async run_* function accepting (registry, run_id, ...) returning stats dict"
  - "All modules use Registry state machine for status transitions with proper error handling"
  - "External deps (HTTP, ES) mocked in tests via unittest.mock.patch"

requirements-completed: [PIPE-02, PIPE-03, PIPE-04, PIPE-05, PIPE-06]

duration: 7min
completed: 2026-03-09
---

# Phase 11 Plan 03: Pipeline Modules Summary

**5 async pipeline modules (discovery, download, extract, ingest, verify) adapting existing DOU codebase to SQLite registry with ES-direct indexing, no PostgreSQL dependency**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-09T12:50:40Z
- **Completed:** 2026-03-09T12:57:40Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments
- Discovery module crawls Liferay JSONWS API with semaphore-based rate limiting and HEAD probe fallback
- Downloader fetches QUEUED ZIPs with SHA256 hashing and 0.2s rate limiting between requests
- Extractor handles multi-era ZIP formats (2002-2018 and 2019+) with chardet encoding detection and ZIP Slip protection
- Ingestor reuses INLabsXMLParser, generates deterministic doc IDs, and bulk-indexes to ES in 300-doc batches
- Verifier queries ES doc counts with 5% tolerance for deduplication variance
- All 22 tests passing across 5 test files

## Task Commits

Each task was committed atomically:

1. **Task 1: Discovery and downloader modules** - `c2ae30d` (feat)
2. **Task 2: Extractor, ingestor, and verifier modules** - `4a659a4` (feat)

## Files Created/Modified
- `src/backend/worker/pipeline/__init__.py` - Package init
- `src/backend/worker/pipeline/discovery.py` - Liferay JSONWS crawler with HEAD probe fallback
- `src/backend/worker/pipeline/downloader.py` - Rate-limited ZIP downloader with SHA256 hashing
- `src/backend/worker/pipeline/extractor.py` - Multi-era ZIP extractor with encoding detection
- `src/backend/worker/pipeline/ingestor.py` - XML parser + ES bulk indexer (no PostgreSQL)
- `src/backend/worker/pipeline/verifier.py` - Post-ingest ES doc count verification
- `tests/test_pipeline/test_discovery.py` - 5 tests for discovery module
- `tests/test_pipeline/test_downloader.py` - 4 tests for downloader module
- `tests/test_pipeline/test_extractor.py` - 5 tests for extractor module
- `tests/test_pipeline/test_ingestor.py` - 5 tests for ingestor module
- `tests/test_pipeline/test_verifier.py` - 3 tests for verifier module

## Decisions Made
- Used chardet for encoding detection with latin-1 fallback when confidence < 0.8
- ZIP Slip protection via path validation (reject absolute paths and .. components)
- Bulk batch size of 300 docs for ES indexing to balance throughput and memory
- 5% tolerance on doc count verification to account for dedup
- Discovery uses asyncio.Semaphore(5) for concurrent request limiting

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed sha256 column name mismatch**
- **Found during:** Task 1 (downloader tests)
- **Issue:** Downloader used `sha256_hash` but the existing Registry schema (from Plan 02) names the column `sha256`
- **Fix:** Changed `sha256_hash` to `sha256` in downloader.py and test assertions
- **Files modified:** src/backend/worker/pipeline/downloader.py, tests/test_pipeline/test_downloader.py
- **Verification:** All tests pass
- **Committed in:** c2ae30d (Task 1 commit)

**2. [Rule 3 - Blocking] Installed missing chardet dependency**
- **Found during:** Task 1 (initial test collection)
- **Issue:** chardet not installed in Python environment
- **Fix:** pip install chardet
- **Verification:** Import succeeds, encoding detection tests pass

---

**Total deviations:** 2 auto-fixed (2 blocking)
**Impact on plan:** Both fixes necessary for correct operation. No scope creep.

## Issues Encountered
None beyond the auto-fixed deviations above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 5 pipeline modules ready for scheduling in Plan 04
- Each module accepts Registry instance and run_id, returning stats dicts
- All modules import without errors and have no PostgreSQL dependency

## Self-Check: PASSED

- All 11 files exist on disk
- Commits c2ae30d and 4a659a4 verified in git log
- All 22 tests pass

---
*Phase: 11-fly-io-migration-and-dashboard-and-extensibility*
*Completed: 2026-03-09*
