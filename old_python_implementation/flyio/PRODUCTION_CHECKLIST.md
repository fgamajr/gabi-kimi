# GABI Fly.io Production Deployment Checklist

## Pre-Deployment

### ✅ Prerequisites

- [ ] Fly.io account created and CLI installed
- [ ] Authenticated with `fly auth login`
- [ ] Local data backup completed
- [ ] Elasticsearch index verified (470k documents)
- [ ] DNS records prepared (gabi.tcu.gov.br)
- [ ] SSL certificates ready (Fly.io provides automatic TLS)

### ✅ Configuration

- [ ] `flyio/secrets.env` created from template
- [ ] PostgreSQL connection string verified
- [ ] Redis (Upstash) connection string verified
- [ ] Elasticsearch (Elastic Cloud) URL and credentials verified
- [ ] OpenAI API key obtained (for embeddings)
- [ ] JWT/Keycloak endpoints verified
- [ ] CORS origins configured for production domains

## Deployment Steps

### Phase 1: Infrastructure (10 minutes)

```bash
make fly-setup
```

- [ ] Fly PostgreSQL created (`gabi-db`)
- [ ] Upstash Redis created (`gabi-redis`)
- [ ] Applications created (`gabi-api`, `gabi-mcp`, `gabi-worker`)
- [ ] Volumes created (`gabi_uploads`, `gabi_worker_data`)

### Phase 2: Secrets (5 minutes)

```bash
make fly-secrets
```

- [ ] Database URL configured
- [ ] Redis URL configured
- [ ] Elasticsearch credentials configured
- [ ] OpenAI API key configured
- [ ] JWT settings configured
- [ ] Verify: `fly secrets list --app gabi-api`

### Phase 3: Deploy Applications (15 minutes)

```bash
make fly-deploy
```

- [ ] API deployed and healthy
- [ ] MCP deployed and healthy
- [ ] Worker deployed (may be scaled to 0)
- [ ] Database migrations applied
- [ ] Health checks passing

### Phase 4: Data Migration (30-60 minutes)

```bash
make fly-migrate
```

- [ ] PostgreSQL metadata exported locally
- [ ] PostgreSQL metadata imported to Fly
- [ ] Elasticsearch snapshot created locally
- [ ] Elasticsearch data restored to Elastic Cloud
- [ ] Document count verified (should be ~470k)

### Phase 5: Verification (15 minutes)

```bash
make fly-monitor
# Select: 1) Health check, 7) Search test
```

- [ ] API health check: `curl https://gabi-api.fly.dev/health`
- [ ] MCP health check: `curl https://gabi-mcp.fly.dev/health`
- [ ] Search API test: Query returns results
- [ ] Document count matches local
- [ ] No errors in logs

### Phase 6: DNS & SSL (10 minutes)

- [ ] DNS A record pointing to Fly.io IPs
- [ ] SSL certificate provisioned (automatic)
- [ ] Custom domain configured: `fly certs create gabi.tcu.gov.br --app gabi-api`
- [ ] HTTPS redirect working

### Phase 7: Monitoring Setup (15 minutes)

- [ ] Fly.io native monitoring enabled
- [ ] Health check alerts configured
- [ ] Log aggregation configured (if needed)
- [ ] Custom dashboards created (optional)

## Post-Deployment

### ✅ Validation

- [ ] End-to-end search test successful
- [ ] MCP connection test successful
- [ ] Worker task execution verified
- [ ] Rate limiting working
- [ ] Authentication working

### ✅ Documentation

- [ ] Runbook created for common issues
- [ ] On-call procedures documented
- [ ] Rollback procedures tested
- [ ] Team trained on Fly.io operations

### ✅ Optimization

- [ ] Auto-scaling behavior verified under load
- [ ] Cost tracking set up
- [ ] Resource utilization reviewed
- [ ] Backup schedules verified

## Rollback Plan

### If Deployment Fails

1. **Immediate**: Stop traffic to Fly.io
   ```bash
   make fly-rollback  # Select emergency stop
   ```

2. **DNS**: Route traffic back to local
   ```bash
   make fly-rollback  # Select failover
   ```

3. **Investigate**: Check logs and metrics
   ```bash
   make fly-logs-api
   make fly-monitor
   ```

4. **Fix**: Address issues and redeploy
   ```bash
   make fly-deploy
   ```

5. **Verify**: Confirm successful deployment

## Emergency Contacts

- Fly.io Status: https://status.fly.io/
- Fly.io Support: support@fly.io
- Internal DevOps: [your team contact]

## Success Criteria

- [ ] All health checks passing
- [ ] Search API returning results < 500ms
- [ ] No critical errors in logs
- [ ] Document count: 470,000+
- [ ] SSL certificate valid
- [ ] Custom domain working
- [ ] Monitoring alerts configured

---

**Deployment Date**: ___/___/______
**Deployed By**: ___________________
**Verified By**: ___________________
