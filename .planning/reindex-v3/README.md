# Reindex V3 Packet

This directory is the execution packet for the DOU reindex-v3 effort.

## Canonical Docs

- `ARCHITECTURE.md`
  - frozen architecture contract
  - schemas, signals, propagation model, chunking contract, rollout stages
- `EXECUTION.md`
  - ordered implementation sequence
  - exit criteria and validation gates
- `RISKS.md`
  - failure modes, rollback concerns, operational watchlist

## Specialist Notes

- `agents/schema-signals.md`
  - parent schema additions, signal fields, freshness maintenance, mapping diff
- `agents/chunking.md`
  - deterministic chunking rules, limits, hashes, pruning ledger
- `agents/cdc-rollout.md`
  - Mongo source-of-truth contract, async propagation, alias cutover, DLQs
- `agents/entities-embeddings.md`
  - entity dictionary persistence/versioning and embedding lifecycle

## Execution Rule

If a specialist note conflicts with a canonical doc, the canonical doc wins until
the coordinator explicitly updates it.

## First Implementation Milestones

1. Run the mapping reality gate for the live `gabi_documents` alias.
2. Freeze the parent v2 field contract and version fields.
3. Define the Mongo outbox/change-stream propagation event schema.
4. Define the deterministic chunk manifest contract.
5. Start parent-index changes before chunk-index or embedding work.

## Phase 0 Command

```bash
docker compose exec -T backend python -m src.backend.ingest.reindex_v3 mapping-diff \
  --report /workspace/.planning/reindex-v3/mapping-diff-live-vs-parent-v2.json
```

Initial baseline from the first run:

- live alias target: `gabi_documents -> gabi_documents_v1`
- expected parent-v2 mapping fields: `91`
- live parent mapping fields: `43`
- missing in live: `48` parent-v2 fields, including restored `topics` and `topic_primary`
- no type mismatches detected on shared fields

Explicit contract decision:

- `topics` and `topic_primary` are restored in the parent-v2 rollout and are not deferred

## Parent Backfill Commands

```bash
docker compose exec -T backend python -m src.backend.ingest.reindex_v3 parent-backfill \
  --index gabi_documents_v2 \
  --recreate-index --yes-destroy
```

```bash
docker compose exec -T backend python -m src.backend.ingest.reindex_v3 parent-stats \
  --index gabi_documents_v2
```

```bash
docker compose exec -T backend python -m src.backend.ingest.reindex_v3 parent-verify \
  --index gabi_documents_v2 --sample-size 100
```

Smoke result:

- throwaway index `gabi_documents_v2_smoke` indexed `50` docs with `--max-batches 1`
- no alias change was performed
- parent DLQ remained at `0`
