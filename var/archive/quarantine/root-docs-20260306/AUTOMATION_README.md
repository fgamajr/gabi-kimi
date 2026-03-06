# GABI Automation Paths

> Last verified: 2026-03-06

This document covers the automation-oriented parts of the repository. It does not replace the main runbook in `README.md` or `PIPELINE.md`.

## Current Status

There are two automation styles in the tree:

1. `scripts/daily_sync.sh`
   Current lightweight operational automation for the `sync_pipeline` path.

2. `ingest/orchestrator.py` plus `config/systemd/gabi-ingest.*`
   Secondary automation path that still exists and is deployable, but is not the primary local operator workflow.

## Primary Scheduled Flow

The simplest scheduled path today is:

```text
systemd/cron -> scripts/daily_sync.sh -> ingest.sync_pipeline -> ingest.bm25_indexer refresh
```

Files involved:

- [scripts/daily_sync.sh](/home/parallels/dev/gabi-kimi/scripts/daily_sync.sh)
- [scripts/gabi-sync@.service](/home/parallels/dev/gabi-kimi/scripts/gabi-sync@.service)
- [scripts/gabi-sync@.timer](/home/parallels/dev/gabi-kimi/scripts/gabi-sync@.timer)

Run manually:

```bash
./scripts/daily_sync.sh
./scripts/daily_sync.sh --dry-run
./scripts/daily_sync.sh --no-bm25
```

## Orchestrator Path

`ingest/orchestrator.py` still exists and loads YAML configuration from:

- [config/pipeline_config.example.yaml](/home/parallels/dev/gabi-kimi/config/pipeline_config.example.yaml)
- [config/production.yaml](/home/parallels/dev/gabi-kimi/config/production.yaml)

It currently parses these fields:

- `data_dir`
- `database.dsn`
- `discovery.auto_discover`
- `discovery.lookback_days`
- `discovery.sections`
- `download.sections`
- `download.include_extras`
- `download.skip_existing`
- `ingestion.seal_commitment`
- `ingestion.sources_yaml`
- `ingestion.identity_yaml`
- `error_handling.max_retries`
- `error_handling.retry_delay_seconds`
- `reporting.generate_report`
- `reporting.report_output`

Example:

```bash
.venv/bin/python -m ingest.orchestrator --days 1 --dry-run
.venv/bin/python -m ingest.orchestrator --config config/production.yaml
```

## Deployment Helpers

The repo also contains a deployment helper for the orchestrator path:

- [scripts/deploy.sh](/home/parallels/dev/gabi-kimi/scripts/deploy.sh)
- [config/systemd/gabi-ingest.service](/home/parallels/dev/gabi-kimi/config/systemd/gabi-ingest.service)
- [config/systemd/gabi-ingest.timer](/home/parallels/dev/gabi-kimi/config/systemd/gabi-ingest.timer)

These are still coherent with the files present in the repository, but they are not the only automation path anymore.

## What To Use Today

Use:

- `ingest.sync_pipeline` for operational ingest into `dou.*`
- `scripts/daily_sync.sh` for recurring local syncs
- `ingest.orchestrator.py` only if you want the YAML-driven automation/reporting path

Do not treat the orchestrator docs as the only or primary ingest path. The search stack used by the web app and MCP servers depends on `dou.*`, BM25, Elasticsearch, chunking, and embeddings as documented in `README.md` and `PIPELINE.md`.
