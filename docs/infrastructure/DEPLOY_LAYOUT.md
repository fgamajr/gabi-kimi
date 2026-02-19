# Layout de Deploy (Dev / Staging / Prod)

Este documento define o layout alvo de infraestrutura para cada ambiente e a decisão de deploy no Fly.io.

---

## 1. Visão por ambiente

### 1.1 Desenvolvimento (local)

**Objetivo:** Máxima produtividade: hot reload, debug, infra consistente.

| Componente     | Onde roda              | Acesso                    |
|----------------|------------------------|---------------------------|
| PostgreSQL     | Docker Compose         | `localhost:5433`          |
| Elasticsearch  | Docker Compose         | `localhost:9200`          |
| Redis          | Docker Compose         | `localhost:6379`          |
| Gabi.Api       | Host (`dotnet run`)    | `localhost:5100`          |
| Gabi.Worker    | Host (`dotnet run`)    | processo em background    |

**Fluxo:**
1. `./scripts/dev-up.sh` — sobe só infra (postgres, elasticsearch, redis).
2. API e Worker rodam no host; conectam em `localhost` com portas do compose.
3. `./scripts/dev-down.sh` — derruba infra.

**Config:** `appsettings.Development.json` / `GABI_SOURCES_PATH` (opcional). Nenhum container da aplicação em dev.

---

### 1.2 Staging (opcional)

**Objetivo:** Validar deploy e integração antes de prod.

| Componente     | Onde roda                    | Observação                    |
|----------------|------------------------------|-------------------------------|
| PostgreSQL     | Fly Postgres ou externo      | DB gerenciado                 |
| Elasticsearch  | Externo ou omitido           | Pode usar só PG inicialmente  |
| Redis          | Upstash / Fly Redis ou omitido | Cache opcional             |
| Gabi.Api       | Fly.io (app `gabi-api`)      | HTTP na porta 8080            |
| Gabi.Worker    | Fly.io (app `gabi-worker`)   | Processo sem HTTP             |

**Fluxo:** Igual a prod, com apps Fly separados; secrets e env de staging.

---

### 1.3 Produção

**Objetivo:** Disponibilidade, escala independente, custo previsível.

| Componente     | Onde roda                    | Observação                    |
|----------------|------------------------------|-------------------------------|
| PostgreSQL     | Fly Postgres / Neon / RDS    | Fonte de verdade              |
| Elasticsearch  | Bonsai / Elastic Cloud / omitir | Só quando busca avançada for necessária |
| Redis          | Upstash / Fly Redis / omitir | Cache/DLQ quando implementado |
| Gabi.Api       | Fly.io (app `gabi-api`)      | Escala por instâncias         |
| Gabi.Worker    | Fly.io (app `gabi-worker`)   | 1 instância ou mais conforme carga |

**Fluxo:** Cada app é deployado com `fly deploy` no seu próprio diretório/config; conectam via secrets (connection strings, URLs).

---

## 2. Diagrama de deploy (produção / Fly.io)

```
                    ┌─────────────────────────────────────────┐
                    │                  Fly.io                  │
                    ├─────────────────────────────────────────┤
                    │  ┌─────────────┐  ┌─────────────┐       │
                    │  │  gabi-api   │  │ gabi-worker │       │
                    │  │  (HTTP)     │  │ (process)   │       │
                    │  └──────┬──────┘  └──────┬──────┘       │
                    │         │                 │              │
                    │         └────────┬────────┘              │
                    │                  │                        │
                    │         ┌────────▼────────┐              │
                    │         │ Fly Postgres     │              │
                    │         │ (ou externo)     │              │
                    │         └─────────────────┘              │
                    └─────────────────────────────────────────┘
```

---

## 3. Referência rápida de comandos

| Ação        | Dev (local)                 | Staging/Prod (Fly)                    |
|-------------|-----------------------------|--------------------------------------|
| Subir infra | `./scripts/dev infra up`    | N/A (serviços gerenciados)           |
| Rodar API   | `dotnet run -p src/Gabi.Api` | `fly deploy` no app gabi-api      |
| Rodar Worker| `dotnet run -p src/Gabi.Worker` | `fly deploy` no app gabi-worker |
| Parar infra | `./scripts/dev infra down`  | `fly apps stop` / scale 0            |

---

## 4. Variáveis e secrets por ambiente

| Variável / Secret              | Dev              | Staging/Prod (Fly)     |
|--------------------------------|------------------|------------------------|
| `ConnectionStrings__Default`    | appsettings.Dev  | `fly secrets set`      |
| `GABI_SOURCES_PATH`            | Opcional (env)   | Volume ou URL (não bake na imagem) |
| `GABI_ELASTICSEARCH_URL`       | localhost:9200   | Secret                 |
| `GABI_REDIS_URL`               | localhost:6379   | Secret (se usar)       |
| `ASPNETCORE_ENVIRONMENT`       | Development      | Production             |
| `ASPNETCORE_URLS`              | (default)        | http://+:8080          |

Consulte [FLY_DEPLOY.md](FLY_DEPLOY.md) para detalhes de apps e secrets no Fly.io.
