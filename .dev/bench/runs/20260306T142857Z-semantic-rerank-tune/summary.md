# Hybrid Search Benchmark

- Cases: 16
- Backends: hybrid, es, pg
- Run dir: `.dev/bench/runs/20260306T142857Z-semantic-rerank-tune`

## Aggregate Metrics

| Backend | Cases | P@1 | P@3 | P@5 | Hits@10 | MRR | Avg Relevance |
|---|---:|---:|---:|---:|---:|---:|---:|
| hybrid | 16 | 0.9375 | 0.6875 | 0.6875 | 1.0000 | 0.9688 | 0.4425 |
| es | 16 | 0.6250 | 0.5000 | 0.4500 | 0.8750 | 0.6944 | 0.4246 |
| pg | 16 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

## Categories

| Backend | Category | Cases | P@1 | P@3 | Hits@10 | MRR |
|---|---|---:|---:|---:|---:|---:|
| hybrid | semantic_paraphrase | 16 | 0.9375 | 0.6875 | 1.0000 | 0.9688 |
| es | semantic_paraphrase | 16 | 0.6250 | 0.5000 | 0.8750 | 0.6944 |
| pg | semantic_paraphrase | 16 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
