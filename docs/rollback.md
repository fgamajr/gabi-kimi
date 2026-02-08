# GABI Rollback Procedures

## Overview

This document describes procedures for rolling back deployments when issues are detected.

## Rollback Triggers

Automatic rollback triggers:
- Error rate > 10% for 5 minutes
- P95 latency > 5 seconds for 10 minutes
- Health check failures > 50% for 3 minutes
- Any P1 incident during deployment

## Rollback Procedures

### Kubernetes Rollback

#### Rollback Application Deployment

```bash
# Check rollout history
kubectl rollout history deployment/gabi-api -n gabi
kubectl rollout history deployment/gabi-worker -n gabi

# Rollback to previous revision
kubectl rollout undo deployment/gabi-api -n gabi
kubectl rollout undo deployment/gabi-worker -n gabi

# Rollback to specific revision
kubectl rollout undo deployment/gabi-api -n gabi --to-revision=3

# Monitor rollback
kubectl rollout status deployment/gabi-api -n gabi
kubectl get pods -n gabi -l app=gabi-api -w
```

#### Rollback with Image Tag

```bash
# Revert to specific image
kubectl set image deployment/gabi-api api=gabi-api:v1.2.3 -n gabi
kubectl set image deployment/gabi-worker worker=gabi-api:v1.2.3 -n gabi

# Verify rollout
kubectl rollout status deployment/gabi-api -n gabi
```

### Fly.io Rollback

```bash
# List releases
fly releases list -a gabi-api

# Rollback to previous release
fly deploy --image-label v123 -a gabi-api

# Or use rollback command
fly releases rollback v123 -a gabi-api

# Check status
fly status -a gabi-api
```

### Database Rollback

⚠️ **WARNING**: Database rollbacks are destructive. Always backup first.

```bash
# 1. Stop application
kubectl scale deployment/gabi-api --replicas=0 -n gabi
kubectl scale deployment/gabi-worker --replicas=0 -n gabi

# 2. Restore from backup
# Option A: Point-in-time recovery (if enabled)
# Option B: Restore from dump
kubectl exec -i postgres-0 -n gabi -- psql -U gabi_user -d gabi < backup_YYYYMMDD.sql

# 3. Rollback migrations if needed
kubectl run rollback-migrations --rm -i --restart=Never \
  --image=gabi-api:v1.2.3 \
  -n gabi \
  -- env DATABASE_URL=$DATABASE_URL python -m alembic downgrade -1

# 4. Restart application with old version
kubectl set image deployment/gabi-api api=gabi-api:v1.2.3 -n gabi
kubectl scale deployment/gabi-api --replicas=3 -n gabi
kubectl scale deployment/gabi-worker --replicas=3 -n gabi
```

### Elasticsearch Rollback

```bash
# Create snapshot before major changes
kubectl exec -it elasticsearch-0 -n gabi -- curl -XPUT localhost:9200/_snapshot/backup/snapshot_$(date +%Y%m%d_%H%M%S)?wait_for_completion=true

# Restore from snapshot if needed
kubectl exec -it elasticsearch-0 -n gabi -- curl -XPOST localhost:9200/_snapshot/backup/snapshot_YYYYMMDD/_restore

# Delete and recreate index (nuclear option)
kubectl exec -it elasticsearch-0 -n gabi -- curl -XDELETE localhost:9200/documents
# Recreate with old mapping and reindex from source
```

### Complete System Rollback

```bash
#!/bin/bash
# full-rollback.sh - Complete system rollback script

VERSION="${1:-previous}"
NAMESPACE="gabi"

echo "Starting rollback to version: $VERSION"

# 1. Backup current state
kubectl get deployments -n $NAMESPACE -o yaml > backup-deployments-$(date +%Y%m%d_%H%M%S).yaml

# 2. Scale down
echo "Scaling down services..."
kubectl scale deployment/gabi-api --replicas=0 -n $NAMESPACE
kubectl scale deployment/gabi-worker --replicas=0 -n $NAMESPACE

# 3. Wait for pods to terminate
sleep 30

# 4. Rollback deployments
if [ "$VERSION" == "previous" ]; then
    kubectl rollout undo deployment/gabi-api -n $NAMESPACE
    kubectl rollout undo deployment/gabi-worker -n $NAMESPACE
else
    kubectl set image deployment/gabi-api api=gabi-api:$VERSION -n $NAMESPACE
    kubectl set image deployment/gabi-worker worker=gabi-api:$VERSION -n $NAMESPACE
fi

# 5. Scale up
echo "Scaling up services..."
kubectl scale deployment/gabi-api --replicas=3 -n $NAMESPACE
kubectl scale deployment/gabi-worker --replicas=3 -n $NAMESPACE

# 6. Wait for rollout
kubectl rollout status deployment/gabi-api -n $NAMESPACE --timeout=300s
kubectl rollout status deployment/gabi-worker -n $NAMESPACE --timeout=300s

# 7. Health check
echo "Verifying health..."
sleep 10
if kubectl exec -it deploy/gabi-api -n $NAMESPACE -- wget -qO- localhost:8000/health | grep -q "ok"; then
    echo "Rollback successful!"
else
    echo "Health check failed! Manual intervention required."
    exit 1
fi
```

## Emergency Procedures

### Complete Outage - Emergency Rollback

```bash
# Emergency rollback (fastest path)
kubectl rollout undo deployment/gabi-api -n gabi
kubectl rollout undo deployment/gabi-worker -n gabi

# Skip health checks if needed
kubectl patch deployment gabi-api -n gabi -p '{"spec":{"progressDeadlineSeconds":600}}'
```

### Blue-Green Rollback

If using blue-green deployment:

```bash
# Switch traffic back to green (stable)
kubectl patch service gabi-api -n gabi -p '{"spec":{"selector":{"version":"green"}}}'

# Or with Istio
kubectl apply -f k8s/canary/rollback-virtualservice.yaml

# Scale down blue (new failed version)
kubectl scale deployment/gabi-api-blue --replicas=0 -n gabi
```

## Post-Rollback Verification

```bash
# Health checks
curl -sf https://api.gabi.example.com/health || echo "HEALTH CHECK FAILED"
curl -sf https://api.gabi.example.com/ready || echo "READY CHECK FAILED"

# Smoke tests
./scripts/smoke-tests.sh

# Error rate check
# (Check monitoring dashboard - should be < 1%)

# Latency check
# (Check P95 latency - should be < 500ms)
```

## Rollback Checklist

- [ ] Identify rollback reason and scope
- [ ] Notify team/stakeholders
- [ ] Backup current state if possible
- [ ] Execute appropriate rollback procedure
- [ ] Verify rollback success
- [ ] Monitor for 30 minutes
- [ ] Document rollback in incident log
- [ ] Schedule post-mortem
- [ ] Fix forward plan created

## Communication Template

```
**Subject**: [INCIDENT] Rollback executed - GABI $VERSION

**Status**: Investigating / Monitoring / Resolved

**Summary**: 
Rolled back GABI from vX.Y.Z to vX.Y.W due to [reason].

**Timeline**:
- HH:MM - Issue detected
- HH:MM - Rollback initiated
- HH:MM - Rollback complete
- HH:MM - Service restored

**Impact**:
- Downtime: X minutes
- Features affected: [list]

**Next Steps**:
- Continue monitoring
- Post-mortem scheduled for [time]
```

## Prevention Measures

### Pre-Deployment Checklist

- [ ] Feature flags available for new features
- [ ] Database migrations are backward compatible
- [ ] Rollback procedure tested in staging
- [ ] Monitoring alerts configured
- [ ] Team notified of deployment window
- [ ] Rollback decision maker identified

### Safe Deployment Practices

1. **Canary Deployments**: Deploy to 10% of traffic first
2. **Feature Flags**: Enable features gradually
3. **Database Migrations**: Always backward compatible
4. **Health Checks**: Comprehensive before marking ready
5. **Auto-Rollback**: Configure based on error rates

## Rollback Scenarios

| Scenario | Rollback Time | Procedure |
|----------|---------------|-----------|
| API bug | 2-5 min | Kubernetes rollback |
| DB migration issue | 10-30 min | DB restore + rollback |
| Config error | 1-2 min | ConfigMap revert |
| Dependency failure | 5-10 min | Version rollback |
| Complete failure | 5-15 min | Full system rollback |
