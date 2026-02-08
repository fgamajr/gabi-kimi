# AGENT-2: Database & Storage Agent

## Role
Manage PostgreSQL, pgvector, Elasticsearch indices, and all data persistence

## Scope
- alembic/ migrations
- src/gabi/models/
- src/gabi/db.py
- PGVector configuration
- Elasticsearch index setup

## YOLO Mode Instructions
1. **AUTO-FIX MIGRATIONS** - If migration fails, try autogenerate
2. **RESET IF NEEDED** - If pgvector fails, suggest clean slate
3. **CREATE MISSING INDICES** - Verify and create ES indices automatically
4. **DIMENSION CORRECTION** - Ensure 384d embeddings everywhere

## Tasks

### PHASE 1: Wait for Infrastructure (Blocked until AGENT-1 completes)
Poll `.swarm/status/AGENT-1.json` for `status == "completed"`

### PHASE 2: Database Setup (5-10 min)
```bash
# Verify pgvector extension
psql $DATABASE_URL -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Verify 384 dimension
psql $DATABASE_URL -c "SHOW vector.dim;" 2>/dev/null || echo "Using default"

# Run migrations
alembic upgrade head

# Verify all tables exist
psql $DATABASE_URL -c "\dt" | grep -E "(documents|chunks|sources|executions)"
```

### PHASE 3: Elasticsearch Setup (10-15 min)
```bash
# Create indices if not exist
python -c "
from src.gabi.services.elasticsearch_setup import setup_indices
import asyncio
asyncio.run(setup_indices())
"

# Verify mappings
curl -s http://localhost:9200/documents/_mapping | jq '.documents.mappings.properties'
```

### PHASE 4: Data Validation (15-20 min)
```bash
# Check schema alignment
python -c "
from src.gabi.models import Document, Chunk, Source
# Verify models load without errors
"

# Run quick data integrity check
```

## Output Artifacts
Write to `.swarm/artifacts/AGENT-2-report.md`:
- Migration status
- Table list with row counts (if any)
- ES indices and their mappings
- pgvector configuration

## Status Updates
Write to `.swarm/status/AGENT-2.json` every 2 minutes.

## Dependencies
- AGENT-1 (PG/ES/Redis must be running)

## Blocks
- AGENT-3 (needs migrations complete)
- AGENT-4 (needs same)
- AGENT-6 (needs same)
