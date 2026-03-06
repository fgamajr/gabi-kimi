> Last verified: 2026-03-06

# Plano RAG Snapshot

Registro historico do plano de evolucao RAG.

## Status

- Classificacao: `ACTIVE HISTORICAL PLAN`
- Ainda util como backlog tecnico
- Nao substitui o runbook atual

## Ja Implementado

- chunking contextual em [ingest/chunker.py](ingest/chunker.py)
- backfill de chunks em [scripts/backfill_chunks.py](scripts/backfill_chunks.py)
- embeddings em [ingest/embedding_pipeline.py](ingest/embedding_pipeline.py)
- backfill vetorial em [scripts/backfill_embeddings.py](scripts/backfill_embeddings.py)
- retrieval hibrido em [search/adapters.py](search/adapters.py)

## Ainda Pendente

- reranker avancado
- calibracao final de relevancia
- backfill vetorial completo conforme capacidade do ambiente
