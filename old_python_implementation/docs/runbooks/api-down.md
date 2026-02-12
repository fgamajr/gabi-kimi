# Runbook: GABI API Down

**Alert:** `GABIAPIDown`  
**Severity:** Critical  
**Team:** Platform  

---

## Symptoms

- Health endpoint (`/health`) returns non-200 status or times out
- Users reporting service unavailable
- Fly status shows machines as unhealthy
- UptimeRobot external check failing

---

## Immediate Actions (First 5 minutes)

### 1. Verify the Alert

```bash
# Check if API is actually down
curl -s -o /dev/null -w "%{http_code}" https://gabi-api.tcu.gov.br/health

# Should return 200, anything else indicates issues
```

### 2. Check Fly.io Status

```bash
# View overall app status
fly status --app gabi-api

# Check recent events
fly machine list --app gabi-api

# Check if there's a deployment in progress
fly releases list --app gabi-api
```

### 3. Check Logs

```bash
# Recent logs
fly logs --app gabi-api --recent

# Follow logs in real-time
fly logs --app gabi-api --follow
```

---

## Investigation Steps

### Database Connectivity Issues

```bash
# SSH into the machine
fly ssh console --app gabi-api

# Check database connectivity
python -c "
import asyncio
from gabi.db import init_db, async_session_factory
from sqlalchemy import text

async def check():
    await init_db()
    async with async_session_factory() as session:
        result = await session.execute(text('SELECT 1'))
        print('DB OK:', result.scalar())

asyncio.run(check())
"
```

### Memory/Resource Issues

```bash
# Check resource usage
fly machine status --app gabi-api <machine-id>

# Look for OOM kills in logs
fly logs --app gabi-api | grep -i "oom\|killed\|memory"
```

### Recent Deployment Issues

```bash
# Check if issue started after deployment
fly releases list --app gabi-api

# View specific release
fly releases show --app gabi-api <version>

# Check what changed
git log --oneline <previous-commit>..<current-commit>
```

---

## Resolution Steps

### Option 1: Restart Machines

```bash
# Restart all machines
fly machine restart --app gabi-api

# Or restart specific machine
fly machine restart --app gabi-api <machine-id>
```

### Option 2: Rollback Deployment

```bash
# Deploy previous version
fly deploy --app gabi-api --image <previous-image-sha>

# Or rollback via release
fly releases rollback --app gabi-api <previous-version>
```

### Option 3: Scale Up Resources

```bash
# If resource-constrained, temporarily scale up
fly scale memory 4096 --app gabi-api
fly scale cpus 4 --app gabi-api
```

### Option 4: Check External Dependencies

```bash
# Verify database is accessible
fly status --app gabi-db

# Verify Elasticsearch
fly status --app gabi-es  # or check Bonsai dashboard

# Verify Redis
fly status --app gabi-redis  # or check Upstash dashboard
```

---

## Verification

After taking action, verify the service is restored:

```bash
# Health check
curl https://gabi-api.tcu.gov.br/health

# Check metrics endpoint
curl https://gabi-api.tcu.gov.br/metrics | head

# Check external monitoring
# Verify UptimeRobot shows recovery
```

---

## Post-Incident Actions

1. **Document the incident** in the incident tracker
2. **Analyze root cause** within 24 hours
3. **Update runbook** if new patterns discovered
4. **Schedule follow-up** to prevent recurrence

---

## Escalation Path

- **0-15 min:** Platform team on-call engineer
- **15-30 min:** Platform team lead
- **30+ min:** CTO + TCU IT operations

---

## Related Resources

- [Fly.io Troubleshooting](https://fly.io/docs/reference/troubleshooting/)
- [Grafana Dashboard](https://grafana.tcu.gov.br/d/gabi-production)
- [Deployment History](https://fly.io/dashboard/gabi-api)
