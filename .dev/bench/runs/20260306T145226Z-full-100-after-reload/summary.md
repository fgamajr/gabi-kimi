# Hybrid Search Benchmark

- Cases: 100
- Backends: hybrid, pg, es
- Run dir: `.dev/bench/runs/20260306T145226Z-full-100-after-reload`

## Aggregate Metrics

| Backend | Cases | P@1 | P@3 | P@5 | Hits@10 | MRR | Avg Relevance |
|---|---:|---:|---:|---:|---:|---:|---:|
| hybrid | 100 | 0.9600 | 0.9000 | 0.8920 | 0.9900 | 0.9695 | 0.5127 |
| pg | 100 | 0.1700 | 0.1700 | 0.1700 | 0.1700 | 0.1700 | 0.0844 |
| es | 100 | 0.6800 | 0.6433 | 0.6340 | 0.7200 | 0.6950 | 0.3874 |

## Categories

| Backend | Category | Cases | P@1 | P@3 | Hits@10 | MRR |
|---|---|---:|---:|---:|---:|---:|
| hybrid | bolsa_alimentacao | 16 | 0.9375 | 0.8333 | 1.0000 | 0.9500 |
| hybrid | broad_filter | 12 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| hybrid | legal_concepts | 12 | 0.8333 | 0.8889 | 1.0000 | 0.8958 |
| hybrid | organ_type_filters | 16 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| hybrid | person_exact_phrase | 12 | 0.9167 | 0.8611 | 0.9167 | 0.9167 |
| hybrid | procurement_do3 | 16 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| hybrid | semantic_paraphrase | 16 | 1.0000 | 0.7292 | 1.0000 | 1.0000 |
| pg | bolsa_alimentacao | 16 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| pg | broad_filter | 12 | 0.0833 | 0.0833 | 0.0833 | 0.0833 |
| pg | legal_concepts | 12 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| pg | organ_type_filters | 16 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| pg | person_exact_phrase | 12 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| pg | procurement_do3 | 16 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| pg | semantic_paraphrase | 16 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| es | bolsa_alimentacao | 16 | 0.8750 | 0.9583 | 1.0000 | 0.9375 |
| es | broad_filter | 12 | 0.5000 | 0.5000 | 0.5000 | 0.5000 |
| es | legal_concepts | 12 | 0.8333 | 0.6389 | 0.8333 | 0.8333 |
| es | organ_type_filters | 16 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| es | person_exact_phrase | 12 | 0.8333 | 0.7778 | 0.8333 | 0.8333 |
| es | procurement_do3 | 16 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| es | semantic_paraphrase | 16 | 0.7500 | 0.6250 | 0.8750 | 0.7812 |
