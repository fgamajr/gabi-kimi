# GABI Pipeline Automation - Quick Reference

## Common Commands

### Discovery Operations

```bash
# Discover new publications (dry-run)
python -m ingest.auto_discovery --days 7 --dry-run

# Update discovery registry
python -m ingest.auto_discovery --days 7 --update-registry

# List discovered publications
python -m ingest.auto_discovery --list --days 30

# List only pending downloads
python -m ingest.auto_discovery --list --not-downloaded --days 30

# Export registry to JSON
python -m ingest.auto_discovery --export data/discovery.json
```

### Pipeline Operations

```bash
# Run pipeline (dry-run)
python -m ingest.orchestrator --days 1 --dry-run

# Run full pipeline
python -m ingest.orchestrator --days 1 --seal

# Run with custom config
python -m ingest.orchestrator --config config/production.yaml

# Generate report
python -m ingest.orchestrator --days 1 --report-output logs/report.json
```

### Systemd Operations

```bash
# Enable timer (run on boot)
sudo systemctl enable gabi-ingest.timer

# Start timer
sudo systemctl start gabi-ingest.timer

# Stop timer
sudo systemctl stop gabi-ingest.timer

# Check timer status
sudo systemctl status gabi-ingest.timer

# Check service status
sudo systemctl status gabi-ingest.service

# View recent logs
sudo journalctl -u gabi-ingest.service -n 100

# Follow live logs
sudo journalctl -u gabi-ingest.service -f

# Restart service
sudo systemctl restart gabi-ingest.service
```

### Database Operations

```bash
# Create download registry schema
psql "$GABI_DSN" -f dbsync/download_registry_schema.sql

# View download statistics
psql "$GABI_DSN" -c "SELECT * FROM ingest.download_statistics;"

# View pending downloads
psql "$GABI_DSN" -c "SELECT * FROM ingest.pending_downloads;"

# View recent downloads
psql "$GABI_DSN" -c "
SELECT section, publication_date, filename, download_status
FROM ingest.downloaded_zips
ORDER BY downloaded_at DESC
LIMIT 20;
"

# Create discovery registry schema
python3 -c "
from ingest.discovery_registry import PostgreSQLDiscoveryRegistry
registry = PostgreSQLDiscoveryRegistry('$GABI_DSN')
"
```

### Deployment

```bash
# Run deployment script
sudo scripts/deploy.sh

# Verify deployment
sudo systemctl status gabi-ingest.timer
sudo -u gabi /opt/gabi/.venv/bin/python -m ingest.orchestrator --days 1 --dry-run
```

## Configuration Files

| File | Purpose | Location |
|------|---------|----------|
| `config/production.yaml` | Pipeline configuration | `/opt/gabi/config/` |
| `.env` | Environment variables | `/opt/gabi/` |
| `gabi-ingest.service` | Systemd service | `/etc/systemd/system/` |
| `gabi-ingest.timer` | Systemd timer | `/etc/systemd/system/` |

## Log Files

| Log | Location | Command |
|-----|----------|---------|
| Systemd logs | journald | `journalctl -u gabi-ingest.service` |
| Pipeline reports | JSON files | `logs/pipeline_*.json` |
| PostgreSQL logs | Docker logs | `docker logs gabi-postgres` |

## Troubleshooting

### Pipeline not running

```bash
# Check if timer is enabled
sudo systemctl is-enabled gabi-ingest.timer

# Check if timer is active
sudo systemctl is-active gabi-ingest.timer

# Check next scheduled run
systemctl list-timers gabi-ingest.timer
```

### Downloads failing

```sql
-- Check failed downloads
SELECT section, publication_date, filename, error_message
FROM ingest.downloaded_zips
WHERE download_status = 'failed'
ORDER BY downloaded_at DESC
LIMIT 10;
```

### Discovery not finding publications

```bash
# Run discovery with verbose output
python -m ingest.auto_discovery --days 7 --dry-run --verbose 2>&1 | head -100

# Check catalog registry
cat data/dou_catalog_registry.json | jq '.folder_ids | keys[-5:]'
```

## Environment Variables

```bash
# Database connection
export GABI_DSN="host=localhost port=5433 dbname=gabi user=gabi password=gabi"

# Data directories
export GABI_DATA_DIR="/opt/gabi/data/inlabs"
export GABI_LOG_DIR="/opt/gabi/logs"

# Configuration
export GABI_CONFIG="/opt/gabi/config/production.yaml"
```

## Default Schedule

- **Frequency**: Daily
- **Time**: 2:00 AM (system time)
- **Randomized delay**: Up to 5 minutes (to avoid thundering herd)
- **Persistent**: Runs on boot if missed

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (check logs) |

## Key Directories

| Directory | Purpose |
|-----------|---------|
| `/opt/gabi/` | Application root |
| `/opt/gabi/data/inlabs/` | ZIP downloads |
| `/opt/gabi/logs/` | Pipeline reports |
| `/opt/gabi/config/` | Configuration files |
| `/opt/gabi/.venv/` | Python virtual environment |

## Monitoring Checklist

- [ ] Systemd timer is enabled and active
- [ ] Database is running and accessible
- [ ] Data directory has sufficient space
- [ ] Logs are being written correctly
- [ ] Reports are being generated
- [ ] No failed downloads in registry
- [ ] Commitments are being sealed

## Quick Health Check

```bash
# 1. Check systemd
sudo systemctl status gabi-ingest.timer

# 2. Check database
psql "$GABI_DSN" -c "SELECT 1"

# 3. Check disk space
df -h /opt/gabi/data

# 4. Check recent runs
sudo journalctl -u gabi-ingest.service --since "24 hours ago" | grep -E "(PHASE|PIPELINE)"

# 5. Check download stats
psql "$GABI_DSN" -c "SELECT * FROM ingest.download_statistics;"
```
