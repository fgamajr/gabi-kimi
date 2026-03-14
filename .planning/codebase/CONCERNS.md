# Codebase Concerns

**Analysis Date:** 2026-03-11

## Tech Debt

### No Version Pinning in Requirements
- Issue: `requirements.txt` contains unpinned dependencies without version constraints
- Files: `requirements.txt`
- Impact: Builds may break unexpectedly when packages release breaking changes; reproducibility compromised
- Fix approach: Pin all dependencies with exact versions or minimum versions (e.g., `pymongo>=4.0,<5.0`)

### Legacy Code Archive
- Issue: Large `archive_legacy/` directory contains outdated code mixed with potentially useful patterns
- Files: `archive_legacy/` (multiple files, 3500+ lines in single web_server.py)
- Impact: Code rot, confusion about which code is active, maintenance burden
- Fix approach: Evaluate and either delete or properly archive outside repository

### Global Mutable State in DB Connection
- Issue: `MongoDB` class uses class-level mutable state for connection singleton
- Files: `src/backend/data/db.py`
- Impact: Thread safety concerns, testing difficulties, hidden dependencies
- Fix approach: Use dependency injection or context manager pattern

### Duplicated Environment Handling
- Issue: Multiple files read environment variables directly with `os.getenv()` instead of using centralized `Settings`
- Files: `src/backend/ingest/es_indexer.py` (lines 42-44, 100-107), `ops/bin/mcp_es_server.py` (lines 144-151)
- Impact: Configuration drift, harder to maintain, inconsistent defaults
- Fix approach: Consolidate all config in `src/backend/core/config.py` `Settings` class

## Known Bugs

### MCP Server Tool Mismatch
- Issue: `src/backend/mcp_server.py` uses MongoDB Atlas Search aggregation but actual MCP server in `ops/bin/mcp_es_server.py` uses Elasticsearch
- Files: `src/backend/mcp_server.py`, `ops/bin/mcp_es_server.py`
- Trigger: Running the documented MCP server
- Impact: Confusion, wrong code path used, docstrings claim "hybrid search (BM25 + Vector)" but implementation uses Atlas Search
- Workaround: Use `ops/bin/mcp_es_server.py` as documented in AGENTS.md

### Empty Return Without Logging
- Issue: Multiple functions return `None` or empty lists without logging why
- Files: `src/backend/ingest/dou_processor.py` (lines 165, 169, 178, 291), `src/backend/ingest/downloader.py` (lines 36, 62)
- Impact: Silent failures make debugging difficult; data may be lost without visibility
- Fix approach: Add logging before all early returns

### Year Extraction Bug
- Issue: `extract_structured_data()` extracts year incorrectly - matches `19` or `20` instead of full year
- Files: `src/backend/ingest/dou_processor.py` (line 104)
- Impact: `act_year` will be `19` or `20` instead of `2019`, `2020`, etc.
- Trigger: Documents with year in identifica field
- Fix approach: Change regex from `r'\b(19|20)\d{2}\b'` to capture full year, or use `match_year.group(0)`

## Security Considerations

### Unvalidated External XML Input
- Risk: XML files from external source (in.gov.br) are parsed without schema validation
- Files: `src/backend/ingest/dou_processor.py` (line 21 - `etree.XMLParser(recover=True)`)
- Current mitigation: `recover=True` prevents crashes from malformed XML
- Recommendations: Add XML schema validation; consider limiting entity expansion (XXE protection)

### No TLS Certificate Validation Override
- Risk: `ES_VERIFY_TLS` environment variable can disable TLS verification
- Files: `src/backend/ingest/es_indexer.py` (line 103), `ops/bin/mcp_es_server.py` (line 148)
- Current mitigation: Defaults to `True`
- Recommendations: Document clearly when this should be used (dev only), add warning log when disabled

### MongoDB Connection String in Environment
- Risk: `MONGO_STRING` may contain credentials in connection URI
- Files: `src/backend/core/config.py`
- Current mitigation: Loaded from `.env` file which is in `.gitignore`
- Recommendations: Consider using separate username/password fields for credential rotation

### External Download Without Integrity Verification
- Risk: ZIP files downloaded from in.gov.br are not verified for integrity beyond HTTP status
- Files: `src/backend/ingest/downloader.py` (lines 46-61)
- Current mitigation: HTTP status check
- Recommendations: Add checksum verification if available from source

## Performance Bottlenecks

### No Rate Limiting on External Downloads
- Problem: `DouDownloader` makes requests without rate limiting or backoff for server errors
- Files: `src/backend/ingest/downloader.py`
- Cause: No retry logic or exponential backoff for 429/5xx responses
- Impact: May overwhelm external server or get blocked
- Improvement path: Add `tenacity` library for retries with exponential backoff

### Large File Processing in Memory
- Problem: ZIP files are loaded entirely into memory before processing
- Files: `src/backend/ingest/dou_processor.py` (line 298 - `io.BytesIO(zip_bytes)`)
- Cause: Design decision for simplicity
- Impact: Memory pressure with large archives, potential OOM
- Improvement path: Stream to disk first, process from disk

### Cursor File as Single Point of Failure
- Problem: ES sync cursor stored in single JSON file; corruption causes data loss or re-processing
- Files: `src/backend/ingest/es_indexer.py` (lines 48-63)
- Cause: Simple file-based persistence
- Impact: Must re-run full backfill if cursor file corrupted
- Improvement path: Store cursor in MongoDB alongside documents

### Bulk Write Without Batch Size Limit
- Problem: `ingest_documents()` creates operations for all documents without chunking
- Files: `sync_dou.py` (lines 31-58)
- Cause: Assuming batch is from single ZIP
- Impact: Memory exhaustion with large ZIP files
- Improvement path: Add configurable batch size and chunk operations

## Fragile Areas

### Disk Space Management
- Files: `sync_dou.py` (lines 144-147), `sync_dou.py` (lines 65-107)
- Why fragile: Critical check at 2GB threshold; archive to iCloud can fail silently; cleanup may not run if process crashes
- Safe modification: Increase threshold, add pre-flight checks, implement transactional cleanup
- Test coverage: None

### ES Index Schema Migration
- Files: `src/backend/search/es_index_v1.json`, `src/backend/ingest/es_indexer.py`
- Why fragile: `--recreate-index` destroys all data; no migration path for schema changes
- Safe modification: Create versioned indexes, implement zero-downtime reindexing
- Test coverage: None

### Date Parsing with Single Format
- Files: `src/backend/ingest/dou_processor.py` (lines 23-31)
- Why fragile: Only handles `DD/MM/YYYY` format; documents with different date formats return `None`
- Safe modification: Add fallback formats or use dateutil parser
- Test coverage: None

## Scaling Limits

### Single-Threaded Ingestion
- Current capacity: Processes one ZIP file at a time sequentially
- Limit: Throughput bounded by single-thread performance and network I/O
- Scaling path: Implement parallel ZIP processing with multiprocessing or async

### MongoDB Connection Pool
- Current capacity: Single MongoClient instance shared globally
- Limit: Default connection pool (100 connections) may be insufficient for high concurrency
- Scaling path: Configure `maxPoolSize` explicitly, monitor connection usage

### Elasticsearch Batch Size
- Current capacity: 2000 documents per batch (configurable)
- Limit: Large documents may hit request size limits
- Scaling path: Implement adaptive batch sizing based on document size

## Dependencies at Risk

### `mcp` Package (Unpinned)
- Risk: Fast-moving API, potential breaking changes
- Impact: MCP server may break on package update
- Migration plan: Pin version, monitor changelog

### `lxml` Package
- Risk: C extension, may have platform-specific issues
- Impact: Installation failures on some systems
- Migration plan: Consider pure-Python fallback (defusedxml) for development

## Missing Critical Features

### No Health Check Endpoint
- Problem: No programmatic way to verify system health (MongoDB + Elasticsearch connectivity)
- Blocks: Monitoring, automated alerts, graceful degradation

### No Graceful Shutdown
- Problem: No signal handling for SIGTERM/SIGINT during long-running operations
- Blocks: Clean container orchestration, safe deployments

### No Data Validation on Ingest
- Problem: Documents are ingested without schema validation beyond Pydantic model
- Blocks: Data quality assurance, early error detection

## Test Coverage Gaps

### No Unit Test Suite
- What's not tested: All business logic in `src/backend/ingest/`
- Files: `src/backend/ingest/dou_processor.py`, `src/backend/ingest/es_indexer.py`
- Risk: Refactoring may introduce bugs without detection
- Priority: High

### No Integration Tests
- What's not tested: MongoDB operations, Elasticsearch indexing, end-to-end sync
- Files: `sync_dou.py`, `src/backend/data/db.py`
- Risk: Infrastructure changes may break production
- Priority: High

### Only Ad-Hoc Test Scripts
- What's tested: Basic connectivity only
- Files: `ops/test_mongo_connection.py`, `ops/test_extraction.py`, `ops/test_icloud_json.py`
- Risk: Not part of CI/CD, manual execution only
- Priority: Medium

### Untested Error Paths
- What's not tested: Network failures, invalid XML, corrupt ZIP, disk full
- Files: All modules
- Risk: System may crash or corrupt data on edge cases
- Priority: Medium

---

*Concerns audit: 2026-03-11*
