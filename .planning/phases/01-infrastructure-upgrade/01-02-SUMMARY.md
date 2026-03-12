---
plan: 01-02
status: complete
tasks_completed: 2
tasks_total: 2
commits:
  - hash: "(backfill - no code changes)"
    message: "Backfill 16.3M docs from MongoDB directly to gabi_documents_v2"
---

# Plan 01-02 Summary: Backfill MongoDB → V2

## Objective
Populate gabi_documents_v2 with all MongoDB documents so BM25 search works on v2.

## What Was Done
- Backfilled 16,305,252 documents from MongoDB directly to gabi_documents_v2
- Zero failures across 3,262 batches (batch_size=5000)
- Refresh interval disabled during bulk load, restored after
- Force merge to 5 segments completed
- BM25 search verified on v2 (10,000+ hits for "decreto")

## Deviation from Plan
**Original plan:** Reindex v1 → v2 via ES `_reindex` API
**Actual:** Backfilled MongoDB → v2 directly using `es_indexer backfill` with `ES_INDEX=gabi_documents_v2`
**Reason:** v1 index never existed in this ES instance. Direct backfill saved ~80 minutes (skip v1 creation + reindex step). Same end state.

## Additional Deviation
**Disk full incident:** First backfill attempt crashed at ~4.7M docs (939 batches) because `/media/psf/gabi_es` was a regular directory on root partition (62GB, 97% full), not a Parallels shared folder. Fixed by creating proper Parallels shared folder on Mac side pointing to iCloud storage (98GB free). Second attempt completed successfully.

## Verification
- [x] v2 document count: 16,305,252 (matches MongoDB exactly)
- [x] BM25 search returns results on v2
- [x] refresh_interval restored to 1s
- [x] Force merge completed
