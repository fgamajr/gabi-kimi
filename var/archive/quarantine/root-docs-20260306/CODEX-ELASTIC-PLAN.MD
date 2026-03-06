> Last verified: 2026-03-06

# CODEX Elastic Migration Plan

Snapshot historico do plano que levou a integracao Elasticsearch.

## Status

- Classificacao: `HISTORICAL PLAN`
- Parte relevante ja implementada
- Nao usar como runbook operacional

## Estado Atual

- indexacao lexical em [ingest/es_indexer.py](ingest/es_indexer.py)
- adapter lexical e hibrido em [search/adapters.py](search/adapters.py)
- MCP Elasticsearch/hibrido em [mcp_es_server.py](mcp_es_server.py)
- configuracao reconciliada em [.env.example](.env.example)

## Fonte Atual

- [README.md](README.md)
- [PIPELINE.md](PIPELINE.md)
- [ARCHITECTURE_DIAGRAMS.md](ARCHITECTURE_DIAGRAMS.md)
