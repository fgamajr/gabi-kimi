# Hybrid Search Benchmark

- Cases: 16
- Backends: hybrid, es, pg
- Run dir: `.dev/bench/runs/20260306T144459Z-implicit-do3-filter`

## Aggregate Metrics

| Backend | Cases | P@1 | P@3 | P@5 | Hits@10 | MRR | Avg Relevance |
|---|---:|---:|---:|---:|---:|---:|---:|
| hybrid | 16 | 1.0000 | 1.0000 | 0.9875 | 1.0000 | 1.0000 | 0.4803 |
| es | 16 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| pg | 16 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

## Categories

| Backend | Category | Cases | P@1 | P@3 | Hits@10 | MRR |
|---|---|---:|---:|---:|---:|---:|
| hybrid | procurement_do3 | 16 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| es | procurement_do3 | 16 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| pg | procurement_do3 | 16 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
