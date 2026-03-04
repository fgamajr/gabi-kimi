# GABI Pipeline Automation

This directory contains the automated pipeline infrastructure for GABI (Gerador Automatico de Boletins por Inteligencia Artificial).

## Overview

The automated pipeline provides:

- **Automatic Discovery**: Detects new DOU publications from in.gov.br
- **Scheduled Execution**: Runs daily via systemd timers
- **Incremental Processing**: Only downloads and processes new content
- **Resilient Error Handling**: Retry logic and circuit breakers
- **Comprehensive Reporting**: JSON reports and structured logging
- **CRSS-1 Commitments**: Cryptographic sealing of each batch

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Systemd Timer (daily at 2:00 AM)                           │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│  Pipeline Orchestrator (ingest/orchestrator.py)             │
│  • Coordinates all pipeline phases                          │
│  • Handles errors and retries                               │
│  • Generates reports                                        │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│  Pipeline Phases:                                           │
│  1. Discovery → auto_discovery.py                           │
│  2. Download → zip_downloader.py                            │
│  3. Extract → zip_downloader.py                             │
│  4. Parse → xml_parser.py                                   │
│  5. Normalize → normalizer.py                               │
│  6. Ingest → registry_ingest.py                             │
│  7. Commit → CRSS-1 anchor chain                            │
└─────────────────────────────────────────────────────────────┘
```

## Components

### 1. Discovery Registry (`ingest/discovery_registry.py`)

Tracks discovered DOU publications to avoid re-discovery.

**Backends**:
- PostgreSQL (production)
- SQLite (development/testing)
- In-memory (testing)

**Key Classes**:
- `DiscoveredPublication`: Data class for publication metadata
- `DiscoveryRegistry`: Interface for registry operations
- `PostgreSQLDiscoveryRegistry`: PostgreSQL implementation
- `SQLiteDiscoveryRegistry`: SQLite implementation
- `InMemoryDiscoveryRegistry`: In-memory implementation

### 2. Auto Discovery (`ingest/auto_discovery.py`)

Automatically discovers new DOU publications from in.gov.br.

**Features**:
- Probes monthly ZIP bundles
- Detects special editions via tags API
- Compares against discovery registry
- CLI interface for manual operations

**Usage**:
```bash
# Discover new publications (dry-run)
python -m ingest.auto_discovery --days 7 --dry-run

# Update discovery registry
python -m ingest.auto_discovery --days 7 --update-registry

# List discovered publications
python -m ingest.auto_discovery --list --days 30

# Export registry to JSON
python -m ingest.auto_discovery --export data/discovery_registry.json
```

### 3. Pipeline Orchestrator (`ingest/orchestrator.py`)

Coordinates the complete ingestion pipeline.

**Features**:
- Configurable via YAML or CLI
- Phase tracking and timing
- Error handling and retries
- Report generation

**Usage**:
```bash
# Run full pipeline
python -m ingest.orchestrator --days 1 --seal

# Run with custom config
python -m ingest.orchestrator --config config/production.yaml

# Dry run (discovery only)
python -m ingest.orchestrator --days 1 --dry-run
```

### 4. Download Registry (`dbsync/download_registry_schema.sql`)

PostgreSQL schema for tracking downloaded ZIP files.

**Features**:
- Prevents re-downloading
- Tracks download status (success/failed/skipped)
- Maintains retry count
- Stores SHA-256 checksums

**Tables**:
- `ingest.downloaded_zips`: Download metadata
- `ingest.pending_downloads`: View of pending downloads
- `ingest.download_statistics`: View of download stats

**Functions**:
- `ingest.mark_download_success()`: Mark download as successful
- `ingest.mark_download_failed()`: Mark download as failed
- `ingest.is_already_downloaded()`: Check if already downloaded

### 5. Systemd Integration (`config/systemd/`)

Systemd service and timer for scheduled execution.

**Files**:
- `gabi-ingest.service`: Service definition
- `gabi-ingest.timer`: Timer definition (daily at 2:00 AM)

**Setup**:
```bash
# Copy to systemd directory
sudo cp config/systemd/gabi-ingest.* /etc/systemd/system/

# Enable and start timer
sudo systemctl enable gabi-ingest.timer
sudo systemctl start gabi-ingest.timer

# Check status
sudo systemctl status gabi-ingest.timer
sudo systemctl status gabi-ingest.service

# View logs
sudo journalctl -u gabi-ingest.service -f
```

### 6. Configuration (`config/`)

YAML configuration files for pipeline behavior.

**Files**:
- `pipeline_config.example.yaml`: Example configuration with documentation
- `production.yaml`: Production-ready configuration

**Example**:
```yaml
data_dir: "/opt/gabi/data/inlabs"

database:
  dsn: "${GABI_DSN}"

discovery:
  auto_discover: true
  lookback_days: 1

download:
  include_extras: true
  skip_existing: true

ingestion:
  seal_commitment: true
  sources_yaml: "/opt/gabi/sources_v3.yaml"
  identity_yaml: "/opt/gabi/sources_v3.identity-test.yaml"
```

## Quick Start

### 1. Setup Database

```bash
# Create discovery registry schema
python3 -c "
from ingest.discovery_registry import PostgreSQLDiscoveryRegistry
registry = PostgreSQLDiscoveryRegistry('host=localhost port=5433 dbname=gabi user=gabi password=gabi')
print('Discovery registry schema created')
"

# Create download registry schema
psql "host=localhost port=5433 dbname=gabi user=gabi password=gabi" \
    -f dbsync/download_registry_schema.sql
```

### 2. Configure Pipeline

```bash
# Copy example config
cp config/pipeline_config.example.yaml config/production.yaml

# Edit configuration
vim config/production.yaml

# Set environment variables
export GABI_DSN="host=localhost port=5433 dbname=gabi user=gabi password=gabi"
```

### 3. Test Discovery

```bash
# Discover new publications (dry-run)
python -m ingest.auto_discovery --days 7 --dry-run

# Update registry
python -m ingest.auto_discovery --days 7 --update-registry
```

### 4. Test Pipeline

```bash
# Run pipeline manually (dry-run)
python -m ingest.orchestrator --days 1 --dry-run

# Run full pipeline
python -m ingest.orchestrator --days 1 --seal
```

### 5. Setup Scheduled Execution

```bash
# Copy systemd files
sudo cp config/systemd/gabi-ingest.* /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable and start timer
sudo systemctl enable gabi-ingest.timer
sudo systemctl start gabi-ingest.timer

# Check status
sudo systemctl status gabi-ingest.timer
```

## Monitoring

### View Discovery Registry

```bash
# List all discovered publications
python -m ingest.auto_discovery --list --days 30

# List only pending downloads
python -m ingest.auto_discovery --list --not-downloaded --days 30
```

### View Download Registry

```sql
-- View download statistics
SELECT * FROM ingest.download_statistics;

-- View pending downloads
SELECT * FROM ingest.pending_downloads;

-- View recent downloads
SELECT section, publication_date, filename, download_status, downloaded_at
FROM ingest.downloaded_zips
ORDER BY downloaded_at DESC
LIMIT 20;
```

### View Systemd Logs

```bash
# View recent pipeline runs
sudo journalctl -u gabi-ingest.service --since "24 hours ago"

# Follow live logs
sudo journalctl -u gabi-ingest.service -f

# View timer logs
sudo journalctl -u gabi-ingest.timer
```

### View Reports

```bash
# List generated reports
ls -lh logs/pipeline_*.json

# View latest report
cat logs/pipeline_$(date +%Y-%m-%d)*.json | jq .
```

## Troubleshooting

### Pipeline Fails to Start

**Check systemd status**:
```bash
sudo systemctl status gabi-ingest.service
```

**Check logs**:
```bash
sudo journalctl -u gabi-ingest.service -n 100
```

**Common issues**:
- Database not running: `sudo systemctl status postgresql`
- Incorrect DSN in config
- Missing Python dependencies

### Downloads Failing

**Check download registry**:
```sql
SELECT section, publication_date, filename, download_status, error_message
FROM ingest.downloaded_zips
WHERE download_status = 'failed'
ORDER BY downloaded_at DESC
LIMIT 10;
```

**Manual retry**:
```bash
python -m ingest.orchestrator --days 1 --no-auto-discover
```

### Discovery Not Finding New Publications

**Check discovery probe**:
```bash
python -m ingest.auto_discovery --days 7 --dry-run --verbose
```

**Check catalog registry**:
```bash
cat data/dou_catalog_registry.json | jq '.folder_ids | keys[-5:]'
```

## Future Enhancements

### Phase 2 (Planned)

- [ ] Parallel downloads
- [ ] Incremental parsing (skip already-parsed XML)
- [ ] Delta commitments (commit only new records)
- [ ] Web UI dashboard
- [ ] REST API for pipeline control

### Phase 3 (Planned)

- [ ] Multi-source ingestion (other official gazettes)
- [ ] NLP enrichment (entity extraction, topic modeling)
- [ ] Search index (Elasticsearch/Meilisearch)
- [ ] Data export (CSV, JSON, RDF)
- [ ] Blockchain anchoring

## Development

### Running Tests

```bash
# Test discovery registry
python3 -c "
from ingest.discovery_registry import InMemoryDiscoveryRegistry
from datetime import date, datetime

registry = InMemoryDiscoveryRegistry()
print('✓ In-memory registry works')

# Test add publication
from ingest.discovery_registry import DiscoveredPublication
pub = DiscoveredPublication(
    section='do1',
    publication_date=date(2026, 3, 1),
    edition_number='',
    edition_type='regular',
    folder_id=123456,
    filename='S01032026.zip',
    file_size=1234567,
    discovered_at=datetime.now(),
)
registry.add_publication(pub)
print('✓ Add publication works')

# Test get publication
retrieved = registry.get_publication('do1', date(2026, 3, 1), 'S01032026.zip')
print(f'✓ Get publication works: {retrieved.section}')
"

# Test orchestrator (dry-run)
python -m ingest.orchestrator --days 1 --dry-run
```

### Adding New Features

1. **Update discovery probe**: Modify `ingest/auto_discovery.py`
2. **Update orchestrator**: Modify `ingest/orchestrator.py`
3. **Update configuration schema**: Modify `config/pipeline_config.example.yaml`
4. **Update documentation**: Update this README
5. **Test thoroughly**: Run manual tests before deploying

## Support

For issues or questions:
1. Check this README and troubleshooting section
2. Review systemd logs: `sudo journalctl -u gabi-ingest.service`
3. Check database logs: `docker logs gabi-postgres`
4. Open an issue on the repository
