> Last verified: 2026-03-06

# Search Benchmark Harness

This dev-only harness benchmarks GABI retrieval quality across backends and categories.

## What it does

- builds a stratified 100-case benchmark suite
- runs each case against one or more backends: `pg`, `es`, `hybrid`
- grades top-k results heuristically
- optionally asks an LLM judge to score a sample of cases
- writes JSON and Markdown reports under `.dev/bench/runs/`

## Files

- `.dev/bench/cases.py`: 100 benchmark cases
- `.dev/bench/grader.py`: heuristic grading
- `.dev/bench/normalization.py`: benchmark-only query/result normalization
- `.dev/bench/judge.py`: optional LLM-as-judge
- `.dev/bench/reporting.py`: report writers
- `.dev/bench/run_benchmark.py`: CLI runner

## Usage

Smoke run:

```bash
.venv/bin/python .dev/bench/run_benchmark.py --limit 6 --backends hybrid,pg
```

Full 100-case run:

```bash
.venv/bin/python .dev/bench/run_benchmark.py --backends hybrid,pg,es
```

Run with an LLM judge on a small sample:

```bash
.venv/bin/python .dev/bench/run_benchmark.py \
  --backends hybrid,pg \
  --llm-judge-agent minimax \
  --judge-sample 5
```

## Categories

- `bolsa_alimentacao`
- `procurement_do3`
- `organ_type_filters`
- `person_exact_phrase`
- `legal_concepts`
- `semantic_paraphrase`
- `broad_filter`

## Notes

- The benchmark is intentionally mixed: some cases are precise, some are semantic paraphrases.
- Benchmark grading uses a canonical row hydration step by `doc_id` so `pg`, `es`, and `hybrid` are scored on comparable document fields.
- For `organ_type_filters`, the `pg` benchmark path executes `query="*"` with the explicit filters because the case intent is filter-led and the backend is being evaluated as lexical BM25 plus structured filters, not semantic paraphrase recovery.
- The heuristic grader is deterministic and should be the default.
- The LLM judge is optional and best used as a secondary signal.
