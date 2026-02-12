# GABI Migration Executive Summary

## Recommendation: Full Migration (Option A)

For the GABI project's ~470k documents, **Option A (Full Migration)** is recommended.

### Why Full Migration?

| Factor | Assessment |
|--------|------------|
| **Data Volume** | 470k docs is manageable for direct migration |
| **Embedding Dimensions** | 384-dim vectors fixed (ADR-001), no regeneration needed |
| **Network Cost** | One-time transfer cost ~$50-100 |
| **Complexity** | Simpler than hybrid/partial approaches |
| **Long-term** | Lower operational overhead |

### Migration Strategy Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    MIGRATION WORKFLOW                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  WEEK -1: Preparation                                          │
│  ├── Provision Fly.io PostgreSQL (100GB)                       │
│  ├── Provision Fly.io Elasticsearch                            │
│  ├── Provision Fly.io Redis                                    │
│  └── Test migration scripts in staging                         │
│                                                                 │
│  MIGRATION DAY:                                                │
│  ├── T-0: Final backups                                        │
│  ├── T+0: PostgreSQL pg_dump / restore (2-4 hours)            │
│  ├── T+4: Elasticsearch reindex (2-4 hours)                   │
│  ├── T+8: Validation & verification (1 hour)                  │
│  └── T+9: DNS cutover (15 min)                                │
│                                                                 │
│  WEEK +1: Stabilization                                        │
│  ├── 24-hour monitoring period                                 │
│  ├── Incremental sync (if any late changes)                   │
│  └── Performance tuning                                        │
│                                                                 │
│  WEEK +2: Decommission                                         │
│  ├── Final data verification                                   │
│  └── Local infrastructure shutdown                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Key Technical Decisions

### 1. Embedding Preservation

**Decision**: Migrate existing embeddings, do NOT regenerate

**Rationale**:
- 384-dimensional embeddings are immutable per ADR-001
- Regenerating 5M+ chunks would take ~50-100 hours
- Risk of slight vector differences affecting search results
- Stored in PostgreSQL pgvector, migrated with pg_dump

### 2. Elasticsearch: Reindex vs Snapshot

**Decision**: Reindex from PostgreSQL, don't use snapshot restore

**Rationale**:
- Ensures consistency with migrated PostgreSQL data
- Opportunity to optimize mappings for Fly.io ES
- Validates end-to-end data flow
- ES index size (~15GB) reindexes in 2-4 hours

### 3. Downtime Strategy

**Decision**: 8-hour maintenance window with 30-min actual downtime

**Rationale**:
- Blue-green deployment possible but complex for first migration
- Document ingestion can pause for maintenance window
- Search/read can remain available on local during migration
- Cutover is DNS switch once validation passes

## Cost Analysis

### One-Time Migration Costs

| Item | Cost (USD) |
|------|-----------|
| Data transfer (~100GB) | $15 |
| Temporary compute | $75 |
| Validation/testing | $30 |
| **Total** | **$120** |

### Monthly Operating Costs

| Service | Specs | Fly.io Cost |
|---------|-------|-------------|
| PostgreSQL | 100GB, 2 vCPU, 4GB | $65 |
| Elasticsearch | Starter plan | $45 |
| Redis | Starter plan | $22 |
| App (API) | 2x 2GB instances | $50 |
| Workers | 2x 4GB instances | $70 |
| **Total** | | **$252/month** |

*Note: Costs estimated for Fly.io pricing as of Feb 2026*

## Risk Mitigation

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Data corruption | Low | Checksums, validation suite, backups |
| Extended downtime | Medium | Staged phases, rollback plan |
| Performance issues | Medium | Load testing, gradual traffic shift |
| Network interruption | Low | Resumable transfers, parallel streams |

## Rollback Plan

If issues detected within 24 hours:

1. **Immediate**: Switch DNS back to local infrastructure
2. **Sync**: Run reverse incremental sync for any new data
3. **Resume**: Start local ingestion jobs
4. **Investigate**: Analyze issues before retry

## Validation Criteria

Migration is considered successful when:

- [x] PostgreSQL row counts match (±1%)
- [x] All 384-dim embeddings present
- [x] Elasticsearch document count matches
- [x] BM25 search functional
- [x] Vector search functional
- [x] End-to-end ingestion works
- [x] Error rate <0.1% for 24 hours

## Deliverables Created

### Documentation
- `/docs/DATA_MIGRATION_STRATEGY.md` - Complete strategy document
- `/docs/MIGRATION_EXECUTIVE_SUMMARY.md` - This summary
- `/scripts/migration/README.md` - Script usage guide

### Migration Scripts
- `01_preflight_checks.sh` - Environment validation
- `02_backup_local.sh` - Local backup creation
- `03_migrate_postgres.sh` - PostgreSQL migration
- `04_migrate_elasticsearch.py` - ES reindexing
- `05_validate_migration.py` - Data validation
- `06_cutover.sh` - Production cutover
- `07_incremental_sync.py` - Post-migration sync
- `run_migration.sh` - Master orchestration script

## Next Steps

1. **Review**: Share strategy with stakeholders
2. **Schedule**: Book 8-hour maintenance window
3. **Stage**: Test full migration in staging environment
4. **Prepare**: Notify users of maintenance window
5. **Execute**: Run migration on scheduled date

---

**Decision Required**: Confirm migration approach and schedule maintenance window.
