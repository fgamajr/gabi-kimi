# GABI Operations Runbook

## Incident Response

### Severity Levels

- **P1 (Critical)**: Complete system outage, data loss, security breach
- **P2 (High)**: Major functionality degraded, partial outage
- **P3 (Medium)**: Minor functionality issues, workarounds exist
- **P4 (Low)**: Cosmetic issues, feature requests

### Response Team

| Role | Contact | Responsibility |
|------|---------|----------------|
| On-call Engineer | PagerDuty | Initial response, triage |
| Tech Lead | Slack #incidents | Escalation, decisions |
| DevOps | Slack #ops | Infrastructure issues |
| Security | security@example.com | Security incidents |

## Standard Operating Procedures

### Daily Checks

```bash
# Check system health
curl https://api.gabi.example.com/health

# Check metrics
kubectl top pods -n gabi

# Check logs for errors
kubectl logs -n gabi -l app=gabi-api --tail=100 | grep ERROR

# Check queue status
kubectl exec -it deploy/gabi-worker -n gabi -- celery -A src.tasks.celery_app inspect stats
```

### Weekly Tasks

- [ ] Review error logs and alerts
- [ ] Check disk usage on all persistent volumes
- [ ] Verify backup completion
- [ ] Review performance metrics
- [ ] Check security patches available

### Monthly Tasks

- [ ] Capacity planning review
- [ ] Security audit
- [ ] Access review
- [ ] Disaster recovery test
- [ ] Documentation update

## Common Procedures

### Restart Services

```bash
# Restart API
kubectl rollout restart deployment/gabi-api -n gabi

# Restart workers
kubectl rollout restart deployment/gabi-worker -n gabi

# Restart specific pod
kubectl delete pod gabi-api-xxx -n gabi
```

### Scale Services

```bash
# Scale API horizontally
kubectl scale deployment/gabi-api --replicas=5 -n gabi

# Scale workers
kubectl scale deployment/gabi-worker --replicas=10 -n gabi

# Check HPA status
kubectl get hpa -n gabi
```

### Database Operations

```bash
# Connect to database
kubectl exec -it postgres-0 -n gabi -- psql -U gabi_user -d gabi

# Check active connections
SELECT count(*) FROM pg_stat_activity;

# Check table sizes
SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) 
FROM pg_tables 
WHERE schemaname='public' 
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

# Check long-running queries
SELECT pid, usename, application_name, state, query_start, now() - query_start as duration, query 
FROM pg_stat_activity 
WHERE state != 'idle' AND now() - query_start > interval '5 minutes';
```

### Celery Queue Management

```bash
# Check queue lengths
kubectl exec -it deploy/gabi-worker -n gabi -- celery -A src.tasks.celery_app inspect active

# Purge all tasks (DANGEROUS)
kubectl exec -it deploy/gabi-worker -n gabi -- celery -A src.tasks.celery_app purge

# Revoke specific task
kubectl exec -it deploy/gabi-worker -n gabi -- celery -A src.tasks.celery_app control revoke <task_id>

# Restart workers gracefully
kubectl exec -it deploy/gabi-worker -n gabi -- celery -A src.tasks.celery_app control shutdown
```

## Alert Responses

### High Error Rate

**Symptoms**: Error rate > 5%

**Steps**:
1. Check logs: `kubectl logs -n gabi -l app=gabi-api --tail=500`
2. Check external dependencies (OpenAI, database)
3. Check resource usage: `kubectl top pods -n gabi`
4. If resource exhaustion, scale up
5. If dependency issue, check status pages

### High Latency

**Symptoms**: P95 latency > 2s

**Steps**:
1. Check database query performance
2. Check Elasticsearch cluster health
3. Check worker queue depth
4. Review recent deployments
5. Consider scaling if sustained

### Queue Backlog

**Symptoms**: Queue length > 1000

**Steps**:
1. Check worker status: `celery -A src.tasks.celery_app inspect stats`
2. Scale workers if needed
3. Check for blocked tasks
4. Review task success/failure rates
5. Consider prioritizing queues

### Disk Space Warning

**Symptoms**: Disk usage > 80%

**Steps**:
1. Identify large consumers
2. Clean old logs if safe
3. Extend volume if needed
4. Review retention policies

## Deployment Procedures

### Standard Deployment

```bash
# 1. Notify team
# 2. Deploy
kubectl apply -k k8s/overlays/production

# 3. Monitor rollout
kubectl rollout status deployment/gabi-api -n gabi
kubectl rollout status deployment/gabi-worker -n gabi

# 4. Run smoke tests
./scripts/smoke-tests.sh

# 5. Notify team of completion
```

### Database Migration Deployment

```bash
# 1. Backup database first
kubectl exec -it postgres-0 -n gabi -- pg_dump -U gabi_user gabi > backup_$(date +%Y%m%d).sql

# 2. Run migrations via init container or job
kubectl apply -f k8s/jobs/migrate.yaml

# 3. Verify migrations
kubectl logs -f job/db-migrate -n gabi

# 4. Deploy application
kubectl apply -k k8s/overlays/production
```

### Hotfix Deployment

```bash
# 1. Build hotfix image
docker build -t gabi-api:hotfix-1.2.3 .

# 2. Deploy with hotfix tag
kubectl set image deployment/gabi-api api=gabi-api:hotfix-1.2.3 -n gabi

# 3. Monitor
kubectl rollout status deployment/gabi-api -n gabi

# 4. Rollback if needed
kubectl rollout undo deployment/gabi-api -n gabi
```

## Maintenance Windows

### Scheduled Maintenance

1. **Pre-maintenance** (T-24h):
   - Notify users
   - Prepare rollback plan
   - Verify backups

2. **During maintenance**:
   - Enable maintenance mode if needed
   - Execute changes
   - Verify functionality

3. **Post-maintenance** (T+2h):
   - Monitor closely
   - Notify users of completion
   - Document any issues

## Escalation Procedures

### Escalation Path

1. **L1 (0-15 min)**: On-call engineer handles
2. **L2 (15-30 min)**: Escalate to Tech Lead if unresolved
3. **L3 (30+ min)**: Full incident response team

### External Escalation

- **Cloud Provider**: AWS/GCP support cases
- **SaaS Vendors**: OpenAI status/support
- **Security**: security@example.com

## Post-Incident

### Post-Mortem Template

```markdown
# Incident Post-Mortem: [TITLE]

## Summary
- Date: 
- Duration: 
- Severity: 
- Impact: 

## Timeline
- T+0: Issue detected
- T+X: Action taken
- T+Y: Resolution

## Root Cause
[Detailed analysis]

## Resolution
[What fixed it]

## Lessons Learned
- What went well
- What could be improved

## Action Items
- [ ] Action 1 (Owner, Due)
- [ ] Action 2 (Owner, Due)
```

## Contact Information

| Service | Contact | URL |
|---------|---------|-----|
| On-call | PagerDuty | https://pagerduty.com |
| Slack | #incidents | slack:// |
| Status Page | Statuspage | https://status.gabi.example.com |
| Documentation | Confluence | https://wiki.example.com |
