# GABI Rollback Scripts

This directory contains SQL scripts for safe rollback and recovery operations.

## Prerequisites

- PostgreSQL client (`psql`) installed
- Database connection configured (default: `postgresql://postgres@localhost:5433/gabi`)
- Appropriate database permissions

## Quick Start

```bash
# 1. Check current status of a source
psql -d gabi -f 01_check_source_status.sql -v source_id="'dou_publico'"

# 2. Perform rollback as needed (see below)

# 3. Validate rollback before restart
psql -d gabi -f 06_validate_rollback.sql -v source_id="'dou_publico'"

# 4. Restart pipeline via API
curl -X POST http://localhost:5100/api/v1/dashboard/sources/dou_publico/run-pipeline \
  -H "Authorization: Bearer $TOKEN"
```

## Script Reference

| Script | Purpose | Risk Level |
|--------|---------|------------|
| `01_check_source_status.sql` | View current state before rollback | Safe |
| `02_reset_job_registry.sql` | Reset stuck jobs | Low |
| `03_reset_fetch_phase.sql` | Reset fetch phase | Low-Medium |
| `04_reset_ingest_phase.sql` | Reset ingest phase | Medium |
| `05_nuclear_reset.sql` | Full source reset (transaction) | **High** |
| `06_validate_rollback.sql` | Verify rollback success | Safe |

## Common Scenarios

### Scenario 1: Job Stuck in "Running" State

```bash
# Check status
psql -d gabi -f 01_check_source_status.sql -v source_id="'dou_publico'"

# Reset job registry
psql -d gabi -f 02_reset_job_registry.sql -v source_id="'dou_publico'"

# Validate
psql -d gabi -f 06_validate_rollback.sql -v source_id="'dou_publico'"

# Restart pipeline
curl -X POST http://localhost:5100/api/v1/dashboard/sources/dou_publico/run-pipeline \
  -H "Authorization: Bearer $TOKEN"
```

### Scenario 2: Fetch Phase Failed, Need Refetch

```bash
# Check current state
psql -d gabi -f 01_check_source_status.sql -v source_id="'dou_publico'"

# Reset only failed/processing fetch items (keeps completed)
psql -d gabi -f 03_reset_fetch_phase.sql -v source_id="'dou_publico'"

# Or full reset of ALL fetch items
psql -d gabi -f 03_reset_fetch_phase.sql -v source_id="'dou_publico'" -v full_reset=true

# Validate
psql -d gabi -f 06_validate_rollback.sql -v source_id="'dou_publico'"

# Restart from fetch phase
curl -X POST http://localhost:5100/api/v1/dashboard/sources/dou_publico/phases/fetch \
  -H "Authorization: Bearer $TOKEN"
```

### Scenario 3: Ingest Phase Created Corrupt Documents

```bash
# Check documents
psql -d gabi -f 01_check_source_status.sql -v source_id="'dou_publico'"

# Reset failed/processing documents
psql -d gabi -f 04_reset_ingest_phase.sql -v source_id="'dou_publico'"

# Or reset ALL documents including completed (full re-ingest)
psql -d gabi -f 04_reset_ingest_phase.sql -v source_id="'dou_publico'" -v include_completed=true

# Validate
psql -d gabi -f 06_validate_rollback.sql -v source_id="'dou_publico'"

# Restart from ingest phase
curl -X POST http://localhost:5100/api/v1/dashboard/sources/dou_publico/phases/ingest \
  -H "Authorization: Bearer $TOKEN"
```

### Scenario 4: Complete Source Reset (Nuclear Option)

> **⚠️ WARNING**: This removes ALL data for the source. Use with extreme caution.

```bash
# First, backup the source data
pg_dump -h localhost -p 5433 -U postgres -d gabi \
  --table="discovered_links" \
  --table="fetch_items" \
  --table="documents" \
  -F c -f "backup_dou_publico_$(date +%Y%m%d_%H%M%S).dump"

# Run nuclear reset (requires manual COMMIT)
psql -d gabi -f 05_nuclear_reset.sql -v source_id="'dou_publico'"

# In psql, review the output and then:
# COMMIT;  -- to apply
# ROLLBACK; -- to cancel

# After COMMIT, validate
psql -d gabi -f 06_validate_rollback.sql -v source_id="'dou_publico'"

# Restart full pipeline
curl -X POST http://localhost:5100/api/v1/dashboard/sources/dou_publico/run-pipeline \
  -H "Authorization: Bearer $TOKEN"
```

## Safety Guidelines

1. **Always backup before major operations**:
   ```bash
   pg_dump -h localhost -p 5433 -U postgres -d gabi -F c -f "backup_$(date +%Y%m%d_%H%M%S).dump"
   ```

2. **Use transactions for destructive operations**:
   - Nuclear reset script uses explicit `BEGIN` - requires manual `COMMIT`/`ROLLBACK`
   - Other scripts are non-destructive (soft delete/reset status)

3. **Validate before restarting**:
   - Always run `06_validate_rollback.sql` before restarting pipeline
   - Check for stuck jobs, processing items, or orphaned data

4. **Check Hangfire dashboard**:
   - Visit `/hangfire` to verify no jobs are actually running
   - Cancel any orphaned Hangfire jobs before rollback

## Database Connection

Default connection assumes:
- Host: `localhost`
- Port: `5433` (matches docker-compose.yml)
- Database: `gabi`
- User: `postgres`

Override with:
```bash
psql "postgresql://user:pass@host:port/db" -f script.sql -v source_id="'dou_publico'"
```

## API Restart Commands

```bash
# Get authentication token
TOKEN=$(curl -s -X POST http://localhost:5100/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"YOUR_PASSWORD"}' | jq -r '.token')

# Run full pipeline
curl -X POST http://localhost:5100/api/v1/dashboard/sources/{source_id}/run-pipeline \
  -H "Authorization: Bearer $TOKEN"

# Run specific phase
curl -X POST http://localhost:5100/api/v1/dashboard/sources/{source_id}/phases/discovery \
  -H "Authorization: Bearer $TOKEN"

curl -X POST http://localhost:5100/api/v1/dashboard/sources/{source_id}/phases/fetch \
  -H "Authorization: Bearer $TOKEN"

curl -X POST http://localhost:5100/api/v1/dashboard/sources/{source_id}/phases/ingest \
  -H "Authorization: Bearer $TOKEN"

# Pause/Resume/Stop
curl -X POST http://localhost:5100/api/v1/dashboard/sources/{source_id}/pause \
  -H "Authorization: Bearer $TOKEN"

curl -X POST http://localhost:5100/api/v1/dashboard/sources/{source_id}/resume \
  -H "Authorization: Bearer $TOKEN"

curl -X POST http://localhost:5100/api/v1/dashboard/sources/{source_id}/stop \
  -H "Authorization: Bearer $TOKEN"
```

## Troubleshooting

### Connection Refused
```bash
# Check if PostgreSQL is running
docker-compose ps postgres

# Or connect via docker
docker-compose exec postgres psql -U postgres -d gabi
```

### Permission Denied
```sql
-- Grant necessary permissions
GRANT SELECT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO your_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO your_user;
```

### Invalid Source ID
```bash
# List available sources
psql -d gabi -c "SELECT id, name FROM source_registry WHERE enabled = true;"
```

## Support

For issues or questions:
- Check full documentation: `docs/operations/ROLLBACK_STRATEGY.md`
- Review chaos playbook: `docs/reliability/CHAOS_PLAYBOOK.md`
- Check architecture: `docs/architecture/LAYERED_ARCHITECTURE.md`
