# Runbook: GABI Elasticsearch Degraded

**Alert:** `GABIESDegraded` or `GABIESClusterRed`  
**Severity:** Warning/Critical  
**Team:** Platform  

---

## Symptoms

- ES cluster status yellow or red
- Search performance degraded
- Indexing failures
- Slow search queries

---

## Immediate Actions

### 1. Check Cluster Health

```bash
# Direct ES check
curl $ES_URL/_cluster/health?pretty

# Via API
curl -H "Authorization: Bearer $TOKEN" \
  https://gabi-api.tcu.gov.br/api/v1/dashboard/health
```

### 2. Check Index Status

```bash
# List indices
curl $ES_URL/_cat/indices?v

# Check specific index
curl $ES_URL/gabi_documents_v1/_stats
```

### 3. Check Node Status

```bash
# Node information
curl $ES_URL/_cat/nodes?v

# Node stats
curl $ES_URL/_nodes/stats
```

---

## Investigation Steps

### Yellow Status (Degraded)

**Common causes:**
- Unassigned replica shards
- Node joining/leaving
- Temporary network issues

```bash
# Check unassigned shards
curl $ES_URL/_cat/shards?v | grep UNASSIGNED

# Get allocation explanation
curl $ES_URL/_cluster/allocation/explain?pretty
```

### Red Status (Critical)

**Common causes:**
- Primary shard unassigned
- Data node down
- Disk full
- Split brain scenario

```bash
# Check cluster state
curl $ES_URL/_cluster/state?pretty

# Check for red indices
curl $ES_URL/_cat/indices?v&health=red
```

### Disk Space Issues

```bash
# Check disk usage
curl $ES_URL/_cat/allocation?v

# Check FS stats
curl $ES_URL/_nodes/stats/fs
```

### Memory Issues

```bash
# Check JVM heap
curl $ES_URL/_nodes/stats/jvm

# Check circuit breaker
curl $ES_URL/_nodes/stats/breaker
```

---

## Resolution Steps

### For Yellow Status

#### Option 1: Wait for Recovery

ES often recovers automatically. Monitor:

```bash
watch -n 10 'curl -s $ES_URL/_cluster/health?pretty | grep status'
```

#### Option 2: Force Replica Allocation

```bash
# Temporarily reduce replica count
curl -X PUT "$ES_URL/gabi_documents_v1/_settings" \
  -H "Content-Type: application/json" \
  -d '{"index": {"number_of_replicas": 0}}'

# Then restore
curl -X PUT "$ES_URL/gabi_documents_v1/_settings" \
  -H "Content-Type: application/json" \
  -d '{"index": {"number_of_replicas": 1}}'
```

#### Option 3: Reroute Shards

```bash
# Attempt to reroute unassigned shards
curl -X POST "$ES_URL/_cluster/reroute" \
  -H "Content-Type: application/json" \
  -d '{"commands": [{"allocate_empty_primary": {"index": "gabi_documents_v1", "shard": 0, "node": "node-name", "accept_data_loss": true}}]}'
```

### For Red Status

#### Option 1: Restart ES Nodes

```bash
# If using Fly machines
fly machine restart --app gabi-es <machine-id>

# Wait for recovery
watch -n 10 'curl -s $ES_URL/_cluster/health?pretty'
```

#### Option 2: Free Disk Space

```bash
# Delete old indices (careful!)
curl -X DELETE "$ES_URL/old-index-name"

# Or clear old data
curl -X POST "$ES_URL/gabi_documents_v1/_forcemerge?max_num_segments=1"
```

#### Option 3: Recover from Snapshot

```bash
# List snapshots
curl "$ES_URL/_snapshot/backup_repo/_all"

# Restore from snapshot
curl -X POST "$ES_URL/_snapshot/backup_repo/snapshot_name/_restore" \
  -H "Content-Type: application/json" \
  -d '{"indices": "gabi_documents_v1"}'
```

### For Search Performance Issues

```bash
# Force merge to optimize segments
curl -X POST "$ES_URL/gabi_documents_v1/_forcemerge?max_num_segments=1"

# Clear cache
curl -X POST "$ES_URL/_cache/clear"

# Update refresh interval
curl -X PUT "$ES_URL/gabi_documents_v1/_settings" \
  -H "Content-Type: application/json" \
  -d '{"index": {"refresh_interval": "30s"}}'
```

---

## Verification

### Monitor Recovery

```bash
# Watch cluster health
watch -n 5 'curl -s $ES_URL/_cluster/health?pretty'

# Check shard allocation
curl $ES_URL/_cat/shards?v
```

### Test Search

```bash
# Simple search test
curl -X POST "$ES_URL/gabi_documents_v1/_search" \
  -H "Content-Type: application/json" \
  -d '{"query": {"match_all": {}}, "size": 1}'

# Via GABI API
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query": "test", "limit": 5}' \
  https://gabi-api.tcu.gov.br/api/v1/search
```

### Check Metrics

```bash
# Verify ES metrics
curl -s https://gabi-api.tcu.gov.br/metrics | grep elasticsearch
```

---

## Prevention

### Set up Index Lifecycle Management

```json
PUT _ilm/policy/gabi_policy
{
  "policy": {
    "phases": {
      "hot": {
        "actions": {
          "rollover": {
            "max_size": "10GB",
            "max_age": "7d"
          }
        }
      },
      "warm": {
        "min_age": "7d",
        "actions": {
          "shrink": {"number_of_shards": 1}
        }
      }
    }
  }
}
```

### Configure Disk Watermarks

```bash
# Set watermarks (via elasticsearch.yml or API)
curl -X PUT "$ES_URL/_cluster/settings" \
  -H "Content-Type: application/json" \
  -d '{
    "transient": {
      "cluster.routing.allocation.disk.watermark.low": "85%",
      "cluster.routing.allocation.disk.watermark.high": "90%",
      "cluster.routing.allocation.disk.watermark.flood_stage": "95%"
    }
  }'
```

### Regular Snapshots

```bash
# Create snapshot repository
curl -X PUT "$ES_URL/_snapshot/backup_repo" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "fs",
    "settings": {"location": "/backup"}
  }'

# Create snapshot
curl -X PUT "$ES_URL/_snapshot/backup_repo/snapshot_$(date +%Y%m%d)"
```

---

## Related Runbooks

- [High Error Rate](./high-error-rate.md)
- [Search Failures](./search-failures.md)
