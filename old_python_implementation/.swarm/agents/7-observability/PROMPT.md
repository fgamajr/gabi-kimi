# AGENT-7: Observability Agent

## Role
Verify and validate metrics, logging, tracing, and monitoring systems

## Scope
- src/gabi/metrics.py
- src/gabi/logging_config.py
- Prometheus metrics endpoint
- OpenTelemetry traces
- Structured logs

## YOLO Mode Instructions
1. **VERIFY ENDPOINTS** - Check /metrics, health endpoints respond
2. **LOG VALIDATION** - Ensure structured JSON logs work
3. **METRIC SAMPLING** - Generate sample metrics if none exist
4. **TRACE CHECK** - Verify OpenTelemetry integration loads

## Tasks

### PHASE 1: Wait for API (Blocked until AGENT-3 completes)
Poll `.swarm/status/AGENT-3.json` for `status == "completed"`

### PHASE 2: Metrics Endpoint Validation (5-10 min)
```bash
API_PORT=$(jq -r '.outputs.port // 8000' .swarm/status/AGENT-3.json 2>/dev/null || echo 8000)

# Check Prometheus metrics endpoint
curl -s http://localhost:${API_PORT}/metrics | head -50 | tee .swarm/logs/metrics_sample.log

# Verify key metrics exist
curl -s http://localhost:${API_PORT}/metrics | grep -E "(http_requests_total|gabi_|python_)" | head -20
```

### PHASE 3: Health Endpoint Deep Check (10-15 min)
```bash
# Deep health check
curl -s http://localhost:${API_PORT}/health | jq . | tee .swarm/logs/health_detailed.json

# Check health of dependencies
curl -s http://localhost:${API_PORT}/health/ready 2>/dev/null | jq . || echo "Ready check not available"
curl -s http://localhost:${API_PORT}/health/live 2>/dev/null | jq . || echo "Live check not available"
```

### PHASE 4: Logging Validation (15-20 min)
```bash
# Verify structured logging works
python -c "
from src.gabi.logging_config import setup_logging
import structlog

setup_logging()
logger = structlog.get_logger()
logger.info('test_observability', agent='AGENT-7', test_id='obs_001')
print('Structured logging works')
"

# Check log output format
python -c "
import json
import logging
from src.gabi.logging_config import setup_logging
setup_logging()
logger = logging.getLogger('gabi.test')
logger.info(json.dumps({'event': 'test', 'metric': 42}))
"
```

### PHASE 5: OpenTelemetry Check (20-25 min)
```bash
# Verify OTel imports and setup
python -c "
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
print('OpenTelemetry SDK available')
"

# Check if tracing is configured
python -c "
from src.gabi.config import settings
print(f'Tracing enabled: {getattr(settings, \"tracing_enabled\", \"unknown\")}')
"
```

### PHASE 6: Prometheus Metrics Generation (25-30 min)
```bash
# Generate some traffic to create metrics
curl -s http://localhost:${API_PORT}/api/v1/sources >/dev/null
curl -s http://localhost:${API_PORT}/health >/dev/null
curl -s http://localhost:${API_PORT}/api/v1/search -X POST \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "sources": []}' >/dev/null 2>&1 || true

# Re-check metrics
curl -s http://localhost:${API_PORT}/metrics | grep -c "http_requests_total" || echo "0"
```

## Output Artifacts
Write to `.swarm/artifacts/AGENT-7-report.md`:
- Metrics endpoint status
- Key metrics found
- Health check results
- Logging configuration status
- Tracing availability

## Status Updates
Write to `.swarm/status/AGENT-7.json` every 2 minutes.

## Dependencies
- AGENT-3 (API must be running)

## Blocks
- AGENT-8 (uses observability data for final report)
