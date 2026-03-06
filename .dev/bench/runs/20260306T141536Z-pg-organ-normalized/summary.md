# Hybrid Search Benchmark

- Cases: 16
- Backends: pg, es, hybrid
- Run dir: `.dev/bench/runs/20260306T141536Z-pg-organ-normalized`

## Aggregate Metrics

| Backend | Cases | P@1 | P@3 | P@5 | Hits@10 | MRR | Avg Relevance |
|---|---:|---:|---:|---:|---:|---:|---:|
| pg | 16 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.5000 |
| es | 16 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.5000 |
| hybrid | 16 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.5000 |

## Categories

| Backend | Category | Cases | P@1 | P@3 | Hits@10 | MRR |
|---|---|---:|---:|---:|---:|---:|
| pg | organ_type_filters | 16 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| es | organ_type_filters | 16 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| hybrid | organ_type_filters | 16 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
