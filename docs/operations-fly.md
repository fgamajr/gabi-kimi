# GABI Fly.io Operations Guide

## Overview

This guide covers day-to-day operations for GABI running on Fly.io.

## Quick Reference

| Command | Description |
|---------|-------------|
| `fly status` | Check app status |
| `fly logs` | View logs |
| `fly ssh console` | SSH into instance |
| `fly apps restart` | Restart application |
| `fly scale count web=2` | Scale instances |

## Deployment

### Standard Deploy

```bash
./scripts/deploy-fly.sh production
```

### Deploy to Staging

```bash
./scripts/deploy-fly.sh staging
```

### Rolling Back

```bash
# List releases
fly releases list -a gabi-api

# Rollback to specific version
fly deploy --image-label v123 -a gabi-api

# Or rollback immediately
fly releases rollback v123 -a gabi-api
```

## Scaling

### Horizontal Scaling (More Instances)

```bash
# Scale API instances
fly scale count app=3 -a gabi-api

# Scale workers
fly scale count worker=5 -a gabi-api
```

### Vertical Scaling (More Resources)

```bash
# Scale VM size
fly scale vm performance-2x -a gabi-api

# Scale memory
fly scale memory 4096 -a gabi-api
```

### Autoscaling

```bash
# Enable autoscaling
fly autoscale set min=2 max=10 -a gabi-api

# Disable autoscaling
fly autoscale disable -a gabi-api
```

## Monitoring

### Logs

```bash
# Follow logs
fly logs -a gabi-api

# Logs with filter
fly logs -a gabi-api | grep ERROR

# Historical logs (last hour)
fly logs -a gabi-api --since 1h
```

### Metrics

```bash
# View metrics
fly metrics -a gabi-api

# Custom queries via Grafana
# https://fly-metrics.net/d/fly-app/fly-app
```

### Health Checks

```bash
# Check health endpoint
curl https://gabi-api.fly.dev/health

# Check metrics endpoint
curl https://gabi-api.fly.dev/metrics
```

## Database Operations

### Connect to Database

```bash
# Proxy connection
fly proxy 5432:5432 -a gabi-postgres

# Then connect locally
psql postgres://user:pass@localhost:5432/gabi

# Or direct connection
fly ssh console -a gabi-api -C "psql \$DATABASE_URL"
```

### Database Migrations

```bash
# Run migrations
fly ssh console -a gabi-api -C "python -m alembic upgrade head"

# Rollback migration
fly ssh console -a gabi-api -C "python -m alembic downgrade -1"

# Check migration status
fly ssh console -a gabi-api -C "python -m alembic current"
```

### Database Backup

```bash
# Create backup
fly volumes snapshots create vol_<id> -a gabi-postgres

# List snapshots
fly volumes snapshots list vol_<id> -a gabi-postgres
```

## Secrets Management

### View Secrets

```bash
# List secret names (not values)
fly secrets list -a gabi-api
```

### Set Secrets

```bash
# Single secret
fly secrets set SECRET_KEY=newvalue -a gabi-api

# Multiple secrets
fly secrets set \
  DB_PASSWORD=newpass \
  API_KEY=newkey \
  -a gabi-api
```

### Remove Secrets

```bash
fly secrets unset OLD_SECRET -a gabi-api
```

## Troubleshooting

### App Won't Start

```bash
# Check logs
fly logs -a gabi-api

# Check status
fly status --all -a gabi-api

# Restart
fly apps restart -a gabi-api
```

### High Memory Usage

```bash
# Check memory usage
fly status --all -a gabi-api

# Scale up memory
fly scale memory 4096 -a gabi-api

# Or scale horizontally
fly scale count app=4 -a gabi-api
```

### Slow Performance

```bash
# Check metrics
fly metrics -a gabi-api

# Check if need more workers
fly status -a gabi-api

# Scale workers
fly scale count worker=6 -a gabi-api
```

## Maintenance

### Certificate Management

```bash
# Check certificates
fly certs list -a gabi-api

# Add custom domain
fly certs add api.example.com -a gabi-api
```

### Volume Management

```bash
# List volumes
fly volumes list -a gabi-api

# Extend volume
fly volumes extend <vol_id> --size 20 -a gabi-api
```

## Emergency Procedures

### Complete Outage

1. Check Fly.io status: https://status.fly.io
2. Check app status: `fly status --all -a gabi-api`
3. Restart app: `fly apps restart -a gabi-api`
4. If needed, scale to new region: `fly scale count app=2 --region iad -a gabi-api`

### Database Issues

1. Check database status: `fly status -a gabi-postgres`
2. Check connections: `fly ssh console -a gabi-api -C "pg_isready -d \$DATABASE_URL"`
3. Restart database: `fly apps restart -a gabi-postgres`

### Security Incident

1. Rotate all secrets immediately
2. Check logs for suspicious activity
3. Consider scaling down temporarily
4. Review access logs

## Cost Optimization

```bash
# Check current usage
fly status --all -a gabi-api

# Right-size VMs
fly scale vm shared-cpu-2x -a gabi-api

# Auto-stop machines when idle
# Already configured in fly.toml: auto_stop_machines = 'stop'

# Scale down workers during off-hours
fly scale count worker=1 -a gabi-api
```

## Support

- Fly.io Documentation: https://fly.io/docs/
- Fly.io Community: https://community.fly.io
- GABI Issues: https://github.com/your-org/gabi/issues
