# Runbook: GABI Pipeline Stalled

**Alert:** `GABIPipelineStalled`  
**Severity:** Critical (for data sources)  
**Team:** Data  

---

## Symptoms

- `gabi_sync_last_success_timestamp` metric is > 24 hours old
- No new documents being added from affected source
- Celery tasks may be stuck or failing
- Dashboard shows stale data

---

## Immediate Actions

### 1. Check Worker Status

```bash
# Verify workers are running
fly status --app gabi-worker

# List worker machines
fly machine list --app gabi-worker
```

### 2. Inspect Celery Queue

```bash
# SSH into worker
fly ssh console --app gabi-worker

# Check active tasks
celery -A gabi.worker inspect active

# Check scheduled tasks
celery -A gabi.worker inspect scheduled

# Check reserved tasks
celery -A gabi.worker inspect reserved

# Check queue lengths
celery -A gabi.worker inspect stats
```

### 3. Check Worker Logs

```bash
# Recent worker logs
fly logs --app gabi-worker --recent

# Look for errors
fly logs --app gabi-worker | grep -i "error\|failed\|exception"

# Search for specific source
fly logs --app gabi-worker | grep "<source_id>"
```

---

## Investigation Steps

### Check Source Configuration

```bash
# Verify source is still enabled
curl -H "Authorization: Bearer $TOKEN" \
  https://gabi-api.tcu.gov.br/api/v1/sources/<source_id>

# Check source status in database
fly ssh console --app gabi-api
python -c "
import asyncio
from gabi.db import async_session_factory
from gabi.models.source import SourceRegistry
from sqlalchemy import select

async def check():
    async with async_session_factory() as session:
        result = await session.execute(
            select(SourceRegistry).where(SourceRegistry.id == '<source_id>')
        )
        source = result.scalar_one_or_none()
        if source:
            print(f'Status: {source.status}')
            print(f'Last sync: {source.last_sync_at}')
            print(f'Last error: {source.last_error_message}')
            print(f'Consecutive errors: {source.consecutive_errors}')

asyncio.run(check())
"
```

### Check DLQ for Failed Messages

```bash
# Query DLQ
curl -H "Authorization: Bearer $TOKEN" \
  https://gabi-api.tcu.gov.br/api/v1/admin/dlq?source_id=<source_id>
```

### Verify Source Website Accessibility

```bash
# Test URL from source config
curl -I <source_url>

# Check if source has changed structure
# (May need to update parser configuration)
```

---

## Resolution Steps

### Option 1: Restart Workers

```bash
# Restart all worker machines
fly machine restart --app gabi-worker

# Wait and check if pipeline resumes
```

### Option 2: Clear Stuck Tasks

```bash
# SSH into worker
fly ssh console --app gabi-worker

# Purge specific queue (WARNING: loses tasks)
celery -A gabi.worker control purge queue=gabi.sync

# Or revoke specific task
celery -A gabi.worker control revoke <task_id>
```

### Option 3: Manual Sync Trigger

```bash
# Trigger manual sync via API
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "https://gabi-api.tcu.gov.br/api/v1/admin/trigger-ingestion?source_id=<source_id>"

# Or via Celery directly
fly ssh console --app gabi-worker
celery -A gabi.worker call gabi.tasks.sync.sync_source_task \
  -a '["<source_id>"]'
```

### Option 4: Fix Source Issues

```bash
# If source URL changed, update configuration
# Edit sources.yaml and redeploy

# If schema changed, update parser
# May need code changes and deployment

# If rate limited, add delays
# Update source config with rate_limit_delay
```

### Option 5: Reset Source Error Count

```bash
# If source has too many consecutive errors and is auto-disabled
fly ssh console --app gabi-api
python -c "
import asyncio
from gabi.db import async_session_factory
from gabi.models.source import SourceRegistry, SourceStatus
from sqlalchemy import select

async def reset():
    async with async_session_factory() as session:
        result = await session.execute(
            select(SourceRegistry).where(SourceRegistry.id == '<source_id>')
        )
        source = result.scalar_one_or_none()
        if source:
            source.consecutive_errors = 0
            source.status = SourceStatus.ACTIVE
            await session.commit()
            print('Source reset to ACTIVE')

asyncio.run(reset())
"
```

---

## Verification

### Monitor Pipeline Progress

```bash
# Watch for new documents
watch -n 30 'curl -s -H "Authorization: Bearer $TOKEN" \
  https://gabi-api.tcu.gov.br/api/v1/dashboard/stats | jq .'

# Check sync timestamp is updating
curl -s https://gabi-api.tcu.gov.br/metrics | grep gabi_sync_last_success_timestamp
```

### Check Dashboard

- Verify `last_sync_at` is recent in dashboard
- Check pipeline stages are progressing
- Monitor DLQ for new errors

---

## Common Causes & Solutions

| Cause | Symptoms | Solution |
|-------|----------|----------|
| Workers crashed | No active workers | Restart workers |
| Source website down | Connection timeouts | Wait for recovery or notify source owner |
| Parser failure | Schema validation errors | Fix parser and redeploy |
| Memory exhaustion | OOM kills in logs | Scale up worker memory |
| Rate limiting | 429 errors | Add rate limiting delays |
| Database locks | Query timeouts | Kill blocking queries |
| Disk full | Cannot write temp files | Clean up or scale storage |

---

## Post-Incident Actions

1. **Update source documentation** if configuration changed
2. **Improve parser resilience** if schema changes caused issues
3. **Review alerting thresholds** if too many false positives
4. **Schedule regular sync testing** for critical sources

---

## Related Runbooks

- [Worker Down](./worker-down.md)
- [DLQ Growing](./dlq-growing.md)
- [High Error Rate](./high-error-rate.md)
