# GABI Test and Validate — Reference

- **AGENTS.md** (repo root): Build & Test Commands, Test Conventions, Database & Migrations, Common Issues.
- **Test projects:** `tests/Gabi.Api.Tests`, `tests/Gabi.Postgres.Tests`, `tests/Gabi.Architecture.Tests`, plus Discover, Fetch, Ingest, Jobs, Sync as needed.
- **Zero Kelvin:** `./tests/zero-kelvin-test.sh` — script location and options (e.g. `--source`, `--phase`, `--max-docs`).
- **Chaos / staging:** Experiments (PostgreSQL stall, tarpit, SIGTERM, DLQ replay, etc.) in `docs/reliability/CHAOS_PLAYBOOK.md`; runner `./tests/chaos-test.sh` only when `DOTNET_ENVIRONMENT` is not `Production`.

Use this file when you need exact paths or chaos test details; the main skill keeps only the commands and checklist for typical test and validation workflows.
