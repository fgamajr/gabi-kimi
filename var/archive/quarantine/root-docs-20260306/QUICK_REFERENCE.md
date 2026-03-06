# GABI Quick Reference

> Last verified: 2026-03-06

## Environment

```bash
source .venv/bin/activate
cp .env.example .env
```

## Infra

```bash
.venv/bin/python infra/infra_manager.py up
.venv/bin/python infra/infra_manager.py status
.venv/bin/python infra/infra_manager.py down
```

## Schemas

```bash
PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi -f dbsync/registry_schema.sql
PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi -f dbsync/dou_schema.sql
PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi -f dbsync/bm25_schema.sql
.venv/bin/python schema_sync.py verify --sources sources_v3.yaml
```

## Ingestion

```bash
.venv/bin/python -m ingest.sync_pipeline --refresh-catalog
.venv/bin/python -m ingest.sync_pipeline --start 2002-01 --end 2002-12
.venv/bin/python -m ingest.bulk_pipeline --start 2002-01-01 --end 2002-01-31 --seal
```

## BM25

```bash
.venv/bin/python -m ingest.bm25_indexer build
.venv/bin/python -m ingest.bm25_indexer refresh
.venv/bin/python -m ingest.bm25_indexer stats
```

## Elasticsearch

```bash
.venv/bin/python -m ingest.es_indexer backfill --recreate-index
.venv/bin/python -m ingest.es_indexer sync
.venv/bin/python -m ingest.es_indexer stats
```

## Chunks and Embeddings

```bash
.venv/bin/python scripts/backfill_chunks.py --batch-size 1500 --date-from 2002-01-01 --date-to 2002-12-31
.venv/bin/python -m ingest.embedding_pipeline create-index --recreate-index
.venv/bin/python -m ingest.embedding_pipeline backfill --batch-size 1024
.venv/bin/python -m ingest.embedding_pipeline stats
```

## Web and MCP

```bash
.venv/bin/python web_server.py --port 8000
.venv/bin/python mcp_es_server.py
.venv/bin/python mcp_server.py
```

## Tests

```bash
.venv/bin/python tests/test_commitment.py
.venv/bin/python tests/test_bulk_pipeline.py
.venv/bin/python tests/test_dou_ingest.py
.venv/bin/python tests/test_seal_roundtrip.py
.venv/bin/python tests/test_search_adapters.py
```

## Automation

```bash
./scripts/daily_sync.sh
./scripts/daily_sync.sh --dry-run
.venv/bin/python -m ingest.orchestrator --days 1 --dry-run
```
