> Last verified: 2026-03-06

# CODEX Redis Query-Assist Plan

Snapshot historico do plano de autocomplete, top searches e sinais Redis.

## Status

- Classificacao: `HISTORICAL PLAN`
- Partes implementadas no codigo atual
- Nao usar como fonte primaria de configuracao

## Estado Atual

- sinais Redis em [search/redis_signals.py](search/redis_signals.py)
- endpoints em [web_server.py](web_server.py):
  - `/api/suggest`
  - `/api/autocomplete`
  - `/api/top-searches`
  - `/api/search-examples`
- env reconciliado em [.env.example](.env.example)

## Fonte Atual

- [README.md](README.md)
- [PIPELINE.md](PIPELINE.md)
