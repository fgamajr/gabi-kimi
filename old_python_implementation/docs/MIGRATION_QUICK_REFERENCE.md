# GABI Migration Quick Reference

## Pre-Migration Checklist

```bash
# 1. Verify environment
export SOURCE_PG_URL="postgresql://localhost:5432/gabi"
export TARGET_PG_URL="postgres://user:pass@your-db.fly.dev:5432/gabi"
export TARGET_ES_URL="https://your-es.fly.dev"
export FLY_APP_NAME="gabi-api-prod"

# 2. Run pre-flight checks
cd scripts/migration
./01_preflight_checks.sh

# 3. Create backup
./02_backup_local.sh
```

## Migration Commands

### Option A: Full Automated Migration
```bash
./run_migration.sh
```

### Option B: Step-by-Step
```bash
# Phase 1: Check
./01_preflight_checks.sh

# Phase 2: Backup
./02_backup_local.sh

# Phase 3: PostgreSQL (2-4 hours)
./03_migrate_postgres.sh

# Phase 4: Elasticsearch (2-4 hours)
python3 04_migrate_elasticsearch.py

# Phase 5: Validate
python3 05_validate_migration.py

# Phase 6: Cutover
./06_cutover.sh
```

### Option C: Individual Phase Selection
```bash
# Run only specific phases
./run_migration.sh --phase 1 --phase 3 --phase 5

# Skip backup (if already done)
./run_migration.sh --skip-backup
```

## Monitoring Commands

### PostgreSQL
```bash
# Check row counts (source vs target)
psql $SOURCE_PG_URL -c "SELECT COUNT(*) FROM documents;"
psql $TARGET_PG_URL -c "SELECT COUNT(*) FROM documents;"

# Watch migration progress
watch -n 30 'psql $TARGET_PG_URL -c "SELECT COUNT(*) FROM documents;"'

# Check for errors
tail -f migration_*.log
```

### Elasticsearch
```bash
# Index stats
curl $TARGET_ES_URL/_cat/indices/gabi_documents_v1?v

# Document count
curl $TARGET_ES_URL/gabi_documents_v1/_count

# Health check
curl $TARGET_ES_URL/_cluster/health
```

### Fly.io
```bash
# App status
fly status --app $FLY_APP_NAME

# Logs
fly logs --app $FLY_APP_NAME

# SSH access
fly ssh console --app $FLY_APP_NAME
```

## Validation

```bash
# Full validation suite
python3 05_validate_migration.py

# Quick checks
## PostgreSQL
echo "Documents: $(psql $TARGET_PG_URL -t -c 'SELECT COUNT(*) FROM documents;' | xargs)"
echo "Chunks: $(psql $TARGET_PG_URL -t -c 'SELECT COUNT(*) FROM document_chunks;' | xargs)"

## Elasticsearch
curl -s $TARGET_ES_URL/gabi_documents_v1/_count | jq '.count'

## Cross-store consistency
python3 << 'EOF'
import asyncio
from scripts.migration.05_validate_migration import MigrationValidator
validator = MigrationValidator("$TARGET_PG_URL", "$TARGET_ES_URL")
asyncio.run(validator.validate_cross_store_consistency())
validator.report.print_report()
EOF
```

## Rollback

```bash
# Emergency rollback (switch DNS back to local)
# 1. Revert DNS records to point to local infrastructure

# 2. Resume local services
docker compose --profile all up -d

# 3. Verify local health
curl http://localhost:8000/health

# 4. Sync any new data from Fly.io (optional)
SOURCE_PG_URL=$TARGET_PG_URL TARGET_PG_URL=$SOURCE_PG_URL \
  python3 07_incremental_sync.py --once
```

## Post-Migration

```bash
# Run incremental sync once
TARGET_PG_URL=... TARGET_ES_URL=... \
  python3 07_incremental_sync.py --once

# Or run continuously (for dual-write period)
TARGET_PG_URL=... TARGET_ES_URL=... \
  python3 07_incremental_sync.py

# Monitor for 24 hours
fly logs --app $FLY_APP_NAME | grep -i error
```

## Troubleshooting

### Connection Issues
```bash
# Test PostgreSQL
pg_isready -d $TARGET_PG_URL

# Test Elasticsearch
curl -sf $TARGET_ES_URL/_cluster/health

# Test Fly.io app health
curl -sf https://$FLY_APP_NAME.fly.dev/health
```

### Slow Migration
```bash
# Increase parallel workers
PARALLEL_JOBS=8 ./03_migrate_postgres.sh

# Increase batch size
BATCH_SIZE=5000 python3 04_migrate_elasticsearch.py
```

### Validation Failures
```bash
# Re-sync specific table
pg_dump $SOURCE_PG_URL --data-only --table=documents | psql $TARGET_PG_URL

# Force re-index to ES
python3 << 'EOF'
# Delete and recreate index
# Then re-run 04_migrate_elasticsearch.py
EOF
```

## Timeline Reference

| Phase | Duration | Action If Fails |
|-------|----------|-----------------|
| Pre-flight | 5 min | Fix issues, retry |
| Backup | 30-60 min | Check disk space |
| PostgreSQL | 2-4 hours | Resume from checkpoint |
| Elasticsearch | 2-4 hours | Re-run reindex |
| Validation | 30-60 min | Fix data, re-validate |
| Cutover | 15 min | Rollback if errors >1% |

## Emergency Contacts

| Issue | Contact |
|-------|---------|
| Fly.io platform | support@fly.io |
| Migration script bugs | [Dev team] |
| Data corruption | [DBA team] |
| Network issues | [Ops team] |

## Key Files

```
/scripts/migration/
├── 01_preflight_checks.sh      # Environment validation
├── 02_backup_local.sh           # Create backups
├── 03_migrate_postgres.sh       # PG migration
├── 04_migrate_elasticsearch.py  # ES reindex
├── 05_validate_migration.py     # Validation
├── 06_cutover.sh                # DNS cutover
├── 07_incremental_sync.py       # Post-migration sync
├── run_migration.sh             # Master script
└── README.md                    # Full documentation

/docs/
├── DATA_MIGRATION_STRATEGY.md   # Complete strategy
├── MIGRATION_EXECUTIVE_SUMMARY.md
└── MIGRATION_QUICK_REFERENCE.md # This file
```
