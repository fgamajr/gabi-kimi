# AGENT-3: API & Web Layer Agent

## Role
Start and validate FastAPI application, all REST endpoints, authentication

## Scope
- src/gabi/api/
- src/gabi/auth/
- src/gabi/main.py
- src/gabi/middleware/

## YOLO Mode Instructions
1. **AUTO-CONFIGURE** - If config missing, use smart defaults
2. **PORT FLEXIBILITY** - Try 8000, then 8001, 8002, etc.
3. **AUTH BYPASS FOR TESTS** - If Keycloak unreachable, allow test mode
4. **ROUTE VERIFICATION** - Hit every route, document what works/fails

## Tasks

### PHASE 1: Wait for Database (Blocked until AGENT-2 completes)
Poll `.swarm/status/AGENT-2.json` for `status == "completed"`

### PHASE 2: API Startup (5-10 min)
```bash
# Check if port 8000 is available
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null ; then
    export PORT=8001
else
    export PORT=8000
fi

# Start API in background
export GABI_ENVIRONMENT=local
export GABI_DEBUG=true
export GABI_AUTH_ENABLED=false  # YOLO: disable auth for testing

uvicorn src.gabi.main:app --host 0.0.0.0 --port $PORT --reload &
API_PID=$!
echo $API_PID > .swarm/agents/3-api/api.pid

# Wait for startup
sleep 5
curl -s http://localhost:$PORT/health | jq .
```

### PHASE 3: Route Validation (10-15 min)
```bash
BASE_URL="http://localhost:${PORT:-8000}"

# Health check
curl -s $BASE_URL/health | jq .

# API routes
curl -s $BASE_URL/api/v1/sources | jq .
curl -s $BASE_URL/api/v1/search -X POST -H "Content-Type: application/json" \
  -d '{"query": "test", "sources": ["tcu_acordaos"], "limit": 5}' | jq .

# Admin routes (if available)
curl -s $BASE_URL/api/v1/admin/health | jq . 2>/dev/null || echo "Admin routes may require auth"

# OpenAPI schema
curl -s $BASE_URL/openapi.json | jq '.info'
```

### PHASE 4: Auth System Test (15-20 min)
```bash
# Test JWT middleware loads
python -c "
from src.gabi.auth.jwt import JWTValidator
from src.gabi.auth.middleware import AuthMiddleware
print('Auth modules load successfully')
"

# If Keycloak configured, test JWKS fetch
```

## Output Artifacts
Write to `.swarm/artifacts/AGENT-3-report.md`:
- API startup status
- Available routes table
- Port being used
- Any auth bypasses enabled

## Status Updates
Write to `.swarm/status/AGENT-3.json` every 2 minutes.

## Dependencies
- AGENT-1 (for services)
- AGENT-2 (for migrations)

## Blocks
- AGENT-6 (needs API running for e2e tests)
- AGENT-8 (needs same)
