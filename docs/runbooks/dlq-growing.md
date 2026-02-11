# Runbook: GABI DLQ Growing

**Alert:** `GABIDLQGrowing`  
**Severity:** Warning  
**Team:** Data  

---

## Symptoms

- `gabi_dlq_queue_size` metric > 100
- Documents failing to process repeatedly
- Error rate increasing in pipeline metrics
- Users may see incomplete or stale data

---

## Understanding the DLQ

The Dead Letter Queue (DLQ) holds messages that failed processing and need manual intervention. Messages in DLQ are retried automatically up to a configured limit, then require manual action.

**Common DLQ error types:**
- Parser errors (schema changes, invalid formats)
- Network timeouts (source unavailable)
- Validation errors (missing required fields)
- Embedding failures (TEI service issues)

---

## Immediate Actions

### 1. Check DLQ Status

```bash
# Get DLQ summary
curl -H "Authorization: Bearer $TOKEN" \
  https://gabi-api.tcu.gov.br/api/v1/admin/dlq

# Get messages for specific source
curl -H "Authorization: Bearer $TOKEN" \
  "https://gabi-api.tcu.gov.br/api/v1/admin/dlq?source_id=<source_id>&limit=50"
```

### 2. Analyze Error Patterns

```bash
# Check worker logs for DLQ patterns
fly logs --app gabi-worker | grep -i "dlq\|dead letter"

# Look for specific error types
fly logs --app gabi-worker | grep -i "parse error\|validation\|timeout"
```

### 3. Check DLQ Metrics

```bash
# Prometheus query for DLQ breakdown
curl -s https://gabi-api.tcu.gov.br/metrics | grep gabi_dlq

# Key metrics:
# - gabi_dlq_queue_size (current pending)
# - gabi_dlq_messages_total (created/retried/resolved)
```

---

## Investigation Steps

### Categorize Errors

Group DLQ messages by error type:

```bash
# Get error summary via API
curl -H "Authorization: Bearer $TOKEN" \
  "https://gabi-api.tcu.gov.br/api/v1/admin/dlq/summary"

# Or query directly in database
fly ssh console --app gabi-api
python -c "
import asyncio
from gabi.db import async_session_factory
from gabi.models.dlq import DLQMessage, DLQStatus
from sqlalchemy import select, func

async def summary():
    async with async_session_factory() as session:
        # Count by error type
        result = await session.execute(
            select(DLQMessage.error_type, func.count(DLQMessage.id))
            .where(DLQMessage.status.in_([DLQStatus.PENDING, DLQStatus.RETRYING]))
            .group_by(DLQMessage.error_type)
        )
        for row in result:
            print(f'{row[0]}: {row[1]}')

asyncio.run(summary())
"
```

### Check for Source-Specific Issues

```bash
# If errors are concentrated on one source
curl -H "Authorization: Bearer $TOKEN" \
  "https://gabi-api.tcu.gov.br/api/v1/admin/dlq?source_id=tcu_acordaos"

# Check if source website changed
curl -I <source_url>
```

### Review Recent Changes

```bash
# Check for recent deployments
git log --oneline --since="3 days ago"

# Check if sources.yaml was modified
git diff HEAD~5 -- sources.yaml
```

---

## Resolution Steps

### Option 1: Retry DLQ Messages

```bash
# Retry all pending messages
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  https://gabi-api.tcu.gov.br/api/v1/admin/dlq/retry-all

# Retry specific source
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source_id": "<source_id>"}' \
  https://gabi-api.tcu.gov.br/api/v1/admin/dlq/retry

# Or via Celery task
fly ssh console --app gabi-worker
celery -A gabi.worker call gabi.tasks.dlq.process_pending_dlq_task \
  -k '{"max_messages": 100}'
```

### Option 2: Fix Root Cause and Retry

**For Parser Errors:**
```bash
# 1. Identify failing URL pattern
# 2. Fix parser code
# 3. Deploy fix
fly deploy --app gabi-worker

# 4. Retry DLQ messages
curl -X POST -H "Authorization: Bearer $TOKEN" \
  https://gabi-api.tcu.gov.br/api/v1/admin/dlq/retry-all
```

**For Schema Changes:**
```bash
# 1. Update sources.yaml mapping
cp sources.yaml sources.yaml.bak
vim sources.yaml  # Update field mappings

# 2. Deploy changes
fly deploy --app gabi-worker

# 3. Retry affected messages
```

**For Network Issues:**
```bash
# 1. Verify source is accessible
curl -I <source_url>

# 2. If temporary, just retry
curl -X POST -H "Authorization: Bearer $TOKEN" \
  https://gabi-api.tcu.gov.br/api/v1/admin/dlq/retry-all

# 3. If permanent, update source URL in sources.yaml
```

### Option 3: Purge Invalid Messages

**WARNING:** Only purge if messages are fundamentally unrecoverable

```bash
# Purge specific messages by ID
curl -X DELETE \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message_ids": ["id1", "id2"]}' \
  https://gabi-api.tcu.gov.br/api/v1/admin/dlq

# Purge all messages for a source (USE WITH CAUTION)
curl -X DELETE \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source_id": "<source_id>", "confirm": true}' \
  https://gabi-api.tcu.gov.br/api/v1/admin/dlq
```

### Option 4: Manual Reprocessing

For high-priority documents:

```bash
# Get document details from DLQ
curl -H "Authorization: Bearer $TOKEN" \
  https://gabi-api.tcu.gov.br/api/v1/admin/dlq/<message_id>

# Manually trigger reprocessing
# (May need to construct API call based on document details)
```

---

## Verification

### Monitor DLQ Size

```bash
# Watch DLQ metrics
watch -n 30 'curl -s https://gabi-api.tcu.gov.br/metrics | grep gabi_dlq_queue_size'

# Or via API
curl -H "Authorization: Bearer $TOKEN" \
  https://gabi-api.tcu.gov.br/api/v1/admin/dlq | jq '.pending_count'
```

### Check Resolution Rate

```bash
# Prometheus query
curl -s https://gabi-api.tcu.gov.br/metrics | grep 'gabi_dlq_messages_total.*resolved'
```

### Verify No New Errors

```bash
# Monitor logs for new DLQ entries
fly logs --app gabi-worker | grep -i "dlq\|dead letter"
```

---

## Prevention

### Improve Parser Resilience

```python
# Example: Add fallback for schema changes
def parse_document(data):
    try:
        # Primary parsing logic
        return standard_parse(data)
    except ValidationError:
        # Fallback for schema variations
        return fallback_parse(data)
```

### Add Circuit Breaker

For unreliable sources:

```yaml
# sources.yaml
sources:
  unreliable_source:
    retry_policy:
      max_retries: 3
      backoff: exponential
      circuit_breaker:
        failure_threshold: 10
        timeout: 3600  # 1 hour
```

### Monitor Source Health

Set up alerts for source accessibility:

```yaml
- alert: GABISourceUnreachable
  expr: |
    sum(rate(gabi_pipeline_documents_total{status="failed"}[1h])) by (source_id) > 10
  for: 15m
```

---

## Post-Incident Actions

1. **Document error patterns** in knowledge base
2. **Update parser** to handle edge cases
3. **Review DLQ thresholds** if alerts are noisy
4. **Improve monitoring** for early detection

---

## Related Runbooks

- [Pipeline Stalled](./pipeline-stalled.md)
- [High Error Rate](./high-error-rate.md)
- [Parser Errors](./parser-errors.md)
