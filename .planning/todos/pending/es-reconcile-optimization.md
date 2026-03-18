---
title: ES reconciliation full-scan optimization
created: 2026-03-17
area: ingest
priority: low
blocked_by: none
status: pending
---

`es_reconcile.py` does a full scan comparing all 16M Mongo IDs vs ES IDs (set difference).
For daily operation with small deltas, this is wasteful.

**Optimization ideas:**
- Use `updated_at` timestamp cursor to only check recently changed docs
- Maintain a reconciliation watermark in `es_sync_cursor.json`
- Run full reconciliation weekly, incremental daily
