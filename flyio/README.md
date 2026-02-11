# GABI Fly.io Deployment

Complete Fly.io deployment configuration for GABI (Gerador Automático de Boletins por IA).

## Architecture Overview

This deployment uses a **Hybrid Approach**:
- **Fly.io**: API + MCP Server for serving queries (auto-scaling, global edge)
- **Local**: Heavy document processing pipeline (470k docs already processed)
- **Managed Services**: PostgreSQL (Fly), Redis (Upstash), Elasticsearch (Elastic Cloud)

## Quick Start

### Prerequisites

```bash
# Install fly CLI
curl -L https://fly.io/install.sh | sh

# Authenticate
fly auth login
```

### Full Deployment

```bash
# 1. Setup infrastructure
make fly-setup

# 2. Configure secrets
cp flyio/secrets.template.env flyio/.secrets.env
# Edit flyio/.secrets.env with your values
source flyio/.secrets.env
make fly-secrets

# 3. Deploy applications
make fly-deploy

# 4. Migrate data
make fly-migrate
```

## Directory Structure

```
flyio/
├── README.md                    # This file
├── DEPLOYMENT_STRATEGY.md       # Detailed architecture and strategy
├── secrets.template.env         # Template for environment secrets
├── api/
│   └── fly.toml                # API service configuration
├── mcp/
│   └── fly.toml                # MCP server configuration
├── worker/
│   └── fly.toml                # Celery worker configuration
└── scripts/
    ├── 01-setup-infrastructure.sh  # Provision databases & apps
    ├── 02-setup-secrets.sh         # Configure secrets
    ├── 03-deploy.sh                # Deploy applications
    ├── 04-migrate-data.sh          # Data migration
    ├── rollback.sh                 # Rollback procedures
    └── monitoring.sh               # Monitoring & operations
```

## Configuration

### API (gabi-api)

- **Port**: 8000
- **Min Machines**: 2 (HA)
- **Max Machines**: 10 (auto-scale)
- **VM**: shared-cpu-2x, 2GB RAM
- **Endpoints**:
  - `https://gabi-api.fly.dev/health` - Health check
  - `https://gabi-api.fly.dev/api/v1/search` - Search API
  - `https://gabi-api.fly.dev/metrics` - Prometheus metrics

### MCP Server (gabi-mcp)

- **Port**: 8001
- **Min Machines**: 1
- **Max Machines**: 5
- **VM**: shared-cpu-2x, 1GB RAM
- **Endpoints**:
  - `https://gabi-mcp.fly.dev/health` - Health check
  - `https://gabi-mcp.fly.dev/mcp/sse` - MCP SSE endpoint

### Worker (gabi-worker)

- **No HTTP** (internal only)
- **Min Machines**: 0 (scale to zero)
- **Max Machines**: 3
- **VM**: shared-cpu-4x, 4GB RAM
- **Queues**: `gabi.default`, `gabi.sync.high`, `gabi.health`, `gabi.alerts`

**Note**: Heavy processing (bulk ingestion) runs locally, not on Fly.io workers.

## Useful Commands

### Deployment

```bash
# Full deployment
make fly-deploy

# Deploy individual components
make fly-deploy-api
make fly-deploy-mcp
make fly-deploy-worker

# Check status
make fly-status

# View logs
make fly-logs-api
make fly-logs-mcp
make fly-logs-worker
```

### Scaling

```bash
# Scale API to 3 machines
make fly-scale-api COUNT=3

# Scale Worker to 2 machines
make fly-scale-worker COUNT=2

# Manual scaling
fly scale count 5 --app gabi-api
```

### Database

```bash
# Connect to PostgreSQL
make fly-db-connect

# Start local proxy (for pgAdmin, etc.)
make fly-db-proxy
# Then connect to: postgresql://localhost:5433/gabi
```

### SSH Access

```bash
# SSH into containers
make fly-ssh-api
make fly-ssh-mcp
make fly-ssh-worker
```

### Monitoring

```bash
# Interactive monitoring
make fly-monitor

# Or use individual commands:
./flyio/scripts/monitoring.sh health    # Health check
./flyio/scripts/monitoring.sh status    # Full status
./flyio/scripts/monitoring.sh metrics   # Show metrics
./flyio/scripts/monitoring.sh perf      # Performance test
./flyio/scripts/monitoring.sh search    # Test search API
./flyio/scripts/monitoring.sh dashboard # Interactive dashboard
```

## Data Migration

### From Local to Fly.io

```bash
# Export local data
./flyio/scripts/04-migrate-data.sh
# Select option 1: Export local data

# Import to Fly.io
./flyio/scripts/04-migrate-data.sh
# Select option 4: Full migration
```

### Manual Migration

```bash
# PostgreSQL
pg_dump --data-only --no-owner postgresql://localhost:5432/gabi > backup.sql
psql $FLY_DATABASE_URL < backup.sql

# Elasticsearch
elasticdump --input=http://localhost:9200/gabi_documents_v1 --output=es_backup.json
elasticdump --input=es_backup.json --output=$FLY_ELASTICSEARCH_URL/gabi_documents_v1
```

## Rollback

```bash
# Interactive rollback menu
make fly-rollback

# Emergency procedures:
# 1. Rollback to previous version
# 2. Stop all services (emergency stop)
# 3. Failover to local infrastructure
# 4. Restore database from backup
```

## Cost Estimation

| Component | Specs | Monthly Cost |
|-----------|-------|--------------|
| gabi-api | 2x shared-cpu-2x @ 2GB | ~$15-25 |
| gabi-mcp | 1x shared-cpu-2x @ 1GB | ~$8-12 |
| gabi-worker | 0-3x shared-cpu-4x @ 4GB | ~$0-30 |
| Fly Postgres | 1x shared-cpu-1x, 10GB | ~$10-15 |
| Upstash Redis | 10K req/day | Free tier |
| Elastic Cloud | 4GB/2vCPU, 50GB | ~$50-80 |
| **Total** | | **~$85-160/month** |

## Troubleshooting

### App Won't Start

```bash
# Check logs
fly logs --app gabi-api

# Check secrets
fly secrets list --app gabi-api

# SSH and debug
fly ssh console --app gabi-api
# Inside container:
uvicorn gabi.main:app --host 0.0.0.0 --port 8000 --log-level debug
```

### Database Connection Issues

```bash
# Test connection
fly postgres connect --app gabi-db

# Check status
fly status --app gabi-db

# Restart if needed
fly apps restart gabi-db
```

### High Memory Usage

```bash
# Check metrics
fly metrics --app gabi-api

# Scale up
fly scale memory 4096 --app gabi-api

# Or reduce workers
fly scale count 1 --app gabi-api
```

## Security

1. **Secrets**: All credentials stored in `fly secrets` (encrypted at rest)
2. **Network**: Internal communication via Fly.io private network
3. **HTTPS**: Automatic TLS termination
4. **Auth**: JWT validation via external Keycloak
5. **Rate Limiting**: Configured in app + Fly.io proxy

## Support

- [Fly.io Documentation](https://fly.io/docs/)
- [Fly.io Status](https://status.fly.io/)
- Internal: Contact GABI team

## License

TCU Internal Use Only
