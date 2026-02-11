# Agent 8 Summary: Fly.io Deployment Strategy for GABI

## Executive Summary

I have designed a comprehensive Fly.io deployment strategy for the GABI project, recommending a **Hybrid Approach (Option C)**:

- **Local Infrastructure**: Keep heavy document processing (470k docs already processed)
- **Fly.io**: Deploy API + MCP Server for serving queries (auto-scaling, global edge)
- **Managed Services**: PostgreSQL (Fly), Redis (Upstash), Elasticsearch (Elastic Cloud)

---

## Deliverables Created

### 1. Architecture Documentation
- `flyio/DEPLOYMENT_STRATEGY.md` - Complete deployment strategy with architecture diagrams
- `flyio/PRODUCTION_CHECKLIST.md` - Step-by-step production deployment checklist
- `flyio/README.md` - Operations guide for the team

### 2. fly.toml Configurations

| Service | File | Specs |
|---------|------|-------|
| **API** | `flyio/api/fly.toml` | shared-cpu-2x, 2GB, 2-10 machines |
| **MCP** | `flyio/mcp/fly.toml` | shared-cpu-2x, 1GB, 1-5 machines |
| **Worker** | `flyio/worker/fly.toml` | shared-cpu-4x, 4GB, 0-3 machines |

### 3. Deployment Scripts (all executable)
- `flyio/scripts/01-setup-infrastructure.sh` - Provision databases & apps
- `flyio/scripts/02-setup-secrets.sh` - Interactive secrets configuration
- `flyio/scripts/03-deploy.sh` - Deploy all applications
- `flyio/scripts/04-migrate-data.sh` - Data migration from local to Fly.io
- `flyio/scripts/rollback.sh` - Emergency rollback procedures
- `flyio/scripts/monitoring.sh` - Monitoring and operations dashboard

### 4. Configuration Templates
- `flyio/secrets.template.env` - Template for environment variables

### 5. Makefile Integration
Added Fly.io targets to root Makefile:
```bash
make fly-setup       # Setup infrastructure
make fly-secrets     # Configure secrets
make fly-deploy      # Deploy apps
make fly-migrate     # Migrate data
make fly-rollback    # Rollback menu
make fly-monitor     # Monitor services
make fly-status      # Check status
make fly-logs-api    # View API logs
# ... and more
```

---

## Key Recommendations

### Recommended Approach: Hybrid (Option C)

**Why not full Fly.io?**
- 470k documents already processed locally
- Heavy processing (crawling, chunking, embedding) is CPU/IO intensive
- Local infrastructure already handles bulk ingestion well

**Why not just API on Fly.io?**
- Need MCP Server for ChatTCU integration
- Workers needed for priority tasks (alerts, health checks)
- Managed services reduce operational overhead

### Resource Sizing

| Component | VM | Memory | Min | Max | Monthly Cost |
|-----------|-----|--------|-----|-----|--------------|
| API | shared-cpu-2x | 2GB | 2 | 10 | ~$15-25 |
| MCP | shared-cpu-2x | 1GB | 1 | 5 | ~$8-12 |
| Worker | shared-cpu-4x | 4GB | 0 | 3 | ~$0-30 |
| Postgres | shared-cpu-1x | - | 1 | - | ~$10-15 |
| Redis | Upstash | - | - | - | Free tier |
| Elastic Cloud | 4GB/2vCPU | 50GB | - | - | ~$50-80 |
| **Total** | | | | | **~$85-160** |

### Database Strategy

1. **PostgreSQL**: Fly Postgres (10GB, metadata only)
2. **Redis**: Upstash Redis (serverless, auto-scaling)
3. **Elasticsearch**: Elastic Cloud (managed, backups, monitoring)

### Data Migration Plan

**Phase 1**: Export local data
```bash
pg_dump local_db > metadata.sql
elasticdump --input=local_es --output=backup.json
```

**Phase 2**: Import to Fly.io
```bash
psql fly_db < metadata.sql
elasticdump --input=backup.json --output=elastic_cloud
```

**Phase 3**: Verification
- Health checks
- Document count validation
- Search API testing

### Scaling Strategy

**API**: Auto-scale on connections
- Scale up: > 50 concurrent connections
- Scale down: < 10 connections for 5 minutes

**Worker**: Scale to zero
- 0 machines when idle (saves cost)
- Scale up when tasks queued
- Max 3 machines for parallel processing

---

## Rollback Procedures

### Scenario 1: Deployment Failure
```bash
make fly-rollback  # Interactive menu
# Or manually:
fly deploy --app gabi-api --image gabi-api:previous
```

### Scenario 2: Complete Failure
```bash
make fly-rollback  # Select emergency failover
# Route DNS back to local infrastructure
```

### Scenario 3: Data Corruption
```bash
# Restore from backup
fly postgres restore --app gabi-db --from-snapshot <snapshot-id>
```

---

## Quick Start Commands

```bash
# Full deployment
make fly-setup && make fly-secrets && make fly-deploy

# Monitor
make fly-monitor

# Scale
make fly-scale-api COUNT=5

# Logs
make fly-logs-api
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Fly.io outage | Low | High | Keep local as hot standby |
| Data migration failure | Medium | High | Full backups, phased migration |
| Cost overrun | Low | Medium | Auto-scaling limits, monitoring |
| Performance degradation | Low | Medium | Load testing, scaling rules |

---

## Next Steps for Team

1. **Review** the `DEPLOYMENT_STRATEGY.md` document
2. **Create** Elastic Cloud deployment
3. **Prepare** secrets in `flyio/.secrets.env`
4. **Test** deployment in staging environment
5. **Schedule** production migration window
6. **Execute** using `PRODUCTION_CHECKLIST.md`

---

## Files Created/Modified

### New Files
- `flyio/DEPLOYMENT_STRATEGY.md`
- `flyio/PRODUCTION_CHECKLIST.md`
- `flyio/README.md`
- `flyio/api/fly.toml`
- `flyio/mcp/fly.toml`
- `flyio/worker/fly.toml`
- `flyio/secrets.template.env`
- `flyio/scripts/01-setup-infrastructure.sh`
- `flyio/scripts/02-setup-secrets.sh`
- `flyio/scripts/03-deploy.sh`
- `flyio/scripts/04-migrate-data.sh`
- `flyio/scripts/rollback.sh`
- `flyio/scripts/monitoring.sh`
- `flyio/AGENT8_SUMMARY.md`

### Modified Files
- `Makefile` - Added Fly.io targets
- `fly.toml` - Moved to backup, created symlink

---

## Recommendation

**Proceed with Hybrid Approach (Option C)**:
1. Deploy API + MCP to Fly.io immediately
2. Migrate 470k document index to Elastic Cloud
3. Keep local infrastructure for processing
4. Implement gradual cutover with DNS switch

This provides the best balance of:
- **Cost efficiency**: Pay only for serving, not processing
- **Scalability**: Auto-scale API based on demand
- **Reliability**: Managed services reduce ops burden
- **Flexibility**: Easy rollback to local if needed
