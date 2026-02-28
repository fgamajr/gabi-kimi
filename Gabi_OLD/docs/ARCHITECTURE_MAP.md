# GABI — Mapa de Arquitetura (Contexto Inicial)

Documento gerado para onboarding: estrutura do projeto, fluxo de runtime, infraestrutura, premissas e incógnitas. **Somente leitura — nenhum código foi alterado.**

---

## 1. Estrutura do Projeto

```
gabi-kimi/
├── GabiSync.sln                    # Solution única
├── sources_v2.yaml                 # Catálogo canônico de fontes (YAML v2)
├── docker-compose.yml             # Infra + API/Worker opcionais (profiles)
├── docker/postgres/init/          # Init SQL (extensions, timezone)
├── scripts/dev                    # CLI: infra, app, db
├── src/
│   ├── Gabi.Contracts/            # Layer 0–1: interfaces, DTOs, enums (zero deps)
│   ├── Gabi.Postgres/             # Layer 2–3: EF Core, entidades, repositórios
│   ├── Gabi.Discover/             # Layer 4: descoberta de URLs por estratégia
│   ├── Gabi.Fetch/                # Layer 4: HTTP fetch, streaming, formatos
│   ├── Gabi.Ingest/               # Layer 4: parse, normalização, chunk, embed, index
│   ├── Gabi.Sync/                 # Layer 4: orquestração/retry (presente na solução)
│   ├── Gabi.Jobs/                 # Layer 4: definições de jobs (presente na solução)
│   ├── Gabi.Api/                  # Layer 5: REST API, JWT, dashboard, enqueue
│   └── Gabi.Worker/               # Layer 5: Hangfire server, executores, projeção
└── tests/
    ├── Gabi.Architecture.Tests/   # Regras de camadas (obrigatório após mudança de refs)
    ├── Gabi.Api.Tests/
    ├── Gabi.Postgres.Tests/
    ├── Gabi.Discover.Tests/
    ├── Gabi.Fetch.Tests/
    ├── Gabi.Ingest.Tests/
    ├── Gabi.Jobs.Tests/
    ├── Gabi.Sync.Tests/
    ├── System/                    # ZeroKelvinHarness, System.Tests
    └── ReliabilityLab/            # Chaos, ambiente, pipeline
```

**Linguagem:** C# 12, .NET 8.  
**Package manager:** NuGet (SDK-style csproj).  
**Testes:** xUnit; arquitetura com NetArchTest.Rules.

---

## 2. Pontos de Entrada e Fluxo de Runtime

| Entrada | Tipo | Função |
|--------|------|--------|
| `src/Gabi.Api/Program.cs` | ASP.NET Core Web App | API REST (porta 5100 ou 8080 no container). Autenticação JWT (viewer/operator/admin), dashboard, seed/fases, busca, health. **Enfileira** jobs via Hangfire (Postgres); não executa jobs. |
| `src/Gabi.Worker/Program.cs` | Host (Worker) | Hangfire Server (filas `seed`, `discovery`, `fetch`, `ingest`, `embed`, `default`), executores de jobs, TEI/ONNX embedder, Elasticsearch, projeção WAL, Temporal (opcional), drift-audit recorrente. |

**Fluxo pipeline (alto nível):**

1. **Seed** — `POST /api/v1/dashboard/seed` → `IDashboardService.SeedSourcesAsync` → `IJobQueueRepository.EnqueueAsync` (catalog_seed) → Hangfire → Worker executa `CatalogSeedJobExecutor` → lê `sources_v2.yaml`, persiste em PostgreSQL (`source_registries`, `seed_runs`).
2. **Discovery** — `POST .../sources/{id}/phases/discovery` → enfileira job discovery → Worker `SourceDiscoveryJobExecutor` → descobre URLs → `discovered_links`.
3. **Fetch** — fase fetch → `FetchJobExecutor` → HTTP, formatos (CSV, ZIP/XML DOU, etc.) → `fetch_items` / documentos brutos.
4. **Ingest** — `IngestJobExecutor` → parse, normalização, SHA-256 (dedup), gravação em `documents`.
5. **Chunk + fan-out** — `ChunkAndExtractJobExecutor` → BM25 (Elasticsearch), embeddings (pgvector), KG (document_relationships). `EmbedAndIndexJobExecutor` está obsoleto.

A API usa `StubGabiJobRunner`; o Worker usa `GabiJobRunner` real e resolve `IJobExecutor` por tipo de job.

---

## 3. Infraestrutura

| Componente | Porta (host) | Uso |
|------------|--------------|-----|
| **PostgreSQL 15** | 5433→5432 | Dados principais, Hangfire storage, job_registry, WAL lógico (replication slots). Extensions: uuid-ossp, pg_trgm, pgvector. |
| **Elasticsearch 8.11** | 9200 | Índice BM25 (texto). Não armazena vetores (movidos para pgvector). |
| **Redis 7** | 6380→6379 | Health check na API se configurado; Worker appsettings referencia; não é usado pelo Hangfire (Hangfire usa Postgres). |
| **TEI** (profile `tei`) | 8080→80 | Text Embeddings Inference, 384 dim, modelo paraphrase-multilingual-MiniLM-L12-v2. Opcional: ONNX local ou HashEmbedder em dev. |
| **Temporal** (sem profile) | 7233, 8233 | Presente no docker-compose; orquestração opcional por fonte (Phase B). |
| **Gabi.Api** (profile `api`) | 5100→8080 | Container da API. |
| **Gabi.Worker** (profile `worker`) | — | Container do Worker. |

Scripts: `./scripts/dev infra up|down|destroy`, `./scripts/dev db apply|status|create`, `./scripts/dev app up|stop|status`.

---

## 4. Mapa de Arquitetura (Resumido)

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                    Cliente / Operador                     │
                    └───────────────────────────┬─────────────────────────────┘
                                                │ HTTP (JWT)
                    ┌───────────────────────────▼───────────────────────────────┐
                    │  Gabi.Api (Layer 5)                                       │
                    │  Endpoints: /api/v1/dashboard/*, /api/v1/search,          │
                    │  /api/v1/auth, /api/v1/documents, /api/v1/graph, /hangfire │
                    │  IJobQueueRepository → Hangfire (enqueue only)             │
                    └───────────────────────────┬───────────────────────────────┘
                                                │ Postgres (Hangfire tables + job_registry)
                    ┌───────────────────────────▼───────────────────────────────┐
                    │  PostgreSQL                                               │
                    │  source_registries, discovered_links, fetch_items,        │
                    │  documents, document_embeddings, document_relationships,  │
                    │  job_registry, seed_runs, workflow_events, ...            │
                    └───────────────────────────┬───────────────────────────────┘
                                                │
                    ┌───────────────────────────▼───────────────────────────────┐
                    │  Gabi.Worker (Layer 5)                                    │
                    │  Hangfire Server (queues: seed, discovery, fetch, ingest,  │
                    │  embed, default) → IGabiJobRunner → IJobExecutor            │
                    │  CatalogSeed | SourceDiscovery | Fetch | Ingest |          │
                    │  ChunkAndExtract | EmbedAndIndex (obsolete) | Media | Drift│
                    └──┬────────────────┬────────────────┬─────────────────────┘
                       │                │                │
         ┌─────────────▼──┐   ┌────────▼────────┐   ┌───▼────────────┐
         │ Elasticsearch  │   │ TEI ou ONNX     │   │ WAL Projection │
         │ (BM25 index)   │   │ (384-dim embed) │   │ (Logical Repl) │
         └────────────────┘   └─────────────────┘   └────────────────┘
```

**Camadas estritas (LayeringTests):** Contracts (0–1) → Postgres (2–3) → Discover, Fetch, Ingest, Sync, Jobs (4) → Api, Worker (5). Domain (4) não pode referenciar Postgres nem EF.

---

## 5. Premissas e Decisões Assumidas

- **PostgreSQL é fonte da verdade**; Elasticsearch e pgvector são índices derivados.
- **sources_v2.yaml** é a única definição canônica de fontes; seed persiste no banco com retry.
- **Hangfire** usa apenas Postgres (não Redis) para storage e filas.
- **Redis** é opcional (health check e possível uso futuro; Worker tem RedisUrl em appsettings).
- **Temporal** está no compose mas é “Phase B” (opt-in por fonte); fluxo principal é Hangfire.
- **Gabi.Sync** e **Gabi.Jobs** estão na solution e nos architecture tests; **Api e Worker não referenciam** esses projetos nos csproj. Executores e “job runner” vivem em `Gabi.Worker` e `Gabi.Contracts`; Sync/Jobs podem conter tipos compartilhados ou lógica legada.
- **DLQ** (Dead Letter Queue): recuperação manual via `POST /api/v1/dlq/{id}/replay`; sem requeue infinito automático.
- **Embeddings:** 384 dimensões; provider configurável (auto | onnx | tei | hash).

---

## 6. Incógnitas / A Verificar

- **Uso real de Gabi.Sync e Gabi.Jobs** em runtime: quem consome esses assemblies (se alguém) e se há plano de remoção ou consolidação.
- **Temporal:** em que condições uma fonte usa Temporal em vez de Hangfire e como o roteamento é feito (`HangfireJobQueueRepository` mencionado para “per-source routing”).
- **Redis:** além do health check, se existe ou está planejado cache/rate-limit na API usando Redis.
- **Projeção WAL:** detalhe do fluxo (LogicalReplicationProjectionWorker, ProjectionLagMonitor) e impacto em consistência de leitura.
- **Testcontainers:** falhas de timeout em Postgres/System/ReliabilityLab são tratadas como infra pré-existentes (não código).

---

## 7. Comandos Úteis (Referência)

```bash
dotnet build GabiSync.sln
dotnet test tests/Gabi.Architecture.Tests
dotnet test GabiSync.sln
./scripts/dev infra up
./scripts/dev db apply
dotnet run --project src/Gabi.Api --urls "http://localhost:5100"
./tests/zero-kelvin-test.sh docker-only
```

Documentação adicional: `CLAUDE.md`, `AGENTS.md`, `docs/architecture/LAYERED_ARCHITECTURE.md`, `HANDOVER.md`.
