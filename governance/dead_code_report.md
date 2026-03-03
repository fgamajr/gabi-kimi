# Dead Code Report

> Generated: 2026-03-03 — Phase 1 Static + Semantic Detection

## Methodology

1. Grep all `import` statements across non-`archive_legacy/` Python files
2. Check CLI entrypoints (`if __name__ == "__main__"`)
3. Check test coverage links
4. Cross-reference governance/config file references

## Results

### Active Codebase (non-archive_legacy/)

**No dead modules detected.**

All 22 non-`__init__` Python modules are wired into the dependency graph via
at least one of: direct import, CLI entrypoint, or test reference.

### Loose Ends (not dead, but not yet fully wired)

| Module | Issue | Resolution |
|--------|-------|------------|
| `ingest/normalizer.py` | Imported by nobody (was bridge stub) | Now integrated into `ingest/bulk_pipeline.py` |
| `ingest/zip_downloader.py` | Had no HTTP download code (URL gen only) | Now completed with full download + extraction |

### archive_legacy/ — Confirmed Archived

All modules under `archive_legacy/20260303/` are classified EXPERIMENTAL.
They are **not imported** by any active module.

| Path | Description | Status |
|------|-------------|--------|
| `archive_legacy/20260303/crawler/` | HTML scraping engine | ARCHIVED — replaced by bulk XML pipeline |
| `archive_legacy/20260303/harvest/` | Legacy harvest utilities | ARCHIVED — consolidated into `ingest/` |
| `archive_legacy/20260303/validation/` | HTML validation harness | ARCHIVED — replaced by XML-native validation |
| `archive_legacy/20260303/validation_html/` | HTML completeness checks | ARCHIVED |
| `archive_legacy/20260303/inlabs_bulk/` | Authenticated INLabs downloader | ARCHIVED — replaced by public endpoint bulk_pipeline |
| `archive_legacy/20260303/utils/` | Shared utilities (observability, UA rotation) | ARCHIVED |
| `archive_legacy/20260303/scripts/` | Ad-hoc scripts | ARCHIVED |
| `archive_legacy/20260303/analysis/` | XML structure analysis | ARCHIVED — findings incorporated |
| `archive_legacy/20260303/docs_governance/` | Legacy governance specs | ARCHIVED |
| `archive_legacy/20260303/examples/` | DSL examples | ARCHIVED |
| `archive_legacy/20260303/governance/` | Legacy governance | ARCHIVED |
| `archive_legacy/20260303/reports/` | Analysis reports | ARCHIVED |

### Third-Party Dependencies

| Package | Status | Used By |
|---------|--------|---------|
| `loguru>=0.7` | DECLARED but not imported | Forward dependency for structured logging |
| `psycopg[binary]>=3.1` | ACTIVE | commitment, dbsync, registry_ingest |
| `pyyaml>=6.0` | ACTIVE | dbsync/loader, ingest/identity_analyzer |
| `requests>=2.31` | ACTIVE | ingest/zip_downloader (now used for HTTP downloads) |

## Candidates for Removal

**None from active codebase.**

The `archive_legacy/` directory is already properly isolated and should be
retained as historical reference per Phase-Lock v2 rules.

## Conclusion

The active codebase is clean. The consolidation from 2026-03-03 successfully
moved all dead/experimental code to `archive_legacy/`. The remaining modules
form a tight dependency graph with no orphans.
