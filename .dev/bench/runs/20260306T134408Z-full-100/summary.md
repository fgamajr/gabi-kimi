# Hybrid Search Benchmark

- Cases: 100
- Backends: hybrid, pg, es
- Run dir: `.dev/bench/runs/20260306T134408Z-full-100`

## Aggregate Metrics

| Backend | Cases | P@1 | P@3 | P@5 | Hits@10 | MRR | Avg Relevance |
|---|---:|---:|---:|---:|---:|---:|---:|
| hybrid | 100 | 0.8000 | 0.7933 | 0.7760 | 0.9300 | 0.8471 | 0.4890 |
| pg | 100 | 0.0200 | 0.0200 | 0.0200 | 0.0200 | 0.0200 | 0.0094 |
| es | 100 | 0.3800 | 0.3767 | 0.3820 | 0.4900 | 0.4174 | 0.3088 |

## Categories

| Backend | Category | Cases | P@1 | P@3 | Hits@10 | MRR |
|---|---|---:|---:|---:|---:|---:|
| hybrid | bolsa_alimentacao | 16 | 0.8125 | 0.7917 | 1.0000 | 0.8854 |
| hybrid | broad_filter | 12 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| hybrid | legal_concepts | 12 | 0.5833 | 0.5555 | 0.7500 | 0.6667 |
| hybrid | organ_type_filters | 16 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| hybrid | person_exact_phrase | 12 | 0.9167 | 0.8611 | 0.9167 | 0.9167 |
| hybrid | procurement_do3 | 16 | 0.9375 | 0.9167 | 1.0000 | 0.9688 |
| hybrid | semantic_paraphrase | 16 | 0.3750 | 0.4375 | 0.8125 | 0.5028 |
| pg | bolsa_alimentacao | 16 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| pg | broad_filter | 12 | 0.1667 | 0.1667 | 0.1667 | 0.1667 |
| pg | legal_concepts | 12 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| pg | organ_type_filters | 16 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| pg | person_exact_phrase | 12 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| pg | procurement_do3 | 16 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| pg | semantic_paraphrase | 16 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| es | bolsa_alimentacao | 16 | 0.8125 | 0.8750 | 1.0000 | 0.9062 |
| es | broad_filter | 12 | 0.5000 | 0.5000 | 0.5000 | 0.5000 |
| es | legal_concepts | 12 | 0.3333 | 0.3333 | 0.6667 | 0.4160 |
| es | organ_type_filters | 16 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| es | person_exact_phrase | 12 | 0.8333 | 0.7500 | 0.8333 | 0.8333 |
| es | procurement_do3 | 16 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| es | semantic_paraphrase | 16 | 0.3125 | 0.2917 | 0.5625 | 0.3906 |
