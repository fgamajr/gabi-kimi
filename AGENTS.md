# Repository Guidelines

## Project Structure & Module Organization
- Core crawler logic lives in `crawler/` (engine, DSL loading/validation, frontier, memory controls, observability).
- Data/schema synchronization utilities are in `dbsync/` and the root helper `schema_sync.py`.
- Extraction and validation flow is in `validation/`, with runnable entrypoints at the repository root: `extract_test.py`, `historical_validate.py`, and `run_mock_crawl.py`.
- Operational infrastructure helpers are in `infra/` (`infra_manager.py`, `docker-compose.yml`).
- Example configs and fixtures live in `examples/`; canonical source catalog is `sources_v3.yaml`.
- `Gabi_OLD/` contains legacy material; treat it as archival unless a task explicitly targets it.

## Build, Test, and Development Commands
- `python3 infra/infra_manager.py up`: start local PostgreSQL appliance (port `5433`).
- `python3 infra/infra_manager.py status`: check container/DB health.
- `python3 run_mock_crawl.py --config examples/mock_crawl.yaml`: run crawler in mock mode.
- `python3 extract_test.py --rules examples/sources_v3_model.yaml --html <input_dir> --out <report_dir>`: execute extraction harness without DB.
- `python3 historical_validate.py full --rules examples/sources_v3_model.yaml`: sample and validate historical corpus.
- `python3 scripts/check_user_agent_rotation.py`: quick deterministic rotation check.

## Coding Style & Naming Conventions
- Follow existing Python style: 4-space indentation, type hints, `from __future__ import annotations` where already used.
- Use `snake_case` for modules/functions/variables, `PascalCase` for classes, and clear CLI flags (`--max-articles`, `--start-year`).
- Keep modules single-purpose; prefer small, composable helpers over large scripts.

## Testing Guidelines
- Current testing is script/harness-driven (no root `pytest` suite configured).
- Add validation coverage by extending `validation/` rules and running `extract_test.py` or `historical_validate.py`.
- For crawler changes, include at least one runnable reproduction command and expected output (for example `total_documents=...`).

## Commit & Pull Request Guidelines
- Recent history favors short, imperative commit subjects (e.g., `Fix pipeline runtime bugs`).
- Prefer specific messages over generic `Fixes`; keep subject lines concise.
- PRs should include: purpose, affected paths, commands run, and before/after behavior.
- Link related issues/tasks and attach logs/screenshots when changing operational workflows.

## Security & Configuration Tips
- Keep secrets in local `.env`; never commit credentials.
- Start from `.env.example` for new environments.
- Validate destructive DB operations (`reset_db`, `recreate`) before running on shared environments.
