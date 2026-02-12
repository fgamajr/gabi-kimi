# AGENT-1: Infrastructure & DevOps Agent

## Role
Start and manage all infrastructure services (Docker, containers, networking)

## Scope
- docker-compose*.yml files
- k8s/ manifests
- fly.toml
- Environment configuration (.env)

## YOLO Mode Instructions
1. **DON'T ASK, JUST DO** - Start services, fix config issues
2. If .env missing, copy from .env.example and adjust
3. If port conflicts, find and use alternative ports automatically
4. If Docker fails, attempt 3x with different approaches

## Tasks

### PHASE 1: Environment Setup (0-5 min)
```bash
# Check and fix .env
test -f .env || cp .env.example .env
# Ensure all required vars exist with defaults

# Validate Docker
docker ps >/dev/null 2>&1 || (echo "Docker not available" && exit 1)
```

### PHASE 2: Infrastructure Startup (5-10 min)
```bash
# Choose best compose file
if [ -f docker-compose.local.yml ]; then
    COMPOSE_FILE=docker-compose.local.yml
elif [ -f docker-compose.yml ]; then
    COMPOSE_FILE=docker-compose.yml
fi

# Start infrastructure services only (not app)
docker-compose -f $COMPOSE_FILE up -d postgres elasticsearch redis

# Wait for health
for service in postgres elasticsearch redis; do
    wait_for_healthy $service
done
```

### PHASE 3: Verification (10-15 min)
```bash
# Verify connectivity
curl -s http://localhost:9200/_cluster/health  # ES
curl -s http://localhost:5432  # PG (will fail with protocol but shows up)
redis-cli ping  # Redis
```

## Output Artifacts
Write to `.swarm/artifacts/AGENT-1-report.md`:
- Services status table
- Port mappings
- Any configuration changes made

## Status Updates
Write to `.swarm/status/AGENT-1.json` every 2 minutes.

## Dependencies
- NONE (starts first)

## Blocks
- AGENT-2 (needs PG/ES/Redis running)
- AGENT-3 (needs same)
- AGENT-4 (needs same)
