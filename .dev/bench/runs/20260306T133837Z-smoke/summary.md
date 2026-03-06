# Hybrid Search Benchmark

- Cases: 6
- Backends: hybrid, pg
- Run dir: `.dev/bench/runs/20260306T133837Z-smoke`

## Aggregate Metrics

| Backend | Cases | P@1 | P@3 | P@5 | Hits@10 | MRR | Avg Relevance |
|---|---:|---:|---:|---:|---:|---:|---:|
| hybrid | 6 | 0.8333 | 0.6667 | 0.6333 | 1.0000 | 0.8611 | 0.4247 |
| pg | 6 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

## Categories

| Backend | Category | Cases | P@1 | P@3 | Hits@10 | MRR |
|---|---|---:|---:|---:|---:|---:|
| hybrid | bolsa_alimentacao | 6 | 0.8333 | 0.6667 | 1.0000 | 0.8611 |
| pg | bolsa_alimentacao | 6 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
