# Hybrid Search Benchmark

- Cases: 16
- Backends: pg, es, hybrid
- Run dir: `.dev/bench/runs/20260306T141517Z-pg-normalized-smoke`

## Aggregate Metrics

| Backend | Cases | P@1 | P@3 | P@5 | Hits@10 | MRR | Avg Relevance |
|---|---:|---:|---:|---:|---:|---:|---:|
| pg | 16 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| es | 16 | 0.8125 | 0.9375 | 0.9500 | 1.0000 | 0.9062 | 0.4598 |
| hybrid | 16 | 0.8125 | 0.7917 | 0.8125 | 1.0000 | 0.8854 | 0.4512 |

## Categories

| Backend | Category | Cases | P@1 | P@3 | Hits@10 | MRR |
|---|---|---:|---:|---:|---:|---:|
| pg | bolsa_alimentacao | 16 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| es | bolsa_alimentacao | 16 | 0.8125 | 0.9375 | 1.0000 | 0.9062 |
| hybrid | bolsa_alimentacao | 16 | 0.8125 | 0.7917 | 1.0000 | 0.8854 |
