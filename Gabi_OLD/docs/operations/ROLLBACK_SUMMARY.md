# GABI Pipeline Rollback - Quick Reference

## TL;DR

When a pipeline fails, use these commands:

```bash
# 1. Check status
./scripts/rollback/rollback.sh check <source_id>

# 2. Perform appropriate rollback
./scripts/rollback/rollback.sh reset-job <source_id>      # Job stuck
./scripts/rollback/rollback.sh reset-fetch <source_id>   # Fetch failed
./scripts/rollback/rollback.sh reset-ingest <source_id>  # Ingest failed

# 3. Validate
./scripts/rollback/rollback.sh validate <source_id>

# 4. Restart via API
curl -X POST http://localhost:5100/api/v1/dashboard/sources/<source_id>/run-pipeline \
  -H "Authorization: Bearer $TOKEN"
```

---

## Rollback Scenarios

### Scenario 1: Worker Crashed, Job Stuck in "Running"

**Symptoms**: Job shows as `running` in dashboard but no activity for >1 hour.

**Solution**:
```bash
./scripts/rollback/rollback.sh reset-job my_source
./scripts/rollback/rollback.sh validate my_source
curl -X POST http://localhost:5100/api/v1/dashboard/sources/my_source/resume \
  -H "Authorization: Bearer $TOKEN"
```

---

### Scenario 2: Fetch Phase Failed Mid-Run

**Symptoms**: Some fetch_items failed, need to retry failed ones only.

**Solution**:
```bash
./scripts/rollback/rollback.sh reset-fetch my_source
./scripts/rollback/rollback.sh validate my_source
curl -X POST http://localhost:5100/api/v1/dashboard/sources/my_source/phases/fetch \
  -H "Authorization: Bearer $TOKEN"
```

**For full refetch** (all items):
```bash
./scripts/rollback/rollback.sh reset-fetch my_source --full
```

---

### Scenario 3: Ingest Created Corrupt Documents

**Symptoms**: Documents have status `completed` but empty/corrupt content.

**Solution**:
```bash
# Reset only failed/processing docs
./scripts/rollback/rollback.sh reset-ingest my_source

# Or reset ALL docs (including completed)
./scripts/rollback/rollback.sh reset-ingest my_source --full

./scripts/rollback/rollback.sh validate my_source
curl -X POST http://localhost:5100/api/v1/dashboard/sources/my_source/phases/ingest \
  -H "Authorization: Bearer $TOKEN"
```

---

### Scenario 4: Complete Source Reset (Emergency)

**Symptoms**: Multiple cascading failures, data inconsistency.

**Solution**:
```bash
# Backup first!
pg_dump -h localhost -p 5433 -U postgres -d gabi -F c \
  -f "emergency_backup_$(date +%Y%m%d_%H%M%S).dump"

# Nuclear reset (requires manual COMMIT)
./scripts/rollback/rollback.sh nuclear my_source

# In psql output, review then:
# COMMIT;  -- apply changes
# ROLLBACK; -- cancel changes

./scripts/rollback/rollback.sh validate my_source
curl -X POST http://localhost:5100/api/v1/dashboard/sources/my_source/run-pipeline \
  -H "Authorization: Bearer $TOKEN"
```

---

## Rollback Matrix

| Problem | Command | API Restart |
|---------|---------|-------------|
| Job stuck running | `reset-job` | `resume` or phase endpoint |
| Fetch partial failure | `reset-fetch` | `/phases/fetch` |
| Fetch complete failure | `reset-fetch --full` | `/phases/fetch` |
| Ingest partial failure | `reset-ingest` | `/phases/ingest` |
| Ingest complete failure | `reset-ingest --full` | `/phases/ingest` |
| Data corruption | `nuclear` | `/run-pipeline` |
| Multiple issues | `nuclear` | `/run-pipeline` |

---

## Pre-Rollback Safety Checklist

- [ ] Pause source via API: `POST /dashboard/sources/{id}/pause`
- [ ] Check Hangfire dashboard at `/hangfire`
- [ ] Verify no actual workers are processing the source
- [ ] **Backup database** before destructive operations
- [ ] Document incident reason

---

## Validation Checklist

After rollback, verify:

- [ ] Pipeline state is `idle` or `stopped`
- [ ] No jobs in `running` or `processing` status
- [ ] No `fetch_items` stuck in `processing` >1 hour
- [ ] No `documents` stuck in `processing` >1 hour
- [ ] Run: `./scripts/rollback/rollback.sh validate <source_id>`

---

## API Authentication

```bash
# Get token
TOKEN=$(curl -s -X POST http://localhost:5100/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"YOUR_PASSWORD"}' | jq -r '.token')

# Use token in requests
curl -H "Authorization: Bearer $TOKEN" ...
```

---

## Files Reference

| File | Purpose |
|------|---------|
| `docs/operations/ROLLBACK_STRATEGY.md` | Full documentation |
| `scripts/rollback/rollback.sh` | Helper script |
| `scripts/rollback/01_check_source_status.sql` | Check status |
| `scripts/rollback/02_reset_job_registry.sql` | Reset jobs |
| `scripts/rollback/03_reset_fetch_phase.sql` | Reset fetch |
| `scripts/rollback/04_reset_ingest_phase.sql` | Reset ingest |
| `scripts/rollback/05_nuclear_reset.sql` | Full reset |
| `scripts/rollback/06_validate_rollback.sql` | Validation |

---

## Emergency Contacts

- On-call: Check `AGENTS.md`
- Runbook: `docs/reliability/CHAOS_PLAYBOOK.md`
- Architecture: `docs/architecture/LAYERED_ARCHITECTURE.md`
