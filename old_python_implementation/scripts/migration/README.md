# GABI Data Migration Scripts

This directory contains scripts for migrating GABI from local infrastructure to Fly.io production.

## Overview

The migration is performed in 7 phases:

1. **Pre-flight Checks** - Validate environment and prerequisites
2. **Local Backup** - Create comprehensive backups
3. **PostgreSQL Migration** - Migrate database to Fly.io
4. **Elasticsearch Migration** - Reindex documents to Fly.io ES
5. **Validation** - Verify data integrity
6. **Cutover** - Switch production traffic
7. **Incremental Sync** - Handle ongoing changes (post-migration)

## Prerequisites

- PostgreSQL client tools (psql, pg_dump)
- Python 3.11+
- Fly.io CLI (`flyctl`) with access token
- curl
- pv (progress viewer) - optional but recommended

## Configuration

Set these environment variables:

```bash
# Source (local)
export SOURCE_PG_URL="postgresql://localhost:5432/gabi"
export SOURCE_ES_URL="http://localhost:9200"

# Target (Fly.io)
export TARGET_PG_URL="postgres://user:pass@db.fly.dev:5432/gabi"
export TARGET_ES_URL="https://es.fly.dev"
export FLY_APP_NAME="gabi-api"

# Optional
export PARALLEL_JOBS=4
export BATCH_SIZE=1000
```

## Usage

### Full Migration (All Phases)

```bash
# Run all phases interactively
./run_migration.sh

# Or run phases individually:
./01_preflight_checks.sh
./02_backup_local.sh
TARGET_PG_URL=postgres://... ./03_migrate_postgres.sh
TARGET_ES_URL=https://... python3 04_migrate_elasticsearch.py
TARGET_PG_URL=... TARGET_ES_URL=... python3 05_validate_migration.py
./06_cutover.sh
```

### Post-Migration Incremental Sync

After cutover, run incremental sync to catch any late changes:

```bash
# Run once
TARGET_PG_URL=... TARGET_ES_URL=... python3 07_incremental_sync.py --once

# Run continuously (for dual-write period)
TARGET_PG_URL=... TARGET_ES_URL=... python3 07_incremental_sync.py
```

## Migration Timeline

| Phase | Duration | Cumulative |
|-------|----------|------------|
| Pre-flight | 5 min | 5 min |
| Backup | 30-60 min | 35-65 min |
| PostgreSQL | 2-4 hours | 3-5 hours |
| Elasticsearch | 2-4 hours | 5-9 hours |
| Validation | 30-60 min | 6-10 hours |
| Cutover | 15 min | 6-10 hours |

**Recommended maintenance window**: 8-12 hours

## Rollback

If issues are detected:

```bash
# Immediate rollback (switch DNS back)
# 1. Revert DNS to point to local infrastructure
# 2. Resume local ingestion jobs:
docker compose --profile all up -d

# Sync any new data from Fly.io back to local (optional)
SOURCE_PG_URL=$TARGET_PG_URL TARGET_PG_URL=$SOURCE_PG_URL python3 07_incremental_sync.py
```

## Troubleshooting

### Connection Issues

```bash
# Test PostgreSQL connection
psql $TARGET_PG_URL -c "SELECT 1"

# Test Elasticsearch
curl $TARGET_ES_URL/_cluster/health

# Test Fly.io app
fly status --app $FLY_APP_NAME
```

### Migration Speed

If migration is too slow:

1. Increase `PARALLEL_JOBS` (default: 4)
2. Use a machine with more bandwidth
3. Consider migrating during off-peak hours
4. For ES: increase `BATCH_SIZE` (default: 1000)

### Validation Failures

If validation shows discrepancies:

```bash
# Re-run specific table migration
pg_dump $SOURCE_PG_URL --data-only --table=documents | psql $TARGET_PG_URL

# Re-index specific documents to ES
python3 04_migrate_elasticsearch.py --resume-from=<document_id>
```

## Cost Estimates

### One-Time Migration

- Data transfer (100GB): $10-20
- Temporary compute: $50-100
- **Total**: $60-120

### Monthly Fly.io (Post-Migration)

- PostgreSQL (100GB): $50-80
- Elasticsearch: $30-60
- Redis: $15-30
- App + Workers: $100-140
- **Total**: $195-310/month

## Support

For issues during migration:

1. Check the validation output for specific errors
2. Review Fly.io status page: https://status.fly.io
3. Contact: [your-support-channel]
