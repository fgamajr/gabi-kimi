# AGENT-6: Testing & QA Agent

## Role
Execute full test suite: unit, integration, and end-to-end tests

## Scope
- tests/unit/
- tests/integration/
- tests/e2e/
- Coverage reporting

## YOLO Mode Instructions
1. **RUN EVERYTHING** - Execute all tests, don't stop on first failure
2. **FLAKY TEST RETRY** - Retry failed tests once (may be timing issues)
3. **COVERAGE THRESHOLD** - Aim for >80%, report actual number
4. **CATEGORIZE FAILURES** - Critical vs optional features

## Tasks

### PHASE 1: Wait for API (Blocked until AGENT-3 completes)
Poll `.swarm/status/AGENT-3.json` for `status == "completed"`

### PHASE 2: Test Environment Setup (5-10 min)
```bash
# Verify test dependencies
pip install -q pytest pytest-asyncio pytest-cov pytest-mock httpx

# Check test database configuration
export GABI_DATABASE_URL="${TEST_DATABASE_URL:-postgresql+asyncpg://postgres:postgres@localhost:5432/gabi_test}"

# Create test DB if not exists
psql postgres://postgres:postgres@localhost:5432 -c "CREATE DATABASE gabi_test;" 2>/dev/null || echo "Test DB exists or will be created"
```

### PHASE 3: Unit Tests (10-15 min)
```bash
cd /home/fgamajr/dev/gabi-kimi

# Run unit tests with coverage
pytest tests/unit -v --tb=short --cov=src/gabi --cov-report=term-missing --cov-report=html:.swarm/artifacts/coverage_html 2>&1 | tee .swarm/logs/unit_tests.log

# Capture exit code
UNIT_EXIT=${PIPESTATUS[0]}
echo "Unit tests exit code: $UNIT_EXIT"
```

### PHASE 4: Integration Tests (15-25 min)
```bash
# Run integration tests
pytest tests/integration -v --tb=short 2>&1 | tee .swarm/logs/integration_tests.log

INTEGRATION_EXIT=${PIPESTATUS[0]}
echo "Integration tests exit code: $INTEGRATION_EXIT"
```

### PHASE 5: E2E Tests (25-35 min)
```bash
# Run e2e tests
pytest tests/e2e -v --tb=short 2>&1 | tee .swarm/logs/e2e_tests.log

E2E_EXIT=${PIPESTATUS[0]}
echo "E2E tests exit code: $E2E_EXIT"
```

### PHASE 6: Coverage Report (35-40 min)
```bash
# Generate coverage report
pytest tests/ --cov=src/gabi --cov-report=xml:.swarm/artifacts/coverage.xml --cov-report=html:.swarm/artifacts/coverage_html

# Calculate coverage percentage
COVERAGE=$(grep -o 'percent="[0-9.]*"' .swarm/artifacts/coverage.xml | head -1 | sed 's/percent="//;s/"//')
echo "Overall coverage: ${COVERAGE}%"
```

## Output Artifacts
Write to `.swarm/artifacts/AGENT-6-report.md`:
- Unit test summary (pass/fail counts)
- Integration test summary
- E2E test summary
- Coverage percentage
- Failed test details

Also create:
- `.swarm/artifacts/test_results.json` - Machine readable results

## Status Updates
Write to `.swarm/status/AGENT-6.json` every 2 minutes.

## Dependencies
- AGENT-3 (API must be running for e2e)
- AGENT-2 (DB for all tests)

## Blocks
- NONE (reporting only)
