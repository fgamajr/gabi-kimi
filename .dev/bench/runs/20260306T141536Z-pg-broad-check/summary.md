# Hybrid Search Benchmark

- Cases: 12
- Backends: pg, es, hybrid
- Run dir: `.dev/bench/runs/20260306T141536Z-pg-broad-check`

## Aggregate Metrics

| Backend | Cases | P@1 | P@3 | P@5 | Hits@10 | MRR | Avg Relevance |
|---|---:|---:|---:|---:|---:|---:|---:|
| pg | 12 | 0.1667 | 0.1667 | 0.1667 | 0.1667 | 0.1667 | 0.0783 |
| es | 12 | 0.5000 | 0.5000 | 0.5000 | 0.5000 | 0.5000 | 0.2386 |
| hybrid | 12 | 1.0000 | 1.0000 | 0.9833 | 1.0000 | 1.0000 | 0.4886 |

## Categories

| Backend | Category | Cases | P@1 | P@3 | Hits@10 | MRR |
|---|---|---:|---:|---:|---:|---:|
| pg | broad_filter | 12 | 0.1667 | 0.1667 | 0.1667 | 0.1667 |
| es | broad_filter | 12 | 0.5000 | 0.5000 | 0.5000 | 0.5000 |
| hybrid | broad_filter | 12 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
