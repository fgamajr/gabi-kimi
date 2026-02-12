# GABI Troubleshooting Guide

## Quick Diagnostics

```bash
# System overview
kubectl get pods -n gabi
kubectl top pods -n gabi
kubectl get events -n gabi --sort-by='.lastTimestamp'

# API health
curl -s https://api.gabi.example.com/health | jq .
curl -s https://api.gabi.example.com/ready | jq .

# Metrics
curl -s https://api.gabi.example.com/metrics
```

## Common Issues

### API Issues

#### 500 Internal Server Error

**Symptoms**: HTTP 500 responses

**Diagnosis**:
```bash
# Check recent errors
kubectl logs -n gabi -l app=gabi-api --tail=100 | grep ERROR

# Check specific pod
kubectl logs gabi-api-xxx -n gabi --previous

# Check resource usage
kubectl top pod gabi-api-xxx -n gabi
```

**Common Causes**:
- Database connection pool exhausted
- Out of memory
- External API (OpenAI) failure
- Misconfiguration

**Solutions**:
```bash
# Restart pods
kubectl rollout restart deployment/gabi-api -n gabi

# Scale up if needed
kubectl scale deployment/gabi-api --replicas=5 -n gabi

# Check database connections
kubectl exec -it postgres-0 -n gabi -- psql -U gabi_user -c "SELECT count(*) FROM pg_stat_activity;"
```

#### High Latency

**Symptoms**: Response times > 2s

**Diagnosis**:
```bash
# Check database performance
kubectl exec -it postgres-0 -n gabi -- psql -U gabi_user -c "
SELECT query, mean_time, calls 
FROM pg_stat_statements 
ORDER BY mean_time DESC 
LIMIT 10;
"

# Check Elasticsearch
kubectl exec -it elasticsearch-0 -n gabi -- curl -s localhost:9200/_cluster/health

# Check worker queue
kubectl exec -it deploy/gabi-worker -n gabi -- celery -A src.tasks.celery_app inspect active
```

**Solutions**:
- Optimize slow queries
- Scale Elasticsearch cluster
- Add indexes if missing
- Review caching strategy

#### Memory Issues

**Symptoms**: OOMKilled, high memory usage

**Diagnosis**:
```bash
# Check memory usage
kubectl top pods -n gabi --sort-by=memory

# Check OOM events
kubectl get events -n gabi | grep -i oom

# Check container limits
kubectl describe pod gabi-api-xxx -n gabi | grep -A5 "Limits"
```

**Solutions**:
```bash
# Increase memory limits
kubectl patch deployment gabi-api -n gabi -p '{"spec":{"template":{"spec":{"containers":[{"name":"api","resources":{"limits":{"memory":"8Gi"}}}]}}}}'

# Optimize memory usage (review application logs)
# Scale horizontally to distribute load
kubectl scale deployment/gabi-api --replicas=6 -n gabi
```

### Database Issues

#### Connection Errors

**Symptoms**: "could not connect to database", connection timeouts

**Diagnosis**:
```bash
# Check connection count
kubectl exec -it postgres-0 -n gabi -- psql -U gabi_user -c "
SELECT state, count(*) 
FROM pg_stat_activity 
GROUP BY state;
"

# Check max connections
kubectl exec -it postgres-0 -n gabi -- psql -U gabi_user -c "SHOW max_connections;"

# Check active connections by application
kubectl exec -it postgres-0 -n gabi -- psql -U gabi_user -c "
SELECT application_name, count(*) 
FROM pg_stat_activity 
WHERE state = 'active' 
GROUP BY application_name;
"
```

**Solutions**:
- Increase max_connections in postgres config
- Reduce connection pool size in application
- Kill idle connections if safe
- Scale application to reduce per-instance connections

#### Slow Queries

**Diagnosis**:
```sql
-- Find slow queries
SELECT query, calls, mean_time, total_time
FROM pg_stat_statements
WHERE mean_time > 100  -- queries taking > 100ms
ORDER BY mean_time DESC
LIMIT 20;

-- Check table bloat
SELECT schemaname, tablename, n_dead_tup, n_live_tup
FROM pg_stat_user_tables
WHERE n_dead_tup > 1000
ORDER BY n_dead_tup DESC;

-- Check missing indexes
SELECT schemaname, tablename, seq_scan, seq_tup_read, idx_scan
FROM pg_stat_user_tables
WHERE seq_scan > 0
ORDER BY seq_tup_read DESC;
```

**Solutions**:
- Add missing indexes
- Vacuum analyze tables
- Optimize queries
- Update table statistics

### Elasticsearch Issues

#### Cluster Health Red/Yellow

**Diagnosis**:
```bash
# Check cluster health
kubectl exec -it elasticsearch-0 -n gabi -- curl -s localhost:9200/_cluster/health?pretty

# Check unassigned shards
kubectl exec -it elasticsearch-0 -n gabi -- curl -s localhost:9200/_cluster/allocation/explain?pretty

# Check disk usage
kubectl exec -it elasticsearch-0 -n gabi -- curl -s localhost:9200/_cat/allocation?v
```

**Solutions**:
```bash
# Force reallocation
kubectl exec -it elasticsearch-0 -n gabi -- curl -XPOST localhost:9200/_cluster/reroute?retry_failed

# Reduce replica count temporarily
kubectl exec -it elasticsearch-0 -n gabi -- curl -XPUT localhost:9200/documents/_settings -H 'Content-Type: application/json' -d '{"index": {"number_of_replicas": 0}}'

# Add more nodes if disk full
kubectl scale statefulset elasticsearch --replicas=4 -n gabi
```

#### Search Performance Issues

**Diagnosis**:
```bash
# Check slow logs
kubectl logs -n gabi -l app=elasticsearch | grep "took"

# Check query cache
kubectl exec -it elasticsearch-0 -n gabi -- curl -s localhost:9200/_nodes/stats/indices/query_cache?pretty

# Check field data cache
kubectl exec -it elasticsearch-0 -n gabi -- curl -s localhost:9200/_nodes/stats/indices/fielddata?pretty
```

### Worker/Celery Issues

#### Tasks Not Processing

**Diagnosis**:
```bash
# Check worker status
kubectl exec -it deploy/gabi-worker -n gabi -- celery -A src.tasks.celery_app inspect stats

# Check queue lengths
kubectl exec -it deploy/gabi-worker -n gabi -- celery -A src.tasks.celery_app inspect scheduled
kubectl exec -it deploy/gabi-worker -n gabi -- celery -A src.tasks.celery_app inspect reserved

# Check for blocked tasks
kubectl exec -it deploy/gabi-worker -n gabi -- celery -A src.tasks.celery_app inspect active

# Check Redis
kubectl exec -it deploy/redis -n gabi -- redis-cli -a $(kubectl get secret gabi-secrets -n gabi -o jsonpath='{.data.REDIS_PASSWORD}' | base64 -d) LLEN celery
```

**Solutions**:
```bash
# Restart workers
kubectl rollout restart deployment/gabi-worker -n gabi

# Scale workers
kubectl scale deployment/gabi-worker --replicas=10 -n gabi

# Purge stuck queue (CAUTION: loses tasks)
kubectl exec -it deploy/gabi-worker -n gabi -- celery -A src.tasks.celery_app purge
```

#### Memory Leak in Workers

**Symptoms**: Workers OOM, gradually increasing memory

**Diagnosis**:
```bash
# Monitor worker memory over time
watch kubectl top pods -n gabi -l app=gabi-worker

# Check for memory leaks in tasks
kubectl logs -n gabi -l app=gabi-worker | grep "Memory"
```

**Solutions**:
- Set max_tasks_per_child in Celery config
- Restart workers periodically
- Fix memory leaks in task code

### Upload/Disk Issues

#### Disk Full

**Diagnosis**:
```bash
# Check PVC usage
kubectl get pvc -n gabi
kubectl describe pvc gabi-uploads -n gabi

# Check actual usage inside pod
kubectl exec -it deploy/gabi-api -n gabi -- df -h

# Find large files
kubectl exec -it deploy/gabi-api -n gabi -- du -sh /app/uploads/* | sort -hr | head -20
```

**Solutions**:
```bash
# Clean old uploads (if retention policy allows)
kubectl exec -it deploy/gabi-api -n gabi -- find /app/uploads -type f -mtime +30 -delete

# Extend PVC (if supported)
kubectl patch pvc gabi-uploads -n gabi -p '{"spec":{"resources":{"requests":{"storage":"200Gi"}}}}'
```

### Network Issues

#### DNS Resolution Failures

**Diagnosis**:
```bash
# Test DNS from pod
kubectl exec -it deploy/gabi-api -n gabi -- nslookup postgres.gabi.svc.cluster.local

# Check CoreDNS
kubectl get pods -n kube-system -l k8s-app=kube-dns
kubectl logs -n kube-system -l k8s-app=kube-dns
```

**Solutions**:
- Restart CoreDNS pods
- Check NetworkPolicies
- Verify service endpoints

#### NetworkPolicy Blocking

**Diagnosis**:
```bash
# Test connectivity
kubectl exec -it deploy/gabi-api -n gabi -- nc -zv postgres.gabi.svc.cluster.local 5432

# Check NetworkPolicies
kubectl get networkpolicies -n gabi
kubectl describe networkpolicy <name> -n gabi
```

## Debugging Tools

### Inside API Pod

```bash
# Interactive shell
kubectl exec -it deploy/gabi-api -n gabi -- /bin/sh

# Run Python
kubectl exec -it deploy/gabi-api -n gabi -- python

# Test database connection
kubectl exec -it deploy/gabi-api -n gabi -- python -c "from src.infrastructure.persistence.database import engine; print(engine.connect().execute('SELECT 1').fetchone())"
```

### Log Analysis

```bash
# Follow logs
kubectl logs -f -n gabi -l app=gabi-api

# Previous container logs (after crash)
kubectl logs -n gabi gabi-api-xxx --previous

# Logs from all pods
kubectl logs -n gabi -l app=gabi-api --all-containers --prefix

# Filter by time
kubectl logs -n gabi -l app=gabi-api --since=1h

# Export logs
kubectl logs -n gabi -l app=gabi-api --since=24h > gabi-logs-$(date +%Y%m%d).log
```

### Performance Profiling

```bash
# CPU profiling (if enabled in app)
curl -o profile.out https://api.gabi.example.com/debug/pprof/profile?seconds=30

# Memory profiling
curl -o heap.out https://api.gabi.example.com/debug/pprof/heap

# Analyze with pprof
go tool pprof -http=:8080 profile.out
```

## Recovery Procedures

### Complete System Recovery

1. **Verify infrastructure**
   ```bash
   kubectl get nodes
   kubectl get pods --all-namespaces
   ```

2. **Check persistent data**
   ```bash
   kubectl get pvc -n gabi
   kubectl describe pvc postgres-data -n gabi
   ```

3. **Restore from backup if needed**
   ```bash
   # Restore PostgreSQL
   kubectl exec -i postgres-0 -n gabi -- psql -U gabi_user -d gabi < backup.sql
   ```

4. **Restart services in order**
   ```bash
   kubectl apply -k k8s/overlays/production
   ```

5. **Verify functionality**
   ```bash
   curl https://api.gabi.example.com/health
   ```

## External Dependencies

| Service | Status Page | Support |
|---------|-------------|---------|
| OpenAI | status.openai.com | - |
| AWS/GCP | status.aws.amazon.com | - |
| Fly.io | status.fly.io | - |
