---
title: Hetzner volume disk space monitoring
created: 2026-03-18
area: ops
priority: medium
blocked_by: none
status: pending
---

`/mnt/HC_Volume_105154890` is at 84% (93G used / 118G total, 19G free).
ES data: 54G, Mongo data: 39G. Volume was expanded from 98G to 120G on 2026-03-18.

**Actions needed:**
- Set up disk space alerting (simple cron + email or webhook)
- Plan next expansion threshold (trigger at 90%)
- Evaluate Mongo compaction to reclaim space
- Consider moving Docker images/layers to root disk (281G free) — partially done via data-root move
