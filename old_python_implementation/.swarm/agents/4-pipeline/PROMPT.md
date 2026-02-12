# AGENT-4: Pipeline Workers Agent

## Role
Start and validate Celery workers, task queue, and ingestion pipeline

## Scope
- src/gabi/pipeline/
- src/gabi/tasks/
- src/gabi/worker.py
- src/gabi/crawler/

## YOLO Mode Instructions
1. **WORKER AUTO-SCALE** - Start with 2 workers, scale if needed
2. **QUEUE DRAINING** - If DLQ has items, process them
3. **MOCK EXTERNAL CALLS** - If TCU API unavailable, use test fixtures
4. **CONTINUE ON PARTIAL** - If some pipeline steps fail, continue with others

## Tasks

### PHASE 1: Wait for Infrastructure (Blocked until AGENT-1 completes)
Poll `.swarm/status/AGENT-1.json` for `status == "completed"`

### PHASE 2: Celery Worker Startup (5-10 min)
```bash
# Verify Redis is accessible
redis-cli ping | grep PONG || exit 1

# Start Celery worker in background
celery -A src.gabi.worker worker --loglevel=info --concurrency=2 &
WORKER_PID=$!
echo $WORKER_PID > .swarm/agents/4-pipeline/worker.pid

# Wait for worker to register
sleep 5

# Check worker status
celery -A src.gabi.worker status 2>/dev/null || echo "Status check failed but worker may be running"
```

### PHASE 3: Pipeline Components Test (10-15 min)
```bash
# Test each pipeline component
python -c "
from src.gabi.pipeline.discovery import DiscoveryService
from src.gabi.pipeline.fetcher import Fetcher
from src.gabi.pipeline.parser import Parser
from src.gabi.pipeline.chunker import Chunker
from src.gabi.pipeline.embedder import Embedder
from src.gabi.pipeline.indexer import Indexer
from src.gabi.pipeline.deduplication import DedupService

print('All pipeline components import successfully')
"

# Test with sample data if available
if [ -f tests/fixtures/sample_document.json ]; then
    echo "Running pipeline with sample document..."
    # Run test ingestion
fi
```

### PHASE 4: Task Queue Validation (15-20 min)
```bash
# Trigger test task
python -c "
from src.gabi.tasks.health import health_check_task
result = health_check_task.delay()
print(f'Task ID: {result.id}')
"

# Check Flower if available
curl -s http://localhost:5555/api/workers | jq . 2>/dev/null || echo "Flower not running"
```

### PHASE 5: DLQ Check (20-25 min)
```bash
# Check for dead letter queue items
python -c "
from src.gabi.models.dlq import DeadLetterQueue
# Query DLQ table for failed tasks
"
```

## Output Artifacts
Write to `.swarm/artifacts/AGENT-4-report.md`:
- Worker process status
- Queue statistics
- Pipeline component health
- DLQ status

## Status Updates
Write to `.swarm/status/AGENT-4.json` every 2 minutes.

## Dependencies
- AGENT-1 (Redis must be running)
- AGENT-2 (DB for task results)

## Blocks
- AGENT-8 (needs workers for end-to-end tests)
