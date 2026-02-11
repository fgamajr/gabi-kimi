# GABI Fly.io Deployment Strategy

## Executive Summary

**Recommended Approach: Hybrid (Option C)**
- **Local**: Document processing pipeline (470k docs already processed)
- **Fly.io**: API + MCP Server for serving queries
- **Managed Services**: PostgreSQL (Fly), Elasticsearch (Elastic Cloud), Redis (Upstash)

---

## Architecture Decision

### Why Hybrid?

| Factor | Local Processing | Fly.io Serving |
|--------|-----------------|----------------|
| **470k Documents** | Already processed ✓ | Only search index needed |
| **Data Volume** | ~180KB ES data (small) | Easily migratable |
| **Processing** | CPU/IO intensive | Keep local |
| **Serving** | Low latency not critical | Global edge, auto-scale |
| **Cost** | Use existing hardware | Pay for serving only |

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         FLY.IO                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  gabi-api    │  │ gabi-mcp     │  │  gabi-worker (lite)  │  │
│  │  (FastAPI)   │  │ (MCP Server) │  │  (priority tasks)    │  │
│  │  Port: 8000  │  │ Port: 8001   │  │                      │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                  │                      │              │
│         └──────────────────┼──────────────────────┘              │
│                            │                                     │
│  ┌─────────────────────────┼───────────────────────────────┐    │
│  │              Fly.io Internal Network                      │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │    │
│  │  │ Fly Postgres │  │ Upstash Redis│  │  (ES Proxy)  │    │    │
│  │  │  (Metadata)  │  │ (Celery/Cache)│  │              │    │    │
│  │  └──────────────┘  └──────────────┘  └──────────────┘    │    │
│  └──────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTPS
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    EXTERNAL SERVICES                            │
│  ┌──────────────────┐  ┌──────────────────────────────────┐    │
│  │  Elastic Cloud   │  │         Keycloak TCU              │    │
│  │  (470k docs idx) │  │         (Auth/JWT)                │    │
│  │  Search/Analytics│  │                                   │    │
│  └──────────────────┘  └──────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     LOCAL (On-Premise)                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │         Processing Pipeline (Heavy Workloads)            │   │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐           │   │
│  │  │  Crawler   │ │  Chunker   │ │  Embedder  │  (TEI)    │   │
│  │  │  Fetcher   │ │  Parser    │ │  Indexer   │           │   │
│  │  └────────────┘ └────────────┘ └────────────┘           │   │
│  │                                                          │   │
│  │  Use: Bulk ingestion, reprocessing, ML training          │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Resource Sizing & Scaling

### gabi-api (FastAPI)

| Metric | Value | Rationale |
|--------|-------|-----------|
| **VM** | shared-cpu-2x | Good for API serving |
| **Memory** | 2GB | FastAPI + asyncpg + overhead |
| **Min Machines** | 2 | High availability |
| **Max Machines** | 10 | Auto-scale on load |
| **Concurrency** | 50 soft / 100 hard | Connection-based |

### gabi-mcp (MCP Server)

| Metric | Value | Rationale |
|--------|-------|-----------|
| **VM** | shared-cpu-2x | SSE connections |
| **Memory** | 1GB | Lower than API |
| **Min Machines** | 1 | Can scale to 0 if needed |
| **Max Machines** | 5 | MCP has sticky sessions |

### gabi-worker (Priority Tasks Only)

| Metric | Value | Rationale |
|--------|-------|-----------|
| **VM** | shared-cpu-4x | Celery task processing |
| **Memory** | 4GB | For large document handling |
| **Min Machines** | 0 | Scale to 0 when idle |
| **Max Machines** | 3 | Process urgent tasks |

**Note**: Heavy processing (bulk ingestion, reindexing) runs locally

---

## Database Strategy

### PostgreSQL: Fly Postgres

```
fly postgres create --name gabi-db --region gru --initial-cluster-size 1 --vm-size shared-cpu-1x --volume-size 10
```

- **Size**: 10GB (metadata only, documents in ES)
- **HA**: Single node (can upgrade to 2-node HA later)
- **Backups**: Daily automated
- **Connection pooling**: Via asyncpg

### Redis: Upstash Redis (Recommended)

```
fly ext redis create --name gabi-redis --region gru
```

- **Why Upstash**: Serverless, auto-scaling, pay-per-request
- **Use**: Celery broker, cache, rate limiting
- **Alternative**: Fly Redis if predictable traffic

### Elasticsearch: Elastic Cloud

```
# Deployment template
Region: Brazil (São Paulo)
Tier: Standard
Size: 4GB RAM / 2 vCPU (2 zones for HA)
Storage: 50GB (expandable)
```

- **Why Elastic Cloud**: Managed, backups, monitoring
- **Migration**: Use elasticdump or reindex API
- **Cost**: ~$50-80/month vs managing own cluster

---

## Data Migration Plan

### Phase 1: Pre-Migration (Local)

```bash
# 1. Export PostgreSQL metadata
pg_dump --data-only --no-owner --no-privileges \
  -h localhost -U gabi gabi > gabi_metadata.sql

# 2. Export Elasticsearch index (470k docs)
# Using elasticdump or native snapshot
elasticdump \
  --input=http://localhost:9200/gabi_documents_v1 \
  --output=gabi_documents_backup.json \
  --type=data

# 3. Verify data integrity
wc -l gabi_documents_backup.json
du -sh gabi_documents_backup.json
```

### Phase 2: Infrastructure Setup (Fly.io)

```bash
# Deploy in order:
1. Fly Postgres
2. Upstash Redis  
3. Elasticsearch (Elastic Cloud)
4. gabi-api
5. gabi-mcp
6. gabi-worker
```

### Phase 3: Data Import

```bash
# 1. Import PostgreSQL
psql $FLY_DATABASE_URL < gabi_metadata.sql

# 2. Import Elasticsearch
echo "Using Elastic Cloud Console or API"
# Upload gabi_documents_backup.json via Kibana or API

# 3. Verify
fly ssh console --app gabi-api
# Run health checks and sample queries
```

### Phase 4: Validation & Cutover

```bash
# 1. Parallel running (verify consistency)
# 2. Update DNS/load balancer
# 3. Monitor for 24-48h
# 4. Decommission local API serving
```

---

## Cost Estimation (Monthly)

### Fly.io Resources

| Service | Specs | Cost |
|---------|-------|------|
| gabi-api | 2x shared-cpu-2x @ 2GB, 24/7 | ~$15-25 |
| gabi-mcp | 1x shared-cpu-2x @ 1GB, 24/7 | ~$8-12 |
| gabi-worker | 0-3x shared-cpu-4x @ 4GB | ~$0-30 |
| Fly Postgres | 1x shared-cpu-1x, 10GB | ~$10-15 |
| **Fly Subtotal** | | **~$35-80** |

### External Services

| Service | Specs | Cost |
|---------|-------|------|
| Upstash Redis | 10K req/day | Free tier |
| Elastic Cloud | 4GB/2vCPU, 50GB | ~$50-80 |
| **External Subtotal** | | **~$50-80** |

### Total Estimated Cost

| Scenario | Monthly Cost |
|----------|--------------|
| **Minimal** (dev/staging) | ~$35 |
| **Production** (steady state) | ~$85-160 |
| **Production** (peak load) | ~$120-200 |

**Note**: Much cheaper than running full infrastructure 24/7 locally

---

## Rollback Procedures

### Scenario 1: Deployment Failure

```bash
# Rollback to previous version
fly deploy --app gabi-api --image gabi-api:previous

# Or rollback migration
fly ssh console --app gabi-api
alembic downgrade -1
```

### Scenario 2: Data Corruption

```bash
# 1. Stop writes
fly scale count 0 --app gabi-worker

# 2. Restore from backup
# - Fly Postgres: Use fly postgres restore
# - Elasticsearch: Restore from snapshot

# 3. Verify and resume
fly scale count 1 --app gabi-worker
```

### Scenario 3: Complete Service Failure

```bash
# Emergency: Route traffic to local instance
curl -X POST "https://dns-provider.com/switch" \
  -d '{"domain": "gabi.tcu.gov.br", "target": "local-ip"}'

# Keep local infrastructure as hot standby for critical period
```

---

## Monitoring & Alerting

### Fly.io Native

```bash
# View logs
fly logs --app gabi-api

# View metrics
fly metrics --app gabi-api

# Status
fly status --app gabi-api
```

### Custom Health Checks

```bash
# API Health
curl https://gabi-api.fly.dev/health

# MCP Health  
curl https://gabi-mcp.fly.dev/health

# Search validation
curl -X POST https://gabi-api.fly.dev/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "limit": 1}'
```

---

## Security Considerations

1. **Secrets**: All credentials in `fly secrets`, never in code
2. **Network**: Internal communication via Fly.io private network
3. **Auth**: JWT validation via Keycloak (external)
4. **HTTPS**: Enforced by Fly.io (automatic TLS)
5. **Rate Limiting**: Configured in app + Fly.io proxy

---

## Next Steps

1. [ ] Create Fly.io apps using provided scripts
2. [ ] Provision databases and caches
3. [ ] Deploy with `make fly-deploy`
4. [ ] Run data migration
5. [ ] Configure DNS and SSL
6. [ ] Set up monitoring
7. [ ] Document operational runbooks
