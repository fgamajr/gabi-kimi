# Observabilidade

## Métricas (Prometheus)
- documents_ingested_total
- documents_deduplicated_total
- fetch_skipped_total
- fetch_failed_total
- embeddings_generated_total

## Logs
- Correlation ID por execution_manifest
- Logs estruturados JSON

## Tracing
- Cada documento possui lineage:
  source → transform → document → api

Persistido em lineage_nodes / lineage_edges.
