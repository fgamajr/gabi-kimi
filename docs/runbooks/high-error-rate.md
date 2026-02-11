# Runbook: GABI High Error Rate

**Alert:** `GABIHighErrorRate`  
**Severity:** Critical  
**Team:** Platform  

---

## Symptoms

- Error rate > 10% (HTTP 5xx responses)
- Increased latency
- Users reporting failures
- Multiple endpoints affected

---

## Immediate Actions

### 1. Identify Error Scope

```bash
# Check which endpoints are failing
curl -s https://gabi-api.tcu.gov.br/metrics | grep 'gabi_http_requests_total{status=~"5.."}'

# Breakdown by endpoint
curl -s https://gabi-api.tcu.gov.br/metrics | grep 'http_requests_total' | grep -E '5..'
```

### 2. Check Logs for Error Patterns

```bash
# Recent errors
fly logs --app gabi-api --recent | grep -i "error\|exception"

# Specific status codes
fly logs --app gabi-api | grep -E '"status_code": 5..'

# Stack traces
fly logs --app gabi-api | grep -A 10 "Traceback"
```

### 3. Check Resource Usage

```bash
# Memory and CPU
fly status --app gabi-api

# Machine-level metrics
fly machine status --app gabi-api <machine-id>
```

---

## Common Causes

### Database Issues

**Symptoms:**
- Connection timeouts
- Query timeout errors
- Pool exhaustion

**Investigation:**
```bash
# Check DB connections
curl -s https://gabi-api.tcu.gov.br/metrics | grep gabi_db_connections

# Check query latency
curl -s https://gabi-api.tcu.gov.br/metrics | grep gabi_db_query_duration
```

**Resolution:**
- Restart database if necessary
- Kill blocking queries
- Scale up connection pool

### Elasticsearch Issues

**Symptoms:**
- Search endpoint errors
- Indexing failures
- Cluster timeouts

**Investigation:**
```bash
# Check ES cluster health
curl -s https://gabi-api.tcu.gov.br/metrics | grep elasticsearch

# Direct ES check
curl <es_url>/_cluster/health
```

**Resolution:**
- Restart ES nodes
- Check disk space
- Review shard allocation

### Memory Issues

**Symptoms:**
- OOM kills
- Increasing response times
- Gradual degradation

**Investigation:**
```bash
# Check for OOM
fly logs --app gabi-api | grep -i "oom\|out of memory\|killed"

# Memory metrics
curl -s https://gabi-api.tcu.gov.br/metrics | grep memory
```

**Resolution:**
- Restart machines
- Scale up memory
- Investigate memory leaks

### Recent Deployment Issues

**Symptoms:**
- Errors started after deployment
- Specific endpoints broken
- New error types appearing

**Investigation:**
```bash
# Check recent deployments
fly releases list --app gabi-api

# Check what changed
git log --oneline <previous>..<current>

# Review recent changes
```

**Resolution:**
- Rollback to previous version
- Fix bug and redeploy

### External API Failures

**Symptoms:**
- Embedding service errors
- Parser fetch failures
- Timeout errors

**Investigation:**
```bash
# Check TEI service
curl -s https://gabi-api.tcu.gov.br/metrics | grep gabi_embedding

# Check fetcher errors
fly logs --app gabi-worker | grep -i "fetch\|timeout\|connection"
```

**Resolution:**
- Check external service status
- Add circuit breakers
- Implement fallbacks

---

## Resolution Steps

### Quick Fixes

#### Restart API
```bash
fly machine restart --app gabi-api
```

#### Scale Resources
```bash
# Scale up temporarily
fly scale memory 4096 --app gabi-api
fly scale cpus 4 --app gabi-api
```

#### Rollback Deployment
```bash
# Deploy previous version
fly deploy --app gabi-api --image <previous-sha>
```

### Database Fixes

```bash
# SSH into API machine
fly ssh console --app gabi-api

# Check DB connectivity
python -c "
import asyncio
from gabi.db import init_db
asyncio.run(init_db())
print('DB OK')
"
```

### Elasticsearch Fixes

```bash
# Check cluster status
curl <es_url>/_cluster/health?pretty

# Check index status
curl <es_url>/_cat/indices?v

# If yellow/red, check unassigned shards
curl <es_url>/_cluster/allocation/explain?pretty
```

---

## Verification

### Monitor Error Rate

```bash
# Watch error rate
watch -n 10 'curl -s https://gabi-api.tcu.gov.br/metrics | grep -E "http_requests_total.*status=\"5"'
```

### Test Endpoints

```bash
# Health check
curl https://gabi-api.tcu.gov.br/health

# Search endpoint
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query": "test", "limit": 5}' \
  https://gabi-api.tcu.gov.br/api/v1/search
```

### Check All Services

```bash
# Verify all components are healthy
curl -H "Authorization: Bearer $TOKEN" \
  https://gabi-api.tcu.gov.br/api/v1/dashboard/health
```

---

## Prevention

### Add Circuit Breakers

```python
# Example circuit breaker for external calls
from circuitbreaker import circuit

@circuit(failure_threshold=5, recovery_timeout=60)
def call_external_api():
    # API call logic
    pass
```

### Improve Error Handling

```python
# Graceful degradation
try:
    results = await search_service.search(query)
except ElasticsearchException:
    # Fallback to database search
    results = await db_search(query)
```

### Add Rate Limiting

Already implemented - verify configuration:

```yaml
# In fly.toml env
RATE_LIMIT_REQUESTS_PER_MINUTE = "60"
RATE_LIMIT_BURST = "10"
```

---

## Post-Incident Actions

1. **Analyze error logs** for root cause
2. **Add regression tests** for bug fixes
3. **Update monitoring** for early detection
4. **Document lessons learned**

---

## Related Runbooks

- [API Down](./api-down.md)
- [Database Issues](./database-issues.md)
- [Elasticsearch Degraded](./es-degraded.md)
