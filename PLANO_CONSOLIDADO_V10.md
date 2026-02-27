# Plano Consolidado v10 (Fonte Única de Execução)

Data base: 26 de fevereiro de 2026 | Última revisão: 27/02/2026
Status: ativo
Escopo: substitui V9; consolida GEMINI findings, HANDOVER 25/02, kimi_plan, e code review forense.
Revisão 27/02: adiciona Reliability Migration (Fases A/B/C) + runtime validation plan.

---

## 1. Objetivo do v10

1. Fechar os gaps P0 identificados pelos findings do Gemini (4 riscos estruturais críticos).
2. Completar Ingest v2 (queue concurrency, bulk ES, circuit breaker).
3. Corrigir infraestrutura de testes (Zero Kelvin Worker, data isolation).
4. Preservar arquitetura em camadas e budget de memória (300MB efetivo no Worker).

Regras do plano:
1. Toda decisão precisa de evidência de código, teste ou execução.
2. Itens em um único estado: `feito`, `em_andamento`, `pendente`, `descartado`.
3. Todo item novo entra neste documento, não em arquivos paralelos.

---

## 2. Document Governance

Documentos canônicos ativos:
1. `PLANO_CONSOLIDADO_V10.md` (execução e priorização).
2. `AGENTS.md` (regras operacionais de engenharia/arquitetura).

Arquivados em `grounding_docs/archive/` (conteúdo absorvido no V10):
- `PLANO_CONSOLIDADO_V9.md`
- `GEMINI_FINDING.md`, `gemini_findings.md`, `GEMINI.md`
- `kimi_plan.md`
- `PLAN_EMBED_INDEX_ARCHITECTURE.md`
- `PLAN_PIPELINE_STATE_BACKPRESSURE.md`
- `HANDOVER_2026-02-25.md`

Referência técnica detalhada: `docs/plans/PLAN_ENTERPRISE_ROADMAP.md` (não é o documento de execução).

Visão futura (`image.png` — multi-agent, Qdrant, Neo4j, RAG): documentar em `docs/architecture/VISION_FUTURE.md`; não implementar antes de P0+P1 estáveis.

---

## 3. Snapshot Atual (factual, 26/02/2026)

### 3.1 Pipeline

| Etapa | Estado | Evidência principal |
|---|---|---|
| Seed | feito | `CatalogSeedJobExecutor` + endpoints de dashboard |
| Discovery | feito | adapters `static_url`, `url_pattern`, `web_crawl`, `api_pagination`; strict coverage endurecido (HANDOVER 25/02) |
| Fetch | feito | `FetchJobExecutor` streaming, cap, release explícito |
| Ingest v1 (normalização + projeção de mídia) | feito | `IngestJobExecutor` normaliza + projeta mídia + fan-out |
| Ingest v2 (chunk/embed/index via TEI + ES) | feito | `EmbedAndIndexJobExecutor` (390 linhas); `ElasticsearchDocumentIndexer` com bulk API + circuit breaker |
| Hybrid search (BM25 + kNN + RRF) | feito | `SearchService.cs`; BM25 multi-field (`title^3 + contentPreview^2`); fallback O(N) removido de produção (503 guard) |
| State machine (pause/resume/stop) | em_andamento | Endpoints existem (`Program.cs`); `SourcePipelineStateEntity` não escrita no lifecycle dos jobs |
| Reliability Migration — Fase A (Observability) | feito | Migrations `AddPerSourceFeatureFlags`, `AddWorkflowTrackingTables`, `EnableDocumentsReplicaIdentity`; entidades `WorkflowEventEntity`, `ProjectionDlqEntity`, `ProjectionCheckpointEntity`; `WorkflowEventRepository`; `JobTerminalStatus.Skipped`; replay guard 5min no `CatalogSeedJobExecutor` |
| Reliability Migration — Fase B (Temporal) | feito — kill-switch off | `temporalio/auto-setup:1.24.2` em docker-compose; `Temporalio 1.11.1`; `PipelineWorkflow`, `PipelineActivities`, `TemporalHealthCheck`, `TemporalWorkflowOrchestrator`, `TemporalWorkerHostedService`; dispatch AND-gated em `HangfireJobQueueRepository` (`EnableTemporalWorker=false` por default) |
| Reliability Migration — Fase C (WAL Projection) | feito — kill-switch off | WAL flags no docker-compose (`wal_level=logical`); `WalProjectionBootstrapService`, `LogicalReplicationProjectionWorker`, `ProjectionLagMonitor`; `DriftAuditorJobExecutor` (hourly); ES external versioning (`version_type=external`); `IndexingStatus.VersionConflict`; `POST /api/v1/admin/sources/{id}/repair-projection` (`EnableWalProjection=false` por default) |
| Runtime validation (Steps 1–7) | pendente | Infra up + migrations + integration suites; Temporal drill; WAL projection drill; failure drills; drift guard; batch rollout — ver §6.3 |

### 3.2 Infraestrutura de testes

| Componente | Estado | Observação |
|---|---|---|
| `Gabi.Architecture.Tests` | feito | NetArchTest validando camadas |
| `Gabi.Ingest.Tests` | em_andamento | NormalizerTests, ChunkerTests, TeiEmbedderTests, ESMetadataTests; falta cobertura de `EmbedAndIndexJobExecutor` |
| `EnvironmentManager` (Testcontainers) | feito | PostgreSQL 15 + Redis 7 + ES 8.11; data isolation por Guid por classe de teste corrigida |
| Zero Kelvin (system tests) | feito | Worker integrado em-processo via Hangfire; `Pipeline_ShouldRemainStable(100)` e `(1000)` passando |
| ReliabilityLab | pendente | Spec em `grounding_docs/archive/kimi_plan.md` (8 projetos, 9 camadas); não implementado |

---

### 3.3 Audit Findings — Reliability Migration (27/02/2026)

| Finding | Real? | Estado |
|---|---|---|
| Gabi.Sync/Jobs → Gabi.Postgres layer violation | Não — apenas Contracts referenciado | ✅ Limpo |
| Architecture test usa `InCurrentDomain` (fraco) | Não — carrega assemblies em runtime; 3 regras corretas | ✅ Limpo |
| `catch {}` silencioso no dashboard | Não — apenas `OperationCanceledException` em shutdown gracioso | ✅ Limpo |
| Sync-over-async em DlqFilter | Não defect — `IElectStateFilter.OnStateElection` é API síncrona do Hangfire | ✅ Aceitável |
| `Channel.CreateUnbounded` em GabiJobRunner | Não defect — scoped por job, `SingleReader=true`, fechado no fim | ✅ Seguro |
| Fallback users com senhas conhecidas | Não defect — guard `IsDevelopment()`, BCrypt-hashed, warning logado | ✅ Só dev |
| Retry logic mismatch (Hangfire vs Sync) | Não conflito — Hangfire usa DlqFilter; Sync usa RetryPolicy internamente | ✅ Consistente |
| N+1 em `PostgreSqlSourceCatalogService` | **Real** — `ListSourcesAsync` e `GetSystemStatsAsync` | ✅ **CORRIGIDO** (`GetBySourcesAsync` + single query) |
| Beta package `OpenTelemetry.Instrumentation.EntityFrameworkCore 1.11.0-beta.1` | Real — sem stable release upstream ainda | ⚠️ Monitorar |
| Credenciais dev em docker-compose.yml | Esperado para dev — não é preocupação de produção | 📝 Documentado |
| `System.Text.RegularExpressions 4.3.0` NU1903 (transitivo do Dapper) | Real | ✅ **CORRIGIDO** (override 4.3.1 em 6 projetos) |

---

## 4. O que mudou desde V9

| Entrega | Evidência |
|---|---|
| Strict coverage source-driven (CODEX-D) | YAML→DB→Dashboard; discovery/fetch respeitam flag por source |
| `EmbedAndIndexJobExecutor` implementado | `src/Gabi.Worker/Jobs/EmbedAndIndexJobExecutor.cs` (390 linhas) — era "em_andamento" no V9 |
| `Gabi.Ingest.Tests` criado | 4 classes de teste — V9 auditoria marcava como "NÃO RESOLVIDO" |
| Endpoints de state machine | `POST /api/v1/dashboard/sources/{id}/pause|resume|stop` |
| `EnvironmentManager` com Testcontainers | `tests/System/Gabi.ZeroKelvinHarness/Infrastructure/EnvironmentManager.cs` |
| Hybrid search BM25+kNN+RRF | `SearchService.cs` — fecha DEF-02/03 parcialmente |
| 8 novos riscos identificados (Gemini) | GEMINI-01 a GEMINI-08 — ver §5.3 |
| **Reliability Migration Fase A** | Migrations + entidades + `WorkflowEventRepository` + replay guard + `JobTerminalStatus.Skipped` |
| **Reliability Migration Fase B** | Temporal docker-compose + `Temporalio 1.11.1` + workflow/activities/hosted service + dispatch AND-gated |
| **Reliability Migration Fase C** | WAL logical replication + drift auditor + ES external versioning + `VersionConflict` status + repair endpoint |
| **NuGet NU1903 fix** | `System.Text.RegularExpressions 4.3.1` override em 6 projetos (3 prod + 3 test) |
| **N+1 fix** | `IDiscoveredLinkRepository.GetBySourcesAsync` + refactor de `ListSourcesAsync` e `GetSystemStatsAsync` |

---

## 5. Inventário Consolidado de Status (DEF + GEMINI)

### 5.1 `feito`

1. `DEF-05`, `DEF-06`, `DEF-07`, `DEF-08`, `DEF-13`, `DEF-15`, `DEF-18` — ver V9 §5.1.
2. **CODEX-B** (Status Semantic Closure): `JobTerminalStatus`; status semânticos; zero-kelvin rejeita `partial` como FAIL.
3. **CODEX-D** (strict coverage source-driven): YAML→DB→Dashboard; discovery/fetch respeitam flag.
4. State machine endpoints (pause/resume/stop): `POST /api/v1/dashboard/sources/{id}/pause|resume|stop`.
5. Hybrid search: `SearchService.cs` — BM25 + kNN + RRF.
6. `EmbedAndIndexJobExecutor`: implementado com batch 64, pause hooks, backpressure.
7. `TeiEmbedder` com circuit breaker: 5 falhas → open 30s; sub-batch 32.
8. **GEMINI-01**: `Gabi:Search:RequireElasticsearch=true` em produção; fallback → 503 implementado.
9. **GEMINI-03**: Tarpitting mitigado separando HangfireServer em dois pools (`pipeline-stages` / `embed-pool`).
10. **DEF-02/03**: Busca implementada com BM25 multi-field (`title^3 + contentPreview^2`) e fallback O(N) removido de produção.
11. **GEMINI-04**: OOM poison pill prevenido. Guard de tamanho no `JobPayloadParser` (5 MB).
11. **GEMINI-04**: OOM poison pill prevenido. Guard de tamanho no `JobPayloadParser` e `JobQueueRepository`.
11. **GEMINI-04**: Payload size guard — `JobPayloadParser.cs` (5 MB) + `JobQueueRepository.cs` (256 KB enqueue + deserialize).
12. **DEF-01**: `ElasticsearchDocumentIndexer` com `BulkAsync` (`_bulk` API) + circuit breaker (5 falhas → open 30s).
13. **DEF-19 / DEF-10**: Guard `GABI_EMBEDDINGS_URL` em `Gabi.Api/Program.cs` em não-Development.
14. **GEMINI-05**: Debounce no `PumpProgressUpdatesAsync` — 1s throttle + drain do canal para write mais recente.
15. **GEMINI-07**: Fallback Latin1 removido de `FetchJobExecutor`; encoding inválido rejeita para DLQ.
16. **CODEX-D defaults**: Merge de `defaults.pipeline` no Seed implementado em `CatalogSeedJobExecutor`.
17. **DB-ISO**: Data isolation em `Gabi.Postgres.Tests` corrigida (Guid por classe de teste).
18. **ZK-FIX**: Worker integrado nos system tests; `Pipeline_ShouldRemainStable` passa (100 e 1000 docs).
19. **GEMINI-08**: Cursor persistido no discovery — checkpoint em `source_registry.PipelineConfig` (JSONB `discovery_checkpoint`); adapters BTCU, Câmara, Senado, DOU lêem cursor via `DiscoveryConfig.Extra` no restart.
20. **DEF-14**: `IDocumentRepository` injetado em `IngestJobExecutor`; `_context.Documents.Add(doc)` substituído por `await _docRepository.AddAsync(doc, ct)`; registrado em Worker DI e ZeroKelvin factory.
21. **DEF-16/17**: `gabi.stage.errors` counter em `PipelineTelemetry`; endpoint `GET /api/v1/dashboard/sources/{id}/metrics` retorna `docs.{completed,pending,failed,success_rate}` + `jobs.{succeeded,failed,processing,pending,error_rate}` consultado do DB.
22. **RELY-A (Observability)**: Migrations `AddPerSourceFeatureFlags`, `AddWorkflowTrackingTables`, `EnableDocumentsReplicaIdentity`; entidades `WorkflowEventEntity`, `ProjectionDlqEntity`, `ProjectionCheckpointEntity`; `WorkflowEventRepository`; `JobTerminalStatus.Skipped`; replay guard 5min em `CatalogSeedJobExecutor`; colunas `UseTemporalOrchestration` e `UseWalProjection` em `SourceRegistryEntity`.
23. **RELY-B (Temporal)**: `temporalio/auto-setup:1.24.2` em docker-compose (ports 7233/8233); `Temporalio 1.11.1` em `Gabi.Worker.csproj`; `PipelineWorkflow`, `PipelineActivities`, `TemporalHealthCheck`, `TemporalWorkflowOrchestrator`, `TemporalWorkerHostedService`; dispatch AND-gated em `HangfireJobQueueRepository` (kill-switch global `EnableTemporalWorker=false` + per-source + reachability check).
24. **RELY-C (WAL Projection)**: WAL flags em docker-compose (`wal_level=logical`, `max_replication_slots=5`); `WalProjectionBootstrapService`, `LogicalReplicationProjectionWorker`, `ProjectionLagMonitor`, `DriftAuditorJobExecutor` (hourly `drift-audit`); `EmbedAndIndexJobExecutor` WAL path (`pending_projection`); ES `version_type=external` com `UpdatedAt.Ticks`; `IndexingStatus.VersionConflict`; `POST /api/v1/admin/sources/{id}/repair-projection` (RequireAdmin); kill-switch global `EnableWalProjection=false`.
25. **RELY-FIX-0 (NuGet NU1903)**: `System.Text.RegularExpressions 4.3.1` override em 6 projetos (`Gabi.Postgres`, `Gabi.Worker`, `Gabi.Api`, `Gabi.Fetch.Tests`, `Gabi.Ingest.Tests`, `Gabi.Discover.Tests`) — elimina NU1903 alto-risco do Dapper transitivo. Build: 0 erros.
26. **RELY-FIX-0b (N+1 query)**: `IDiscoveredLinkRepository.GetBySourcesAsync(IReadOnlyList<string>, ct)` adicionada à interface e implementada com `WHERE source_id IN (...)` (single round-trip); `ListSourcesAsync` e `GetSystemStatsAsync` em `PostgreSqlSourceCatalogService` refatoradas para usar a nova query com `GroupBy` em memória. `Gabi.Api.Tests` 31/31 ✅.

### 5.2 `em_andamento` / `parcial`

1. **DEF-11**, **DEF-12**: progresso parcial.
2. **State machine lifecycle**: endpoints pause/resume/stop existem; `SourcePipelineStateEntity` ainda não é escrita nos lifecycle hooks dos jobs.

### 5.3 `pendente` — novos (GEMINI findings, 26/02/2026)

| ID | Risco | Prioridade | Detalhe e localização |
|---|---|---|---|
| **GEMINI-02** | SSRF incompleto | P1 | DNS resolution faltante: hostname pode resolver para IP privado pós-allowlist. `FetchUrlValidator.cs`. |
| **GEMINI-06** | Mean pooling dilui embeddings | P2 | Média dos vetores de chunk dilui semântica irreversivelmente. Solução: `nested` queries no ES por chunk, não média. `ElasticsearchDocumentIndexer.cs`. |
| **GEMINI-08** | Sisyphean discovery freeze | P1 | Sem cursor persistido. Crash reinicia discovery do zero. Checkpoint em `source_registry`. `SourceDiscoveryJobExecutor.cs`. |

### 5.4 `pendente` — Runtime Validation (Reliability Migration, 27/02/2026)

Implementação concluída (Fases A/B/C); kill-switches `false` em produção. Todos os passos abaixo requerem infra em execução.

| Step | O que validar | Gate de saída |
|---|---|---|
| **1 — Migrations + Integration Suites** | `./scripts/dev infra up && ./scripts/dev db apply`; confirmar `wal_level=logical`; rodar `Gabi.Postgres.Tests` (74/74), `Gabi.System.Tests` (3/3), `ReliabilityLab.Tests` (2/2) | 0 falhas em todos os suites |
| **2 — Temporal drill (tcu_sumulas)** | Setar `use_temporal_orchestration=TRUE` para `tcu_sumulas` via SQL + `EnableTemporalWorker=true` em `appsettings.Development.json`; acionar fase discovery; confirmar workflow na UI `localhost:8233`; kill + restart → workflow resume; 0 duplicatas | Workflow visível em UI; nenhuma linha duplicada após crash |
| **3 — WAL projection drill (tcu_sumulas)** | Setar `use_wal_projection=TRUE` + `EnableWalProjection=true`; confirmar slot `gabi_projection` e pub `gabi_docs_pub`; ingest → `pending_projection` → `completed`; stale-write test (409 → `stale_write_ignored`); kill ES 30s → restart → convergência | Checkpoint avança; DLQ=0; `drift_ratio → 0` após restart do ES |
| **4 — Failure drills** | (4a) Kill worker mid-activity → restart → nenhum doc stuck em `processing`; (4b) crash pós-DB commit → WAL replay drena `pending_projection`; (4c) embedder lento → retry com backoff, nenhuma falha permanente; (4d) 0 duplicatas terminais | Todos drills passam; nenhum estado preso |
| **5 — Drift guard** | Forçar `projection_checkpoint.lsn='0/1'` → drift audit deve diferir (status `Inconclusive`, reason `projection_catching_up`); reset lsn → audit enfileira repair jobs se drift > 1% | Deferral confirmado com lag alto; repair confirmado com lag normal |
| **6 — Batch rollout** | Habilitar `use_wal_projection=TRUE` para primeiros 3 sources; 24h de monitoring; expandir para todos; rollback instantâneo disponível via `UPDATE source_registry SET use_wal_projection=FALSE` | `drift_ratio → 0`; DLQ=0; lag < 50 MB; kill-switches permanecem `false` no código commitado |
| **7 — OpenTelemetry beta** | `OpenTelemetry.Instrumentation.EntityFrameworkCore 1.11.0-beta.1` — sem release stable ainda; rastrear no NuGet; atualizar ambos csproj quando stable disponível | Nenhuma ação imediata; upgrade quando `1.11.0` stable lançado |

### 5.5 `pendente` — herdado de V9

| Item | Prioridade V10 |
|---|---|
| DEF-04 (rate limiting/distribuição) | P1 |
| DEF-09 | P2 |
| DEF-14 (repositório dedicado para escrita de documentos) | P1 |
| DEF-16 (observabilidade com métricas acionáveis) | P1 |
| DEF-17 (resiliência adicional) | P1 |

---

## 6. Backlog Único Priorizado (v10)

### P0 — Bloqueante de produção

**Todos os itens P0 foram fechados.** Evidência: code review + Zero Kelvin system tests passando.

| # | Item | Estado |
|---|---|---|
| 1 | **GEMINI-03**: Dois `AddHangfireServer` (`pipeline-stages` / `embed-pool`) | ✅ feito |
| 2 | **GEMINI-01**: `RequireElasticsearch=true` + 503 guard | ✅ feito |
| 3 | **GEMINI-04**: Payload size guard (5 MB parser, 256 KB enqueue) | ✅ feito |
| 4 | **DEF-01**: ES `BulkAsync` + circuit breaker no `ElasticsearchDocumentIndexer` | ✅ feito |
| 5 | **DEF-19**: Guard `GABI_EMBEDDINGS_URL` em `Gabi.Api/Program.cs` não-Development | ✅ feito |

### P1 — Robustez operacional

Aceite P1: sem falhas silenciosas em progress/retry; testes de falha cobrindo casos críticos.

| # | Item | Estado | Arquivo principal |
|---|---|---|---|
| 6 | **ZK-FIX**: Worker integrado nos system tests | ✅ feito | `tests/System/Gabi.System.Tests/` |
| 7 | **GEMINI-05**: Debounce progress pump (1s throttle + drain) | ✅ feito | `src/Gabi.Worker/Jobs/GabiJobRunner.cs` |
| 8 | **GEMINI-07**: Fallback Latin1 removido; DLQ em encoding inválido | ✅ feito | `src/Gabi.Worker/Jobs/FetchJobExecutor.cs` |
| 9 | **CODEX-D defaults**: Merge `defaults.pipeline` no Seed | ✅ feito | `src/Gabi.Worker/Jobs/CatalogSeedJobExecutor.cs` |
| 10 | **DB-ISO**: Data isolation em `Gabi.Postgres.Tests` | ✅ feito | `tests/Gabi.Postgres.Tests/` |
| 11 | **GEMINI-08**: Cursor persistido no discovery | ✅ feito | `src/Gabi.Worker/Jobs/SourceDiscoveryJobExecutor.cs`, `src/Gabi.Discover/ApiPaginationDiscoveryAdapter.cs` |
| 12 | **GEMINI-02**: DNS resolution guard em `FetchUrlValidator` | ✅ feito | `src/Gabi.Worker/Security/FetchUrlValidator.cs` |
| 13 | **DEF-04**: Rate limiting/distribuição | ✅ feito | `src/Gabi.Api/Program.cs` (`AddRateLimitingConfig`/`UseRateLimiter`) |
| 14 | **DEF-14**: Repositório dedicado para escrita de documentos | ✅ feito | `src/Gabi.Worker/Jobs/IngestJobExecutor.cs` — `IDocumentRepository` injetado; `AddAsync` via repo |
| 15 | **DEF-16/17**: Métricas por source/stage (`success_rate`, `error_rate`) | ✅ feito | `gabi.stage.errors` counter em `PipelineTelemetry`; `GET /api/v1/dashboard/sources/{id}/metrics` |

### P1.5 — Runtime Validation (Reliability Migration) — bloqueante para habilitar em produção

| # | Step | Estado |
|---|---|---|
| RV-1 | Migrations aplicadas + integration suites verdes (74+3+2) | pendente — requer infra |
| RV-2 | Temporal drill em `tcu_sumulas` | pendente — requer infra + `EnableTemporalWorker` dev-only |
| RV-3 | WAL projection drill em `tcu_sumulas` | pendente — requer infra + `EnableWalProjection` dev-only |
| RV-4 | Failure drills (4a–4d) | pendente — requer infra |
| RV-5 | Drift guard behavior | pendente — requer infra |
| RV-6 | Batch rollout (3 sources → todos) | pendente — pós RV-1..5 |
| RV-7 | OpenTelemetry beta → upgrade quando stable | monitorar |

### P2 — Excelência e expansão

1. **ReliabilityLab**: implementar spec de `grounding_docs/archive/kimi_plan.md` (8 projetos, 9 camadas). `tests/ReliabilityLab/`.
2. **GEMINI-06**: chunk-level search no ES (nested queries) em vez de mean pooling.
3. NuGet audit + `TreatWarningsAsErrors` em `Directory.Build.props`.
4. Migrations com `CREATE INDEX CONCURRENTLY`.
5. Redis `requirepass` + ES `xpack.security.enabled=true` em `docker-compose.yml`.
6. Typed payloads (substituir `Dictionary<string,object>` em `IngestJob.Payload`). `src/Gabi.Contracts/Jobs/IngestJob.cs`.
7. `IdempotencyKey` wired em `JobQueueRepository` (deduplicação real de enqueue).
8. Property-based testing (FsCheck) para chunker/fingerprint/idempotência.
9. Cross-source deduplication via fingerprint. `src/Gabi.Postgres/Repositories/DocumentRepository.cs`.
10. Audit log com hash chain (append-only + `REVOKE UPDATE DELETE`).
11. BGE-M3 (1024-dim) — SÓ quando recall gap medido; não fazer preemptivamente.
12. Arquitetura aspiracional (multi-agent, Qdrant, Neo4j, RAG/MCP) — não iniciar antes de P0+P1 estáveis.

---

## 7. Itens Descartados / Despriorizado

1. GPU/SIMD acceleration — `NÃO VIÁVEL` no código atual (IO-bound); revisitar somente se throughput > 100 docs/s.
2. Múltiplos planos paralelos ativos — descartado; V10 é a única fonte.
3. Tratar ingest atual como noop total — descartado.

---

## 8. Sequência de Execução Recomendada

```
✅ CONCLUÍDO — P0 (todos fechados) e P1 (todos os 15 itens fechados)

✅ IMPLEMENTADO — Reliability Migration Fases A/B/C
  Código commitado; kill-switches false por default; código buildando limpo (0 erros).

🔲 BLOQUEANTE para habilitar Reliability Migration em produção — P1.5 Runtime Validation
  RV-1: ./scripts/dev infra up && ./scripts/dev db apply → integration suites (74+3+2)
  RV-2: Temporal drill em tcu_sumulas (workflow UI, crash-recovery, 0 duplicatas)
  RV-3: WAL projection drill em tcu_sumulas (checkpoint avança, ES converge, DLQ=0)
  RV-4: Failure drills 4a–4d
  RV-5: Drift guard behavior
  RV-6: Batch rollout (3 sources → todos)
  RV-7: Monitorar OpenTelemetry.Instrumentation.EntityFrameworkCore stable release

Próximo após RV completo — P2
  ReliabilityLab, typed payloads, NuGet audit, CONCURRENTLY migrations, chunk-level search
```

---

## 9. Auditoria Técnica — Delta V9→V10 (atualizado 26/02/2026)

| Item | V9 | V10 |
|---|---|---|
| `Gabi.Ingest.Tests` existente | NÃO RESOLVIDO | **RESOLVIDO** |
| Circuit breaker nas integrações | NÃO RESOLVIDO | **RESOLVIDO** (`TeiEmbedder` + `ElasticsearchDocumentIndexer`) |
| Testcontainers com PostgreSQL real | NÃO RESOLVIDO | **RESOLVIDO** (`EnvironmentManager` + data isolation por Guid) |
| Zero Kelvin Worker integrado | NÃO RESOLVIDO | **RESOLVIDO** (`Pipeline_ShouldRemainStable` passa 100+1000) |
| ES bulk indexing | NÃO RESOLVIDO | **RESOLVIDO** (`BulkAsync` com `_bulk` API) |
| Payload size guard (GEMINI-04) | NÃO RESOLVIDO | **RESOLVIDO** (5 MB parser + 256 KB enqueue) |
| Progress write-amplification (GEMINI-05) | NÃO RESOLVIDO | **RESOLVIDO** (1s throttle + canal drain) |
| Fallback Latin1 (GEMINI-07) | NÃO RESOLVIDO | **RESOLVIDO** (removido; DLQ em encoding inválido) |
| CODEX-D defaults.pipeline no Seed | PARCIAL | **RESOLVIDO** |
| State machine lifecycle (entity) | (sem item) | **PARCIAL** (endpoints OK; SourcePipelineStateEntity não escrita) |

| **RELY-A Observability** | (sem item) | **RESOLVIDO** (migrations + entidades + replay guard + `JobTerminalStatus.Skipped`) |
| **RELY-B Temporal** | (sem item) | **RESOLVIDO** — código; kill-switch `false`; runtime validation pendente |
| **RELY-C WAL Projection** | (sem item) | **RESOLVIDO** — código; kill-switch `false`; runtime validation pendente |
| **NuGet NU1903 (`System.Text.RegularExpressions`)** | (sem item) | **RESOLVIDO** (override 4.3.1 em 6 projetos) |
| **N+1 em `PostgreSqlSourceCatalogService`** | (sem item) | **RESOLVIDO** (`GetBySourcesAsync` + single query) |

Items que permanecem NÃO RESOLVIDO:
- P1.5: Runtime validation RV-1..7 (requer infra + execução manual dos drills)
- P2: `Result<T>`, `Dictionary<string,object>` em payloads, `IdempotencyKey` não wired, Redis/ES auth, NuGet audit completo, `TreatWarningsAsErrors`, migrations CONCURRENTLY, build determinístico, deploy blue/green, backups testados, `OpenTelemetry.Instrumentation.EntityFrameworkCore` stable.

---

## 10. Governança de Execução do Plano

1. Este arquivo é a única fonte de planejamento operacional corrente.
2. Qualquer atualização deve alterar: Snapshot Atual, Inventário DEF, Backlog Único.
3. Evidência mínima para mover item a `feito`: diff de código + teste automatizado ou execução comprovada.
