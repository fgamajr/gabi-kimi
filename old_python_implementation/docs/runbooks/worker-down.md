# Runbook: GABI Worker Down

**Alert:** `GABIWorkerDown`  
**Severity:** Warning  
**Team:** Platform  

---

## Symptoms

- Celery workers not responding to ping
- No pipeline tasks being processed
- Queue growing
- Dashboard shows stale data

---

## Immediate Actions

### 1. Verify Worker Status

```bash
# Check Fly status
fly status --app gabi-worker

# List machines
fly machine list --app gabi-worker

# Check events
fly machine status --app gabi-worker <machine-id>
```

### 2. Check Celery Status

```bash
# SSH into worker
fly ssh console --app gabi-worker

# Check Celery workers
celery -A gabi.worker inspect ping

# Check active tasks
celery -A gabi.worker inspect active

# Check worker stats
celery -A gabi.worker inspect stats
```

### 3. Check Logs

```bash
# Recent logs
fly logs --app gabi-worker --recent

# Follow logs
fly logs --app gabi-worker --follow

# Search for errors
fly logs --app gabi-worker | grep -i "error\|exception\|killed"
```

---

## Investigation Steps

### Memory Issues

```bash
# Check for OOM kills
fly logs --app gabi-worker | grep -i "oom\|out of memory"

# Check memory usage
fly status --app gabi-worker
```

### Task Timeout Issues

```bash
# Check for long-running tasks
celery -A gabi.worker inspect active --timeout 10

# Look for task timeouts in logs
fly logs --app gabi-worker | grep -i "timeout\|time limit"
```

### Redis Connection Issues

```bash
# Check Redis connectivity
fly ssh console --app gabi-worker
redis-cli -u $REDIS_URL ping

# Check Celery broker
python -c "
from gabi.worker import celery_app
print(celery_app.connection().connected)
"
```

---

## Resolution Steps

### Option 1: Restart Workers

```bash
# Restart all worker machines
fly machine restart --app gabi-worker

# Or specific machine
fly machine restart --app gabi-worker <machine-id>
```

### Option 2: Clear Stuck Tasks

```bash
# SSH into worker
fly ssh console --app gabi-worker

# Purge queue (WARNING: loses tasks)
celery -A gabi.worker control purge

# Revoke specific stuck task
celery -A gabi.worker control revoke <task-id> terminate
```

### Option 3: Scale Workers

```bash
# Add more worker machines temporarily
fly machine clone --app gabi-worker <existing-machine-id>

# Or scale CPU/memory
fly scale memory 4096 --app gabi-worker
fly scale cpus 4 --app gabi-worker
```

### Option 4: Fix Configuration Issues

```bash
# Check environment variables
fly secrets list --app gabi-worker

# Verify Redis URL is correct
echo $CELERY_BROKER_URL
```

---

## Verification

### Check Worker Health

```bash
# Ping workers
celery -A gabi.worker inspect ping

# Check active workers
celery -A gabi.worker inspect stats | grep "pool"
```

### Test Task Execution

```bash
# Trigger test task
celery -A gabi.worker call gabi.tasks.health.health_check_task

# Check task result
celery -A gabi.worker result <task-id>
```

### Monitor Queue

```bash
# Check queue length
celery -A gabi.worker inspect reserved

# Monitor in real-time
celery -A gabi.worker events
```

---

## Prevention

### Set Worker Resource Limits

```python
# In worker configuration
worker_max_tasks_per_child = 1000  # Restart after 1000 tasks
worker_max_memory_per_child = 200000  # 200MB
```

### Add Health Checks

Already implemented in `fly.toml`:

```yaml
[[http_service.checks]]
  interval = '30s'
  timeout = '5s'
  path = '/health'
```

### Monitor Worker Metrics

```yaml
# Alert on worker down
- alert: GABIWorkerDown
  expr: celery_worker_up == 0
  for: 5m
```

---

## Related Runbooks

- [Pipeline Stalled](./pipeline-stalled.md)
- [DLQ Growing](./dlq-growing.md)
- [High Error Rate](./high-error-rate.md)
