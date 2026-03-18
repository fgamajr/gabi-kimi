---
title: Reranker deployment blocked by insufficient RAM
created: 2026-03-17
area: search
priority: medium
blocked_by: infrastructure
status: pending
---

Host has ~3.2 GiB free RAM. The qwen3-reranker-vllm:0.6B model needs ~2GB+ and competes with Mongo/ES.
Reranker adapter exists (`ops/reranker_adapter.py`) and is wired up but disabled (`RERANKER_ENABLED=false`).

**Options:**
- Upgrade Hetzner instance RAM (CPX42 → CPX52)
- Use Cohere rerank-multilingual-v3.0 API (external dependency + cost)
- Evaluate if BM25 with canonical ranking (Front 8) is sufficient
- See Front 5 swarm evaluation results for decision
