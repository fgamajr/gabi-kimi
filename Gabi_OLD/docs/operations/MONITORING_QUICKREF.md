# GABI Monitoring Quick Reference

> One-page reference for common monitoring tasks

---

## 🚨 Critical Checks (Run Every 5 Minutes)

```sql
-- 1. Queue Depth
SELECT status, COUNT(*) FROM job_registry 
WHERE created_at > NOW() - INTERVAL '24 hours' 
GROUP BY status;

-- 2. Stuck Jobs (> 30 min)
SELECT COUNT(*) FROM job_registry 
WHERE status = 'processing' 
  AND started_at < NOW() - INTERVAL '30 minutes';

-- 3. Recent Failures (Last Hour)
SELECT COUNT(*) FROM job_registry 
WHERE status = 'failed' 
  AND completed_at > NOW() - INTERVAL '1 hour';

-- 4. DLQ Size
SELECT COUNT(*) FROM dlq_entries WHERE status = 'pending';
```

---

## 📊 Throughput Metrics (Run Every Hour)

```sql
-- Jobs per Hour
SELECT DATE_TRUNC('hour', completed_at) as hour, COUNT(*)
FROM job_registry
WHERE status = 'completed' 
  AND completed_at > NOW() - INTERVAL '24 hours'
GROUP BY 1 ORDER BY 1 DESC;

-- Average Job Duration
SELECT job_type, 
       AVG(EXTRACT(EPOCH FROM (completed_at - started_at))) as avg_seconds
FROM job_registry
WHERE status = 'completed'
  AND completed_at > NOW() - INTERVAL '24 hours'
GROUP BY job_type;
```

---

## 🔍 Debugging Commands

```bash
# Check worker logs
docker logs gabi-worker --tail 100

# Check API logs
docker logs gabi-api --tail 100

# Database connection test
psql $DATABASE_URL -c "SELECT COUNT(*) FROM job_registry;"

# ES cluster health
curl -s http://localhost:9200/_cluster/health | jq .
```

---

## ⚠️ Alert Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| Pending Jobs | > 500 | > 1000 |
| Failed Jobs (1h) | > 5 | > 20 |
| Stuck Jobs | > 3 | > 10 |
| DLQ Size | > 50 | > 200 |
| Avg Job Duration | > 5 min | > 15 min |
| DB Connections | > 100 | > 180 |

---

## 🔧 Quick Fixes

```bash
# Pause stuck source
curl -X POST /api/v1/dashboard/sources/{id}/pause -H "Authorization: Bearer $TOKEN"

# Resume source
curl -X POST /api/v1/dashboard/sources/{id}/resume -H "Authorization: Bearer $TOKEN"

# Replay DLQ entry
curl -X POST /api/v1/dlq/{id}/replay -H "Authorization: Bearer $TOKEN"

# Queue hygiene (local only)
./scripts/queue-hygiene.sh --dry-run
```

---

## 📈 Dashboard URLs

| Dashboard | URL |
|-----------|-----|
| Hangfire | http://localhost:5100/hangfire |
| API Swagger | http://localhost:5100/swagger |
| Health | http://localhost:5100/health |
| ES Cluster | http://localhost:9200/_cluster/health |

---

## 🔗 Related Docs

- [MONITORING_PLAN.md](./MONITORING_PLAN.md) - Full monitoring plan
- [CHAOS_PLAYBOOK.md](../reliability/CHAOS_PLAYBOOK.md) - Reliability tests
- [queue-hygiene.md](./queue-hygiene.md) - Queue cleanup
