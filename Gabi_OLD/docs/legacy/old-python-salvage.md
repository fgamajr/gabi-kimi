# Old Python Salvage Notes

Date: 2026-02-24  
Status: active reference (legacy only)

## Scope

This document records what was intentionally preserved from the removed `old_python_implementation/` tree and why.

## Preserved Files

Legacy reference files were moved to:

- `grounding_docs/archive/legacy-python/src/gabi/pipeline/fetcher.py`
- `grounding_docs/archive/legacy-python/src/gabi/pipeline/parser.py`
- `grounding_docs/archive/legacy-python/src/gabi/crawler/politeness.py`
- `grounding_docs/archive/legacy-python/src/gabi/tasks/sync.py`

## Why These Files

1. `fetcher.py`
- Mature SSRF hardening and DNS/IP checks.
- Domain circuit-breaker behavior.
- Retry/backoff and streaming guardrails.

2. `parser.py`
- PDF hardening patterns (limits, quarantine, OCR fallback).
- Multi-format parser registry and failure classification.

3. `politeness.py`
- robots.txt cache + crawl-delay support.
- Adaptive per-domain politeness controls.

4. `sync.py`
- Long-running pipeline operational patterns.
- Memory and retry/error classification routines.

## Mapping to Current C#

1. Already covered in C# (partial)
- URL allowlist + blocked network ranges in API media ingress.

2. Still useful for backlog
- Crawl politeness/robots features for `web_crawl`.
- PDF parsing hardening in fetch/ingest path.
- Additional long-run memory guardrails for ingest/fetch loops.

## Deletion Record

`old_python_implementation/` was removed from active repository content after salvage extraction to reduce duplication, stale plans, and maintenance noise.
