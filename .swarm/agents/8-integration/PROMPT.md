# AGENT-8: Integration Monitor Agent

## Role
End-to-end integration tests, final health verification, and swarm report generation

## Scope
- Cross-service integration tests
- End-to-end data flow validation
- Final health report
- Swarm coordination summary

## YOLO Mode Instructions
1. **FULL STACK TEST** - Test data from ingestion to search
2. **GRACEFUL DEGRADATION** - If components missing, test what works
3. **COMPREHENSIVE REPORT** - Document everything, good and bad
4. **FINAL SIGN-OFF** - Declare swarm mission success/failure

## Tasks

### PHASE 1: Wait for All Services (Blocked until Agents 1-7 complete)
Poll all status files:
```bash
for agent in AGENT-{1..7}; do
    jq -r '.status' .swarm/status/${agent}.json 2>/dev/null || echo "pending"
done
```

### PHASE 2: Cross-Service Health Check (5-10 min)
```bash
# Get ports from other agents
API_PORT=$(jq -r '.outputs.port // 8000' .swarm/status/AGENT-3.json 2>/dev/null || echo 8000)

# Verify all services respond
SERVICES=""

# Test PG
if psql $DATABASE_URL -c "SELECT 1" >/dev/null 2>&1; then
    SERVICES="${SERVICES}PostgreSQL: OK
"
else
    SERVICES="${SERVICES}PostgreSQL: FAIL
"
fi

# Test ES
if curl -s http://localhost:9200/_cluster/health | grep -q "status"; then
    SERVICES="${SERVICES}Elasticsearch: OK
"
else
    SERVICES="${SERVICES}Elasticsearch: FAIL
"
fi

# Test Redis
if redis-cli ping | grep -q PONG; then
    SERVICES="${SERVICES}Redis: OK
"
else
    SERVICES="${SERVICES}Redis: FAIL
"
fi

# Test API
if curl -s http://localhost:${API_PORT}/health | grep -q "status"; then
    SERVICES="${SERVICES}API: OK
"
else
    SERVICES="${SERVICES}API: FAIL
"
fi

echo "$SERVICES"
```

### PHASE 3: End-to-End Data Flow Test (10-20 min)
```bash
# Test complete pipeline if possible
python -c "
# Test: Ingest → Index → Search flow
import asyncio
import httpx

async def test_e2e_flow():
    # 1. Check sources endpoint
    async with httpx.AsyncClient() as client:
        response = await client.get('http://localhost:${API_PORT}/api/v1/sources')
        print(f'Sources: {response.status_code}')
        
        # 2. Test search (may be empty but should work)
        response = await client.post(
            'http://localhost:${API_PORT}/api/v1/search',
            json={'query': 'test', 'sources': [], 'limit': 5}
        )
        print(f'Search: {response.status_code}')
        
        # 3. Check admin endpoints
        response = await client.get('http://localhost:${API_PORT}/api/v1/admin/stats')
        print(f'Admin stats: {response.status_code}')

asyncio.run(test_e2e_flow())
"
```

### PHASE 4: Aggregate All Reports (20-25 min)
```bash
# Collect all agent reports
cat > .swarm/artifacts/SWARM_REPORT.md << 'EOF'
# GABI Agent Swarm - Final Report

Generated: $(date -Iseconds)

## Executive Summary

| Component | Status | Notes |
|-----------|--------|-------|
EOF

# Add each agent status
for i in {1..7}; do
    STATUS=$(jq -r '.status' .swarm/status/AGENT-${i}.json 2>/dev/null || echo "unknown")
    echo "| AGENT-$i | $STATUS | |" >> .swarm/artifacts/SWARM_REPORT.md
done

# Append individual reports
echo -e "

## Detailed Reports
" >> .swarm/artifacts/SWARM_REPORT.md

for report in .swarm/artifacts/AGENT-*-report.md; do
    if [ -f "$report" ]; then
        echo "### $(basename $report .md)" >> .swarm/artifacts/SWARM_REPORT.md
        cat "$report" >> .swarm/artifacts/SWARM_REPORT.md
        echo -e "
---
" >> .swarm/artifacts/SWARM_REPORT.md
    fi
done
```

### PHASE 5: Final Health Score (25-30 min)
```bash
# Calculate overall health percentage
TOTAL_AGENTS=7
COMPLETED=$(grep -c "completed" .swarm/status/AGENT-*.json 2>/dev/null || echo 0)
HEALTH_PERCENT=$((COMPLETED * 100 / TOTAL_AGENTS))

# Determine final status
if [ $HEALTH_PERCENT -ge 80 ]; then
    FINAL_STATUS="SUCCESS"
    EXIT_CODE=0
elif [ $HEALTH_PERCENT -ge 50 ]; then
    FINAL_STATUS="PARTIAL"
    EXIT_CODE=0
else
    FINAL_STATUS="FAILED"
    EXIT_CODE=1
fi

echo "Final Health Score: ${HEALTH_PERCENT}%"
echo "Status: ${FINAL_STATUS}"
```

### PHASE 6: Mark Swarm Complete (30-35 min)
```bash
# Write final status
cat > .swarm/status/SWARM_COMPLETE.json << EOF
{
  "timestamp": "$(date -Iseconds)",
  "status": "${FINAL_STATUS}",
  "health_percent": ${HEALTH_PERCENT},
  "agents_completed": ${COMPLETED},
  "agents_total": ${TOTAL_AGENTS},
  "report_location": ".swarm/artifacts/SWARM_REPORT.md",
  "exit_code": ${EXIT_CODE}
}
EOF

echo "=== SWARM MISSION ${FINAL_STATUS} ==="
echo "Report: .swarm/artifacts/SWARM_REPORT.md"
```

## Output Artifacts
Primary: `.swarm/artifacts/SWARM_REPORT.md`
- Executive summary
- All agent reports
- Service health matrix
- Test results summary
- Recommendations

## Status Updates
Write to `.swarm/status/AGENT-8.json` every 2 minutes.

## Dependencies
- ALL AGENTS (1-7)

## Blocks
- NONE (final agent)
