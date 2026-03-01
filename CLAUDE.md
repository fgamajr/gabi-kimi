# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GABI (Gerador Automático de Boletins por Inteligência Artificial) — a Python 3 web crawler and data extraction pipeline for Brazilian legal publications (primarily DOU — Diário Oficial da União). The project is transitioning from a legacy C# system (`Gabi_OLD/`, archival only) to this modular Python approach on branch `feat/pythonpipe`.

## Common Commands

```bash
# Infrastructure (PostgreSQL 16 on port 5433)
python3 infra/infra_manager.py up          # start DB
python3 infra/infra_manager.py status      # health check
python3 infra/infra_manager.py down        # stop
python3 infra/infra_manager.py reset_db    # wipe DB (destructive)
python3 infra/infra_manager.py recreate    # reset + start

# Crawler
python3 run_mock_crawl.py --config examples/mock_crawl.yaml

# Extraction & validation
python3 extract_test.py --rules examples/sources_v3_model.yaml --html <input_dir> --out <report_dir>
python3 historical_validate.py full --rules examples/sources_v3_model.yaml

# Database schema sync
python3 schema_sync.py plan --sources sources_v3.yaml
python3 schema_sync.py apply --sources sources_v3.yaml
python3 schema_sync.py verify --sources sources_v3.yaml
```

No pytest suite — testing is script/harness-driven. For crawler changes, verify with `run_mock_crawl.py` and check `total_documents=N` in output. For extraction changes, run `extract_test.py` or `historical_validate.py`.

## Architecture

### Module Map

- **`crawler/`** — YAML-driven web crawler engine
  - `engine.py`: Generic HTTP crawler with `RuntimeAdapter` protocol (adapters: `HttpRuntime`, `MockBrowser`, `FakeBrowser`)
  - `crawl_engine.py`: Mock orchestrator — loads YAML spec → executes steps → emits documents
  - `dsl_schema.py` / `dsl_loader.py` / `dsl_validator.py`: DSL dataclasses (`CrawlSpec`, `Step`, `ExtractStep`, `FollowStep`, `WaitStep`)
  - `frontier.py`: URL dedup + FIFO queue
  - `memory_budget.py` / `memory_levels.py`: Thread-safe memory governor with pressure levels
  - `observability.py`: Logfmt structured logging via `loguru`
  - `pagination_strategies.py`, `user_agent_rotator.py`: Pagination and UA rotation

- **`validation/`** — HTML extraction and validation
  - `extractor.py`: `ExtractionHarness` — splits HTML into documents, extracts fields via CSS selectors, computes identity hashes
  - `rules.py`: Loads YAML extraction rules (selectors, required fields, heuristics)
  - `html_tools.py`: Custom CSS selector matching and attribute extraction
  - `corpus_sampler.py` / `reporter.py`: Historical sampling and report generation

- **`dbsync/`** — Declarative PostgreSQL schema management
  - Flow: YAML models → `loader.py` → `planner.py` → desired state; `introspect.py` → existing state; `differ.py` → operations → `executor.py`

- **`infra/`** — Docker-based PostgreSQL appliance (`db_control.py`, `infra_manager.py`)

### Key Data Files

- `sources_v3.yaml` (646 lines): Canonical source catalog with crawler configs and entity/field definitions
- `tables.md`: Field-by-field extraction evidence for DOU (selectors, edge cases, rationale)
- `examples/`: YAML fixtures for mock crawls and data models

## Coding Conventions

- Python 3 with type hints, `from __future__ import annotations`
- 4-space indent, `snake_case` functions/variables, `PascalCase` classes
- CLI flags: `--max-articles`, `--start-year` style
- Small single-purpose modules; prefer composable helpers over large scripts
- Dependencies: `yaml`, `psycopg`, `loguru` (no requirements.txt — install manually)
- Secrets in `.env` (copy from `.env.example`), never committed

## Commit Style

Short imperative subjects (e.g., "Fix pipeline runtime bugs"). Include purpose, affected paths, commands run, and before/after behavior in PRs.
