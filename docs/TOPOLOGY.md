# GABI DOU — Topologia oficial de produção (Fly.io)

> Última atualização: 2026-03-09  
> Fonte de verdade: [AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md](runbooks/AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md)

Este documento define a topologia única de produção. Todas as configs Fly, runbooks e referências de rede interna devem estar alinhadas a ela.

## Apps da topologia atual

| App | Função | Acesso | Config |
|-----|--------|--------|--------|
| `gabi-dou-frontend` | SPA estática (React/TS) | Público HTTPS | [ops/deploy/frontend-static/fly.toml](../ops/deploy/frontend-static/fly.toml) |
| `gabi-dou-web` | API FastAPI + ARQ upload_worker | Público HTTPS (API), interno (worker) | [ops/deploy/web/fly.toml](../ops/deploy/web/fly.toml) |
| `gabi-dou-worker` | Pipeline autônomo DOU + SQLite | Apenas interno | [ops/deploy/worker/fly.toml](../ops/deploy/worker/fly.toml) |
| `gabi-dou-es` | Elasticsearch (single-node) | Apenas interno | [ops/deploy/es/fly.toml](../ops/deploy/es/fly.toml) |
| `gabi-dou-redis` | Redis (rate limit + fila ARQ) | Apenas interno | Referenciado pelo web; deploy separado ou Fly Redis |
| `gabi-dou-db` | PostgreSQL (identidade/admin) | Apenas interno | [ops/deploy/postgres/fly.toml](../ops/deploy/postgres/fly.toml) |

**Importante:** O processo `upload_worker` no app `gabi-dou-web` é a fila ARQ para upload manual. Não é o pipeline autônomo. O pipeline autônomo roda no app `gabi-dou-worker`. Ver [FLY_WORKER_ARQ.md](runbooks/FLY_WORKER_ARQ.md).

## Diagrama de rede interna

```
                    Internet
                        │
    ┌───────────────────┼───────────────────┐
    │                   │                   │
    ▼                   ▼                   ▼
gabi-dou-frontend   gabi-dou-web        (não exposto)
(fly.dev)           (fly.dev /healthz,
                    /api/*)
                        │
                        │ proxy /api/worker/* → gabi-dou-worker.internal:8081
                        │ PG_DSN → gabi-dou-db.internal:5432
                        │ REDIS_URL → gabi-dou-redis.internal:6379
                        │ ES_URL → gabi-dou-es.internal:9200
                        ▼
    ┌──────────────────────────────────────────────────┐
    │  gabi-dou-worker (interno)                         │
    │  ES_URL → gabi-dou-es.internal:9200                │
    │  Volume: /data (registry.db, tmp, logs)            │
    └──────────────────────────────────────────────────┘
                        │
                        ▼
    ┌──────────────────────────────────────────────────┐
    │  gabi-dou-es (interno)                             │
    │  Porta 9200, volume próprio                        │
    └──────────────────────────────────────────────────┘
```

## Ordem de deploy recomendada

1. **Postgres** — `fly deploy -c ops/deploy/postgres/fly.toml` (ou máquina já existente)
2. **Redis** — criar/app `gabi-dou-redis` se ainda não existir; web depende dele
3. **Elasticsearch** — `fly deploy -c ops/deploy/es/fly.toml`
4. **Worker** — `fly deploy -c ops/deploy/worker/fly.toml`
5. **Web** — `fly deploy -c ops/deploy/web/fly.toml`
6. **Frontend** — `fly deploy -c ops/deploy/frontend-static/fly.toml`

Ordem mínima para o pipeline funcionar: Postgres + Redis → ES → Worker → Web → Frontend.

## Referências

- [AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md](runbooks/AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md) — estado atual e preflight
- [AUTONOMOUS_DOU_PIPELINE_PROMPT.md](runbooks/AUTONOMOUS_DOU_PIPELINE_PROMPT.md) — arquitetura definitiva (PATCH 2)
- [FLY_SPLIT_DEPLOY.md](runbooks/FLY_SPLIT_DEPLOY.md) — deploy split frontend/web
- [FLY_WORKER_ARQ.md](runbooks/FLY_WORKER_ARQ.md) — diferença entre upload_worker e worker autônomo
