# GABI Agent Swarm - YOLO Mode Coordination

## 🎯 Mission
Deploy, test, and monitor GABI platform end-to-end with minimal human intervention.

## 🐝 Agent Swarm Structure

```
┌─────────────────────────────────────────────────────────────┐
│                    SWARM COORDINATOR                        │
│                   (This Document)                           │
└──────────────┬──────────────┬──────────────┬────────────────┘
               │              │              │
    ┌──────────┴──┐  ┌───────┴────┐  ┌──────┴─────┐
    │  AGENT 1    │  │  AGENT 2   │  │  AGENT 3   │
    │  Infra/Ops  │  │  Database  │  │  API/Web   │
    └──────────┬──┘  └───────┬────┘  └──────┬─────┘
               │              │              │
    ┌──────────┴──┐  ┌───────┴────┐  ┌──────┴─────┐
    │  AGENT 4    │  │  AGENT 5   │  │  AGENT 6   │
    │  Pipeline   │  │    MCP     │  │    QA      │
    └──────────┬──┘  └────────────┘  └──────┬─────┘
               │                            │
    ┌──────────┴──────────┐    ┌───────────┴──────────┐
    │      AGENT 7        │    │       AGENT 8        │
    │   Observability     │    │  Integration Monitor │
    └─────────────────────┘    └──────────────────────┘
```

## 📡 Communication Protocol

### Status Files (Async Communication)
Each agent writes to `.swarm/status/AGENT-{N}.json`:
```json
{
  "agent": "AGENT-1",
  "status": "running|completed|blocked|error",
  "progress": 0-100,
  "last_action": "description",
  "timestamp": "ISO8601",
  "outputs": {"key": "value"},
  "blocking_issues": [],
  "needs_from_agents": []
}
```

### Blocking Resolution
1. Agent detects dependency on another agent
2. Check `.swarm/status/` for required agent status
3. If not ready, add to `needs_from_agents` and poll every 30s
4. If ERROR, escalate to ERROR HANDLER PROTOCOL

### ERROR HANDLER PROTOCOL
```
1. Log error details to .swarm/errors/AGENT-{N}-{TIMESTAMP}.log
2. Attempt self-heal (3 retries with backoff)
3. If unrecoverable, mark status="blocked"
4. Continue with other tasks that don't depend on failed component
5. Report to Integration Monitor (Agent 8) at end of cycle
```

## 🔥 YOLO Mode Rules

1. **NO CONFIRMATION REQUIRED**: Make decisions, fix issues, proceed
2. **AUTONOMOUS RETRY**: 3 attempts with exponential backoff before blocking
3. **SAFE FALLBACKS**: If feature fails, degrade gracefully (don't crash everything)
4. **CONTINUOUS PROGRESS**: Always be doing something useful
5. **DOCUMENT EVERYTHING**: Write to `.swarm/logs/` and `.swarm/artifacts/`

## 🏁 Completion Criteria

All agents must report:
- [ ] Services running (docker-compose or local)
- [ ] Database migrations applied
- [ ] All unit tests passing
- [ ] All integration tests passing
- [ ] Health checks green
- [ ] API responding on :8000
- [ ] MCP server responding
- [ ] Metrics endpoint responding
- [ ] No critical errors in logs

## 🚀 Bootstrap Sequence

```
PHASE 1 (Parallel - 5 min):
  └─ Agent 1: Start infrastructure services
  └─ Agent 2: Prepare database
  └─ Agent 6: Validate test environment

PHASE 2 (After Phase 1 - 10 min):
  └─ Agent 2: Run migrations, verify pgvector
  └─ Agent 3: Start API, verify routes
  └─ Agent 4: Start Celery workers
  └─ Agent 5: Start MCP server

PHASE 3 (After Phase 2 - 15 min):
  └─ Agent 6: Run full test suite
  └─ Agent 7: Verify observability stack
  └─ Agent 8: End-to-end integration tests

PHASE 4 (Final - 5 min):
  └─ Agent 8: Final health report
  └─ Generate .swarm/artifacts/SWARM_REPORT.md
```
