# Plano Consolidado v10 (Fonte Única de Execução)

Data base: 26 de fevereiro de 2026 | Última revisão: 27/02/2026 (sessão 9)
Status: ativo
Escopo: substitui V9; consolida GEMINI findings, HANDOVER 25/02, kimi_plan, e code review forense.
Revisão 27/02: adiciona Reliability Migration (Fases A/B/C) + runtime validation plan.
Revisão 27/02 (s2): processa relatório Gemini forense (R-01..R-09, GEM-01..GEM-08); adiciona EH-07 (scope leak WAL linha 212); registra FALSE CLAIM de R-07 (contagem CreateScope 4 vs real ~50); corrige §5.3 (GEMINI-02 e GEMINI-08 eram duplicatas pendentes de itens feitos); atualiza IO-07 para >40 literais.
Revisão 27/02 (s3): auditoria forense §4/§5/§6/§7 (Concurrency, I/O, EH, Security); 6 FALSE CLAIMs registrados (Task.Run:34, GetAwaiter, StopSourceAsync→idle, Gabi.Sync→Postgres, DlqFilter deadlock, fallback users); EH-02 expandido para 5 locais (inclui SourceDiscoveryJobExecutor:448 checkpoint reset e PipelineStatsService:144 stats silencing); §7.5 e §7.6/7.7 classificados como NOT PROVABLE.
Revisão 27/02 (s8): auditoria forense §17 (ML Assessment + Edge Technologies); 3 FALSE CLAIMs adicionados (IntentGuardrails em DashboardService.cs — arquivo errado; "Temporal não considerado" — já RELY-B; "CDC não considerado" — já RELY-C); 1 claim verificada correta (ErrorTaxonomy/IntelligentRetryPlanner para categorização de retry — DlqFilter linha 42 chama ErrorClassifier.Classify). Nenhum item novo no backlog.
Revisão 27/02 (s9): auditoria forense "Lost WAL DLQ Events" (input issue — EH-03/04/07); EH-07 marcado FIXED (`using var scope` presente em `IndexDocumentWithVersionAsync:217`); EH-03 PARTIALLY FIXED (contador + crash-após-5 implementado, mas falhas não-consecutivas individuais ainda perdem o documento permanentemente — sem Polly/per-event retry); EH-04 PARTIALLY FIXED (contador + rethrow-após-3 implementado; edge case estreito de slot-advance sem checkpoint-save nas 2 primeiras falhas).
Revisão 27/02 (s4): auditoria forense §8/§9/§10/§11 (Performance, Deployment, Testing, Dependencies); adicionados IO-10 (N+1 migrado para PipelineStatsService), IO-11 (guardrail 5000 + N+1), IO-12 (N+1 docCount normal path), IO-13 (coming_soon estático para fases implementadas), ARCH-01 (architecture test vacuoso); 2 FALSE CLAIMs: N+1 em DashboardService:1053 (linha não existe), N+1 em PostgreSqlSourceCatalogService:83 (FIXED via GetBySourcesAsync); O(N) search PARTIALLY FIXED; Channel.CreateUnbounded PARTIALLY FIXED.
Revisão 27/02 (s5): auditoria forense §12/§13/§14 (Technical Debt, Scalability, Refactor Roadmap); 2 FALSE CLAIMs adicionados (Phase0Orchestrator tipos infra, Gabi.Sync/Jobs violação de camada via .csproj — já registrado mas agora com evidência de .cs também); adicionado SYNC-01 (código morto: JobQueueRepository Dapper e JobWorkerService em Gabi.Sync nunca registrados; JobQueueRepository [Obsolete] em Gabi.Postgres nunca registrado); WorkerCount=1 confirmado como design intencional (anti-tarpitting); Postgres SPOF confirmado como concern de infra de produção, não bug de código.
Revisão 27/02 (s7): auditoria forense §16 (Stability/Scalability); 3 itens novos: SCAL-01 (sem global admission cap — somente per-source), SCAL-02 (ScheduleAsync sem lock — dedup indireto via job_registry; gap estreito mas real), SCAL-03 (single pipeline worker = monopolização de fonte); 2 FALSOs ausentes: ES CB fast-fail FIXED, maxPages=500 FIXED; IO-14 reconfirmado.
Revisão 27/02 (s6): auditoria forense §15 (Pipeline Correctness Verdict); 4 FALSE CLAIMs adicionados (stop→idle, fire-and-forget construtor, DlqFilter deadlock, ApiPaginationDiscoveryAdapter:494 — todos já registrados em s3 mas re-confirmados); 3 itens novos: IO-14 (JsonDocument.ParseAsync sem cap em FetchAndParseJsonApiAsync), IO-15 (GenericPaginatedDiscoveryDriver yield break silencioso), EH-08 (embed_and_index double-processing sem single-in-flight guard); crash window (PARTIALLY FIXED via retry idempotente); duplicate embed (PARTIALLY FIXED via xmin guard); PG→ES drift auto-repair (PARTIALLY FIXED — infrastructure existe mas kill-switch off).

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
| Gabi.Sync/Jobs → Gabi.Postgres layer violation | Não — apenas Contracts referenciado (verificado nos .csproj e ausência de `using Gabi.Postgres` nos .cs) | ✅ Limpo |
| Hard-coded OTLP localhost defaults | **Real** — `"http://localhost:4317"` em `Worker/Program.cs` e `Api/PipelineServiceExtensions.cs`; `"http://localhost:9200"` em `SystemHealthService`; `"localhost:7233"` em `TemporalHealthCheck` | ⚠️ Pendente (IO-01) |
| Hard-coded URLs de APIs externas | **Real** — `https://api.openai.com/v1/audio/transcriptions` direto em `MediaTranscribeJobExecutor`; endpoints Google APIs diretos em `YouTubeDiscoveryDriver` | 🔴 Pendente (IO-02) |
| Abstração inadequada em `PostgreSqlSourceCatalogService` | **Real** — uma classe implementa `IHostedService` + carrega YAML + persiste DB + mapeia DTOs (4 responsabilidades) | ⚠️ Pendente (IO-03) |
| Abstração inadequada em `SystemHealthService` | **Real** — cria `HttpClient` inline, swallows exceção sem log, default `localhost:9200` hardcoded, timeout de 5s hardcoded | ⚠️ Pendente (IO-04) |
| OpenAI transcription sem ACL (anti-corruption layer) | **Real** — `MediaTranscribeJobExecutor` faz HTTP diretamente para OpenAI sem interface em Contracts; `OPENAI_API_KEY` lido inline no executor | 🔴 Pendente (IO-05) |
| YouTube Discovery — ACL parcial | **Parcial** — chamado via `ApiPaginationDiscoveryAdapter` (existe abstração), mas métodos são `internal static`, URLs hardcoded, sem interface substituível em Contracts | ⚠️ Pendente (IO-06) |
| Redis port inconsistency (6379 vs 6380) | **Real** — `appsettings.Development.json` usa `redis://localhost:6379` mas docker-compose mapeia Redis em `6380` no host | ⚠️ Pendente (IO-07) |
| Architecture test usa `InCurrentDomain` (fraco) | Não — carrega assemblies em runtime; 3 regras corretas | ✅ Limpo |
| `catch {}` silencioso no dashboard | Não — apenas `OperationCanceledException` em shutdown gracioso (`JobWorkerHostedService`, `JobWorker`) | ✅ Limpo |
| Sync-over-async em DlqFilter (`SaveChanges` em vez de `SaveChangesAsync`) | Verificado: `IElectStateFilter.OnStateElection` é API síncrona do Hangfire; comentário no código documenta explicitamente; write pontual por falha, não loop | ✅ Aceitável — código correto |
| `Channel.CreateUnbounded` em GabiJobRunner | Verificado: scoped por job, `SingleReader=true`, canal fechado com `TryComplete()` e awaited em `AwaitProgressPumpSafelyAsync` | ✅ Seguro |
| `Task.Run` fire-and-forget em `PostgreSqlSourceCatalogService.cs:34` (claim original) | **Falso** — arquivo errado citado. O único `Task.Run` relevante está em `GabiJobRunner.cs:97`; task é armazenada e awaited em linha 117 via `AwaitProgressPumpSafelyAsync` | ✅ Limpo — não existe fire-and-forget |
| `GlobalJobFilters` mutado no bootstrap do Worker | Verificado: linhas 228 e 232 de `Worker/Program.cs` removem `AutomaticRetryAttribute` e adicionam `DlqFilter` — mas ocorre **antes de `host.Run()`**, em bootstrap single-threaded, antes de qualquer worker thread iniciar | ✅ Seguro — ordem de inicialização correta |
| `GetAwaiter().GetResult()` em pipeline Hangfire | Verificado: **zero ocorrências** de `.GetAwaiter().GetResult()`, `.Result` ou `.Wait()` em todo `src/` | ✅ Limpo — não existe |
| Race condition: `StopSourceAsync` escreve `idle`; checks usam `paused`/`stopped` | **Falso** — `StopSourceAsync` escreve `Status.Stopped`; `IsSourcePausedOrStoppedAsync` checa `Status.Paused or Status.Stopped`; consistente em todos os writes (Pause→Paused, Resume→Running, Stop→Stopped) | ✅ Limpo — não existe race condition |
| Fallback users com senhas conhecidas | Não defect — guard `IsDevelopment()`, BCrypt-hashed, warning logado | ✅ Só dev |
| Retry logic mismatch (Hangfire vs Sync) | Não conflito — Hangfire usa DlqFilter; Sync usa RetryPolicy internamente | ✅ Consistente |
| Fail-open DI resolution em `GabiJobRunner` | **Real** — `catch { return null; }` sem log; `IWorkflowEventRepository` silenciosamente `null` | ⚠️ Pendente (EH-01) |
| Fail-open em parse de config de pipeline | **Real** — `catch { return new DiscoveryConfig(); }` em `PostgreSqlSourceCatalogService`; `catch { return null; }` em `SystemHealthService` | ⚠️ Pendente (EH-02) |
| Swallow em WAL projection — `WriteToDlqAsync` | **Parcialmente corrigido** — contador `_consecutiveDlqWriteFailures` implementado; worker para após 5 falhas consecutivas; MAS falhas não-consecutivas individuais ainda descartam o evento permanentemente (sem per-event retry / Polly) | 🟡 PARTIALLY FIXED (EH-03) |
| Swallow em WAL projection — `PersistCheckpointAsync` | **Parcialmente corrigido** — contador `_consecutiveCheckpointFailures` implementado; rethrow após 3 falhas consecutivas; edge case: nas 2 primeiras falhas `conn.SetReplicationStatus` ainda avança sem checkpoint salvo | 🟡 PARTIALLY FIXED (EH-04) |
| Falha de embedding invisível ao caller em `SearchService` | **Real** — exceção capturada, `queryVector=null`, fallback BM25-only silencioso; response idêntico ao caso de sucesso | ⚠️ Pendente (EH-05) |
| Contratos de erro inconsistentes na API | **Real** — 4 formatos distintos: `new { error }`, `ApiError`, `ErrorResponse` (middleware), objetos de domínio; clientes não conseguem parsear uniformemente | ⚠️ Pendente (EH-06) |
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
27. **EH-07** (WAL scope leak): `IndexDocumentWithVersionAsync` agora usa `using var scope = _services.CreateScope();` (linha 217) — scope corretamente disposed após cada evento WAL; rota quente do projection worker não vaza mais connections.

### 5.2 `em_andamento` / `parcial`

1. **DEF-11**, **DEF-12**: progresso parcial.
2. **State machine lifecycle**: endpoints pause/resume/stop existem; `SourcePipelineStateEntity` ainda não é escrita nos lifecycle hooks dos jobs.

### 5.3 `pendente` — novos (GEMINI findings, 26/02/2026)

| ID | Risco | Prioridade | Detalhe e localização |
|---|---|---|---|
| ~~**GEMINI-02**~~ | ~~SSRF incompleto~~ | — | ✅ feito — `FetchUrlValidator.cs` confirmado com DNS resolution guard |
| **GEMINI-06** | Mean pooling dilui embeddings | P2 | Média dos vetores de chunk dilui semântica irreversivelmente. Solução: `nested` queries no ES por chunk, não média. `ElasticsearchDocumentIndexer.cs`. |
| ~~**GEMINI-08**~~ | ~~Sisyphean discovery freeze~~ | — | ✅ feito — cursor persistido em `source_registry.PipelineConfig` (JSONB `discovery_checkpoint`) |

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

### 5.5 `pendente` — Error Handling Audit (27/02/2026)

Auditoria completa do código revelou 6 itens reais, não presentes anteriormente no plano.

| ID | Severidade | Arquivo | Problema | Fix |
|---|---|---|---|---|
| **EH-01** | 🟡 Médio | `GabiJobRunner.cs` | `catch { return null; }` na resolução de `IWorkflowEventRepository` — DI falha silenciosamente sem log; eventos de workflow desativados sem rastro | Mover para `GetRequiredService` com log de `Error` se falhar; ou pelo menos `LogError` antes de retornar null |
| **EH-02** | 🟡 Médio | `PostgreSqlSourceCatalogService.cs`, `SystemHealthService.cs`, `SourceDiscoveryJobExecutor.cs:448`, `PipelineStatsService.cs:144`, `SourceQueryService.cs:239` | `catch {}` / `catch { return ... }` sem logging em múltiplos pontos: parse de config, checkpoint JSON de discovery (falha silenciosa reseta discovery para página 1), stats do job queue (silencia falha de DB), metadata JSON de link — todos fail-open sem rastro | Adicionar `LogError` antes do fallback; casos críticos (checkpoint) devem propagar exceção |
| **EH-03** | 🟡 Médio (PARTIALLY FIXED) | `LogicalReplicationProjectionWorker.cs` — `WriteToDlqAsync` | Contador `_consecutiveDlqWriteFailures` implementado; worker para (throw) após 5 falhas consecutivas; log `Error` ao falhar. GAP REMANESCENTE: falhas não-consecutivas individuais ainda descartam o documento permanentemente — nenhum per-event retry ou Polly policy; LSN checkpoint avança independentemente; restart não replaya o doc perdido | Adicionar retry Polly por evento antes de contar falha; ou: não avançar LSN até que DLQ write confirme |
| **EH-04** | 🟡 Médio (PARTIALLY FIXED) | `LogicalReplicationProjectionWorker.cs` — `PersistCheckpointAsync` | Contador `_consecutiveCheckpointFailures` implementado; rethrow após 3 falhas consecutivas. GAP REMANESCENTE: nas 2 primeiras falhas (contador < 3) `conn.SetReplicationStatus` + `SendStatusUpdate` são chamados na sequência, avançando o slot Postgres sem checkpoint local salvo; restart posterior começa do LSN antigo mas o slot pode já ter avançado | Não chamar `conn.SetReplicationStatus` se `PersistCheckpointAsync` falhou |
| **EH-05** | 🟡 Médio | `SearchService.cs` | Falha de embedding capturada, `queryVector=null`, fallback BM25-only sem sinalização — response ao usuário idêntico ao caso de sucesso kNN | Adicionar campo `"embeddingFailed": true` no response DTO; ou retornar `Warning` header |
| **EH-06** | 🟡 Médio | `Program.cs` (API) | 4 formatos de erro distintos: `new { error = "..." }`, `ApiError(code, msg)`, `ErrorResponse` (middleware), objetos de domínio — clientes não conseguem parsear uniformemente | Unificar em `ApiError` em todos os `Results.BadRequest`/`Results.NotFound`; atualizar middleware para mesmo formato |
| ~~**EH-07**~~ | ~~🔴 Alto~~ | ~~`LogicalReplicationProjectionWorker.cs:212`~~ | ✅ **FEITO** — `IndexDocumentWithVersionAsync` usa `using var scope = _services.CreateScope();` (linha 217); scope corretamente disposed após cada evento WAL | — |

### 5.6 `pendente` — I/O & Boundary Discipline (27/02/2026)

| ID | Sev | Arquivo | Problema | Fix |
|---|---|---|---|---|
| **IO-01** | 🟡 | `Worker/Program.cs`, `Api/PipelineServiceExtensions.cs`, `TemporalHealthCheck.cs` | Defaults `localhost:4317` (OTLP) e `localhost:7233` (Temporal) em código — produção falha silenciosamente sem config explícita | Remover defaults; exigir config explícita; guard de startup como existe para `GABI_EMBEDDINGS_URL` |
| **IO-02** | 🟡 | `SystemHealthService.cs` | Default `"http://localhost:9200"` hardcoded + `HttpClient` criado inline + timeout 5s hardcoded | Mover URL para config; injetar `IHttpClientFactory`; timeout via named client |
| **IO-03** | 🔴 | `MediaTranscribeJobExecutor.cs` | HTTP direto para `https://api.openai.com/v1/audio/transcriptions` sem interface; `OPENAI_API_KEY` lido inline no executor — zero ACL | Criar `ITranscriptionService` em `Gabi.Contracts`; mover implementação OpenAI para `Gabi.Worker/Adapters/OpenAiTranscriptionService.cs`; injetar via DI |
| **IO-04** | 🟡 | `YouTubeDiscoveryDriver.cs` | URLs `googleapis.com` hardcoded; métodos `internal static` sem interface substituível | Mover URLs para config; expor via interface em Contracts (ou ao menos tornar testável via injeção) |
| **IO-05** | 🟡 | `PostgreSqlSourceCatalogService.cs` | Uma classe implementa `IHostedService` + YAML I/O + persistência DB + mapeamento DTOs | Extrair `ISourceYamlLoader` para carregamento de YAML; manter service como orchestrator puro |
| **IO-06** | 🟡 | `appsettings.Development.json` | `redis://localhost:6379` mas docker-compose mapeia Redis em host port `6380` — inconsistência silenciosa | Corrigir para `localhost:6380` no Development config |
| **IO-10** | 🔴 | `PipelineStatsService.cs` — `GetStatsAsync()` | N+1 migrado do DashboardService: `foreach (var s in sources) { await linkRepo.GetBySourceAsync(s.Id) }` — O(N) queries por chamada a `GET /api/v1/dashboard`. Rota quente, chamada por toda carga do dashboard. O fix com `GetBySourcesAsync` foi aplicado só a `PostgreSqlSourceCatalogService` | Usar `linkRepo.GetBySourcesAsync(sourceIds, ct)` + `GroupBy` em memória, idêntico ao fix aplicado em `PostgreSqlSourceCatalogService.GetSystemStatsAsync` |
| **IO-11** | 🔴 | `SourceQueryService.cs` — `GetLinksAsync()` guardrail path | Hardcoded 5000-row fetch (`pageSize=5000`) + N+1 por link (`GetDocumentCountAsync` por link no foreach) — até 5001 queries por chamada; filtragem in-memory por intent; filtragem incompleta se source tem >5000 links | Mover filtro intent para SQL (novo parâmetro de filtro no repositório); ou usar `GetDocumentCountBulkAsync(linkIds)` para batch counts |
| **IO-12** | 🟡 | `SourceQueryService.cs` — `GetLinksAsync()` path normal (não-guardrail) | N+1 por link paginado: `foreach (var link in paginated.Items) { await linkRepo.GetDocumentCountAsync(link.Id) }` — pageSize máximo 100 = até 101 queries por página | Adicionar `GetDocumentCountBulkAsync(IReadOnlyList<long> linkIds)` retornando `Dictionary<long,int>` |
| **IO-13** | 🟡 | `PipelineStatsService.cs`, `SourceQueryService.cs` | `Availability = "coming_soon"` hardcoded para 4 fases do pipeline (Ingest, Processing, Embedding, Indexing) que estão de fato implementadas e em execução no Worker | Remover strings "coming_soon" estáticas; calcular availability real consultando o estado de cada fase ou remover o campo se o frontend não usa mais |
| **IO-14** | 🟡 | `FetchJobExecutor.cs` — `FetchAndParseJsonApiAsync` | `JsonDocument.ParseAsync(stream)` sem byte cap — resposta JSON grande materializa unbounded em memória. Path link-only (linhas 682-705) tem dois guards (`Content-Length` check + `ReadAllBytesWithLimitAsync`); path JSON API não tem nenhum | Adicionar check de `Content-Length` + `ReadAllBytesWithLimitAsync` com limite configurável antes de `JsonDocument.ParseAsync`, idêntico ao path link-only |
| **IO-15** | 🟡 | `GenericPaginatedDiscoveryDriver.cs` | `yield break` silencioso em falha de página API (`resp == null || !resp.IsSuccessStatusCode`) — termina traversal sem registrar qual página falhou, sem cursor resumível para o driver genérico; pages restantes não são recuperadas automaticamente | Converter falha de página em exceção ou registrar `DiscoveryPageFailure` no DB; alternativamente, persistir cursor de página no checkpoint antes de `yield break` para permitir resumo |

### 5.7 `pendente` — Forensic Verification (27/02/2026)

Verificação forense linha a linha das claims do relatório de auditoria original. Regra: "FIXED" só quando o caminho de falha é impossível no código; incerteza → NOT PROVEN FIXED.

| Claim original | Verdict forense | Evidência de código | Item V10 |
|---|---|---|---|
| Gabi.Sync/Jobs → Gabi.Postgres (dependency matrix) | **FIXED** | .csproj lido: ambos referenciam apenas Gabi.Contracts; nenhum `using Gabi.Postgres` em .cs dos projetos | — nada a fazer |
| `StopSourceAsync` escreve `idle`; guards checam `paused/stopped` | **FIXED** | DashboardService.cs tem 587 linhas (linha 844 não existe); delegate para `SourceControlService` que escreve `Status.Stopped`; `IsSourcePausedOrStoppedAsync` checa `Paused or Stopped` | — nada a fazer |
| `Task.Run` fire-and-forget em `PostgreSqlSourceCatalogService.cs:34` | **FIXED** | Linha 34 é `_sourcesPath = ResolveSourcesPath(...)` (síncrona); constructor não tem `Task.Run`; `StartAsync` é `await InitializeAsync(ct)` | — nada a fazer |
| Hardcoded URL em `ApiPaginationDiscoveryAdapter.cs:494` | **PARTIALLY FIXED** | Arquivo tem 75 linhas (linha 494 não existe); sem URLs hardcoded nele. Mas invariante violada em `YouTubeDiscoveryDriver.cs` e `MediaTranscribeJobExecutor.cs` | IO-03, IO-04 (já no P2 IO) |
| Status strings distribuídas fora de `StatusVocabulary` | **NOT FIXED** | >40 literais confirmados via grep (190 matches totais em 48 arquivos; subtraindo StatusVocabulary, migrations, snapshots, Contracts): `HangfireJobQueueRepository.cs` 17 hits, `IngestJobExecutor.cs` 15, `FetchJobExecutor.cs` 17, `SourceDiscoveryJobExecutor.cs` 8. Gemini reportou ~44; forense anterior dizia "12+" (subcontagem de apenas 1 arquivo). | **IO-07** (não fixed) |
| `DashboardService.cs` ~1297 linhas | **PARTIALLY FIXED** | Atual: 587 linhas — lógica extraída para SourceControlService, PipelineStatsService, DlqService. Sub-serviços internos não verificados | — monitorar |
| `Program.cs` ~700 linhas | **NOT FIXED** | Atual: 716 linhas confirmadas | **IO-08** (novo) |
| `FetchJobExecutor.cs` ~2246 linhas | **PARTIALLY FIXED** | Atual: 1166 linhas (reduzido mas ainda gravity center) | **IO-09** (novo) |
| Transaction race em check+enqueue | **FIXED** | `AcquireEnqueueLockAsync` (advisory lock PG) + `BeginTransactionAsync` tornam TOCTOU impossível | — nada a fazer |
| Auditoria 4.1: `Task.Run` fire-and-forget em `PostgreSqlSourceCatalogService.cs:34` | **FALSE CLAIM** | Linha 34 é `_logger = logger`; linha 35 é `ResolveSourcesPath(...)` (síncrona). Constructor não contém `Task.Run`. `StartAsync` = `await InitializeAsync(ct)`. | — |
| Auditoria 4.5: `GetAwaiter().GetResult()` em pipeline Hangfire | **FALSE CLAIM** | Grep completo de `src/**/*.cs` — zero ocorrências de `.GetAwaiter().GetResult()`, `.Wait()` ou bloqueio de task. As duas ocorrências de `.Result` são coluna EF e `Polly.DelegateResult.StatusCode`. | — |
| Auditoria 4.6: `StopSourceAsync` grava `idle`; checks usam `paused`/`stopped` | **FALSE CLAIM** | `SourceControlService.StopSourceAsync:150,156` grava `Status.Stopped` ("stopped"). `IsSourcePausedOrStoppedAsync:28` checa `Status.Paused or Status.Stopped`. Consistente. `DashboardService.cs:844` não existe (arquivo tem 587 linhas). | — |
| Auditoria 5.1: `Gabi.Sync` e `Gabi.Jobs` dependem de `Gabi.Postgres` | **FALSE CLAIM** | Ambos `.csproj` têm apenas `Gabi.Contracts` como `ProjectReference`. Sem referência a `Gabi.Postgres`. | — |
| Auditoria 4.2: Sync-over-async em `DlqFilter.cs:79` (claim de deadlock) | **FIXED** | `OnStateElection` é `void` (API síncrona do Hangfire). `SaveChanges()` é sync EF dentro de método sync. Zero `.GetAwaiter().GetResult()` no arquivo. Padrão correto para API síncrona. | — |
| Auditoria 4.3: `GlobalJobFilters` mutado em bootstrap (race condition) | **FIXED** | Mutações em `Worker/Program.cs:228,232` ocorrem antes de `host.Run():245`. Nenhum worker thread existe antes de `host.Run()`. Thread-safe por ordenação. | — |
| Auditoria 6.4: Retry logic mismatch Hangfire vs Sync | **FIXED** | Dois caminhos disjuntos por design: Hangfire usa `DlqFilter`→`IntelligentRetryPlanner`; Gabi.Sync usa `JobQueueRepository` próprio. Nenhum conflito — operam em conjuntos separados de jobs. | — |
| Auditoria 7.3: Fallback users com senhas conhecidas | **FIXED** | Guard `IsDevelopment()` — lança `InvalidOperationException` em produção sem `GABI_USERS`. BCrypt.HashPassword em runtime. Plaintext não persiste além do stack frame. | — |
| Gemini R-07: "Service Locator reduzido de 15→4 `CreateScope()` calls" | **FALSE CLAIM** | Grep em `src/**/*.cs` revela ~50 `CreateScope()` calls em produção: `LogicalReplicationProjectionWorker.cs` (5), `PostgreSqlSourceCatalogService.cs` (10), `PipelineStatsService.cs` (7), `SourceQueryService.cs` (4), `DashboardService.cs` (4), `DlqService.cs` (4), `SourceControlService.cs` (3), `JobWorkerHostedService.cs` (5), e outros. O contagem de 4 não corresponde ao código real | — nenhum item de backlog (claim falsa); o padrão é real mas a magnitude reportada é incorreta |
| Gemini R-04: "~44 literais de status" | **NOT FIXED (contagem confirmada)** | Grep confirma: 190 matches em 48 arquivos; >40 em código de produção fora de `StatusVocabulary.cs`. Gemini's ~44 é plausível mas subestimado. V10 IO-07 já rastreia. | IO-07 (descrição atualizada nesta sessão) |
| Auditoria 8.1: N+1 em DashboardService.cs:224 e :1053 | **NOT FIXED (localização falsa; padrão real)** | DashboardService.cs tem 587L (linha 1053 não existe); a lógica foi extraída para `PipelineStatsService.GetStatsAsync()` que tem `foreach (var s in sources) { await linkRepo.GetBySourceAsync(s.Id) }` — N+1 confirmado por leitura direta | IO-10 (novo) |
| Auditoria 8.2: N+1 em PostgreSqlSourceCatalogService.cs:83 | **FIXED** | Linha 83 usa `linkRepo.GetBySourcesAsync(sourceIds, ct)` — single bulk query; `GetSystemStatsAsync` idem. O fix foi aplicado corretamente a este serviço. | — nada a fazer |
| Auditoria 8.4: guardrail mode carrega 5000 links + N+1 docCount | **NOT FIXED** | `SourceQueryService.GetLinksAsync:121-130` — `pageSize=5000` hardcoded + `foreach` com `GetDocumentCountAsync` por link = até 5001 queries; filtragem incompleta se source tem >5000 links | IO-11 (novo) |
| Auditoria 8.6: fallback search ToLower().Contains full scan (Program.cs:388) | **PARTIALLY FIXED** | 503 guard cobre "ES não configurado em não-Dev". Mas: em Development (requireEs=false), e se searchService != null mas SearchAsync retorna null → falls through para scan O(N). `LOWER(content) LIKE '%x%'` não usa índice. | — monitorar junto com EH-05 (SearchService swallow) |
| Auditoria 10.5: architecture test vacuous (Types.InCurrentDomain + só Contracts no csproj) | **NOT FIXED** | `Gabi.Architecture.Tests.csproj` tem apenas Gabi.Contracts como ProjectReference. `DomainLayer_ShouldNotReference_Infrastructure` usa `Types.InCurrentDomain().That().ResideInNamespace("Gabi.Discover")` → zero types carregados → vacuously true. Se Gabi.Discover referenciar Gabi.Postgres, o teste ainda passa. Somente o ContractsLayer test é válido. | **ARCH-01** (novo) |
| Auditoria §15: Pipeline correctness — "stop writes idle, guards check stopped" (DashboardService.cs:844) | **FALSE CLAIM** | DashboardService.cs tem 587 linhas (linha 844 não existe). Auditoria já registrada em s3 com evidência de `SourceControlService.StopSourceAsync` e `IsSourcePausedOrStoppedAsync`. | — |
| Auditoria §15: "Fire-and-forget em PostgreSqlSourceCatalogService.cs:34" | **FALSE CLAIM** | Já registrado em s3. Linha 34 = assignment síncrono. `StartAsync` = `await InitializeAsync(ct)`. | — |
| Auditoria §15: "Sync-over-async em DlqFilter.cs:79" | **FALSE CLAIM** | Já registrado em s3. `IElectStateFilter.OnStateElection` é API síncrona do Hangfire; `SaveChanges()` correto. | — |
| Auditoria §15: Hardcoded URLs em ApiPaginationDiscoveryAdapter.cs:494 | **FALSE CLAIM** | Arquivo tem 75 linhas; linha 494 não existe. Nenhuma URL hardcoded no arquivo; delega para drivers. IO-04 rastreia `YouTubeDiscoveryDriver` (real). | — |
| Auditoria §12: "uso de tipos infra em Phase0Orchestrator.cs" | **FALSE CLAIM** | `Phase0Orchestrator.cs` lido linha a linha: imports são `Gabi.Contracts.Api`, `Gabi.Contracts.Discovery`, `Gabi.Contracts.Pipeline`, `Microsoft.Extensions.Logging`, BCL. Zero imports de `Gabi.Postgres` ou EF Core. Injecta `IPhase0LinkRepository`, `ISourceCatalog`, `IDiscoveryEngine` — todos interfaces em Contracts. | — |
| Auditoria §12: "Gabi.Sync.csproj e Gabi.Jobs.csproj referenciam Gabi.Postgres" | **FALSE CLAIM** | Ambos `.csproj` lidos: um único `ProjectReference` each (`Gabi.Contracts`). Grep em `src/Gabi.Sync/**/*.cs` — zero ocorrências de `using Gabi.Postgres`. Já registrado em s3; confirmado novamente com evidência adicional de `Phase0Orchestrator.cs`. | — |
| Auditoria §17: "IntentGuardrails em DashboardService.cs linhas 312-387 usa heurística semântica/probabilística" | **FALSE CLAIM** | `IntentGuardrails` é `public static class` em `src/Gabi.Api/Services/IntentGuardrails.cs` (71 linhas) — arquivo separado, não DashboardService.cs. Implementação é 100% rule-based: 4 intents conhecidos, comparações `string.Equals` em campos `document_kind` e `normative_force`. Sem ML, sem inferência probabilística. | — |
| Auditoria §17: "Temporal workflow engine — ainda não considerado como próximo passo" | **FALSE CLAIM** | Temporal já implementado como RELY-B: `PipelineWorkflow`, `PipelineActivities`, `TemporalWorkerHostedService`, `TemporalWorkflowOrchestrator` em `src/Gabi.Worker/Temporal/`. Kill-switch `EnableTemporalWorker=false` por padrão; runtime validation pendente (RV-1..2). | — |
| Auditoria §17: "CDC-based projection repair — ainda não considerado como próximo passo" | **FALSE CLAIM** | CDC/WAL projection já implementado como RELY-C: `LogicalReplicationProjectionWorker`, `WalProjectionBootstrapService`, `ProjectionLagMonitor`, `DriftAuditorJobExecutor` em `src/Gabi.Worker/Projection/`. Kill-switch `EnableWalProjection=false` por padrão; runtime validation pendente (RV-3..5). | — |
| Auditoria §17: "ErrorTaxonomy.cs para categorização de retry no DlqFilter" | **VERIFIED CORRECT** | `DlqFilter.cs:42` — `ErrorClassifier.Classify(failedState.Exception)` chamado diretamente. `IntelligentRetryPlanner.Plan(classification, retryCount, maxRetries)` roteia: `Permanent`/`Bug` → DLQ imediato; `Throttled` → 15min retry; `Transient` → exponential backoff (clamped 1–60s). Implementação verificada em `IntelligentRetryPlanner.cs` (34 linhas). | — |
| Auditoria §12: "múltiplas implementações ativas de fila" (Gabi.Sync.JobQueueRepository vs HangfireJobQueueRepository) | **NOT FIXED (dead code)** | `Gabi.Sync.Jobs.JobQueueRepository` (Dapper + SKIP LOCKED) e `Gabi.Sync.Jobs.JobWorkerService` existem mas NUNCA são registrados em `Api/Program.cs` ou `Worker/Program.cs`. `Gabi.Postgres.Repositories.JobQueueRepository` é marcado `[Obsolete]` e também não registrado. Produção usa exclusivamente `HangfireJobQueueRepository`. Sem runtime bug mas código morto significativo que pode confundir desenvolvedores. | **SYNC-01** (novo) |
| Auditoria §13: WorkerCount=1 para pipeline-stages (concern de escalabilidade) | **DESIGN INTENCIONAL** | `Worker/Program.cs:123` — comentário inline explica: separar `pipeline-stages` (WorkerCount=1) de `embed-pool` (WorkerCount=EmbedWorkerCount, default 3) é anti-tarpitting deliberado para evitar que embedding lento bloqueie discovery/fetch. Não é um bug ou limitação oculta. | — |
| Auditoria §13: PostgreSQL SPOF em docker-compose (sem réplica/HA) | **CONCERN DE INFRA DE PRODUÇÃO** | `docker-compose.yml` tem instância única de Postgres — correto para dev. Em produção usa-se serviço gerenciado (RDS Multi-AZ, etc.). Não é um bug de código; é uma decisão de infraestrutura de produção fora do escopo deste plano. | — |

### 5.8 `pendente` — herdado de V9

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

### P2 — I/O & Boundary Discipline (IO items — verificados em 27/02/2026)

| # | ID | Item | Arquivo |
|---|---|---|---|
| IO-1 | **IO-03** 🔴 | Criar `ITranscriptionService` em Contracts; mover OpenAI HTTP para adapter injetável | `Gabi.Worker/Jobs/MediaTranscribeJobExecutor.cs` → novo `Gabi.Worker/Adapters/OpenAiTranscriptionService.cs` |
| IO-2 | **IO-01** 🟡 | Remover defaults `localhost` de OTLP e Temporal; falhar fast no startup se ausentes | `Worker/Program.cs`, `Api/PipelineServiceExtensions.cs`, `TemporalHealthCheck.cs` |
| IO-3 | **IO-02** 🟡 | `SystemHealthService`: injetar `IHttpClientFactory`, mover URL ES para config, remover hardcoded timeout | `src/Gabi.Api/Services/SystemHealthService.cs` |
| IO-4 | **IO-04** 🟡 | `YouTubeDiscoveryDriver`: mover URLs `googleapis.com` para config; tornar testável via interface | `src/Gabi.Discover/Drivers/YouTubeDiscoveryDriver.cs` |
| IO-5 | **IO-05** 🟡 | `PostgreSqlSourceCatalogService`: extrair `ISourceYamlLoader`; deixar service como orchestrator | `src/Gabi.Api/Services/PostgreSqlSourceCatalogService.cs` |
| IO-6 | **IO-06** 🟡 | Corrigir Redis port em `appsettings.Development.json`: 6379 → 6380 | `src/Gabi.Worker/appsettings.Development.json` |
| IO-7 | **IO-07** 🟡 | Substituir 12+ literais de status (`"failed"`, `"pending"`, `"running"`, etc.) por referências a `StatusVocabulary` — incluindo `HangfireJobQueueRepository` (`GetLatestActiveForSourceAndJobTypeAsync`) e defaults de entidades | `HangfireJobQueueRepository.cs`, `IngestJobExecutor.cs`, `EmbedAndIndexJobExecutor.cs`, `Program.cs`, `SourcePipelineStateEntity.cs`, `SourceRefreshEntity.cs` |
| IO-8 | **IO-08** 🟡 | `Program.cs` (Api): 716 linhas — gravity center; extrair grupos de endpoints em arquivos de extensão dedicados | `src/Gabi.Api/Program.cs` |
| IO-9 | **IO-09** 🟡 | `FetchJobExecutor.cs`: 1166 linhas — gravity center; candidato a extração de responsabilidades (streaming, cap logic, persistence, telemetry) | `src/Gabi.Worker/Jobs/FetchJobExecutor.cs` |

### P2 — Error Handling (EH items — verificados em 27/02/2026)

| # | ID | Item | Arquivo |
|---|---|---|---|
| EH-1 | **EH-03** 🟡 PARTIALLY FIXED | WAL projection: `WriteToDlqAsync` — contador + crash-após-5 implementados; GAP: per-event retry ausente; falhas não-consecutivas perdem doc permanentemente; adicionar Polly retry por evento | `LogicalReplicationProjectionWorker.cs` |
| EH-2 | **EH-04** 🟡 PARTIALLY FIXED | WAL projection: `PersistCheckpointAsync` — contador + rethrow-após-3 implementados; GAP: nas 2 primeiras falhas slot avança sem checkpoint salvo; não chamar `SetReplicationStatus` se save falhou | `LogicalReplicationProjectionWorker.cs` |
| EH-3 | **EH-06** 🟡 | Unificar contratos de erro da API em `ApiError` em todos os endpoints | `src/Gabi.Api/Program.cs` |
| EH-4 | **EH-01** 🟡 | `GabiJobRunner`: `LogError` ao falhar resolução de `IWorkflowEventRepository` | `src/Gabi.Worker/Jobs/GabiJobRunner.cs` |
| EH-5 | **EH-05** 🟡 | `SearchService`: sinalizar `embeddingFailed: true` no DTO quando fallback BM25-only | `src/Gabi.Ingest/SearchService.cs` |
| EH-6 | **EH-02** 🟡 | Adicionar `LogError` nos fall-open de parse de config em `PostgreSqlSourceCatalogService` e `SystemHealthService` | `src/Gabi.Api/Services/` |
| ~~EH-7~~ | ~~**EH-07**~~ ✅ feito | ~~WAL projection: scope never disposed~~ — `using var scope` presente em `IndexDocumentWithVersionAsync:217`; feito | — |
| EH-8 | **EH-08** 🟡 | `EmbedAndIndexJobExecutor`: double-embedding race — `embed_and_index` não tem single-in-flight guard (`EnforceSingleInFlightPerSource` retorna false para este tipo); backpressure reduz frequência mas não elimina; xmin previne double-write silencioso mas double TEI API call ainda ocorre; comment no código confirma: "Single-in-flight is NOT enforced per source" | Adicionar `"embed_and_index"` ao set em `EnforceSingleInFlightPerSource`, ou implementar `IdempotencyKey` baseado em hash dos doc IDs do batch no `EnqueueAsync` |

### P2 — I/O & Performance (items adicionais — 27/02/2026 s4)

| # | ID | Item | Arquivo |
|---|---|---|---|
| IO-10 | **IO-10** 🔴 | `PipelineStatsService.GetStatsAsync` — N+1 por source migrado do DashboardService; usar `GetBySourcesAsync` + GroupBy | `src/Gabi.Api/Services/PipelineStatsService.cs` |
| IO-11 | **IO-11** 🔴 | `SourceQueryService.GetLinksAsync` guardrail — 5000-row fetch + N+1 docCount por link; mover filtro para SQL ou batch counts | `src/Gabi.Api/Services/SourceQueryService.cs` |
| IO-12 | **IO-12** 🟡 | `SourceQueryService.GetLinksAsync` normal path — N+1 docCount por link paginado; adicionar `GetDocumentCountBulkAsync` | `src/Gabi.Api/Services/SourceQueryService.cs` |
| IO-13 | **IO-13** 🟡 | `coming_soon` hardcoded para 4 fases implementadas (Ingest/Processing/Embedding/Indexing) — dashboard mente ao operador | `PipelineStatsService.cs`, `SourceQueryService.cs` |
| IO-14 | **IO-14** 🟡 | `FetchAndParseJsonApiAsync` — `JsonDocument.ParseAsync(stream)` sem byte cap; path link-only tem dois guards (`Content-Length` + `ReadAllBytesWithLimitAsync`); path JSON API não tem nenhum — large JSON response OOM possível | `src/Gabi.Worker/Jobs/FetchJobExecutor.cs` (método `FetchAndParseJsonApiAsync`) |
| IO-15 | **IO-15** 🟡 | `GenericPaginatedDiscoveryDriver` — `yield break` silencioso em falha de página API; sem registro de página com falha; sem cursor resumível para driver genérico; discovery completa parcialmente sem sinalizar páginas perdidas | `src/Gabi.Discover/Drivers/GenericPaginatedDiscoveryDriver.cs` |

### P2 — Architecture Tests

| # | ID | Item | Arquivo |
|---|---|---|---|
| ARCH-1 | **ARCH-01** 🔴 | `DomainLayer_ShouldNotReference_Infrastructure` é vacuosamente verdadeiro: domain assemblies não carregados em runtime do teste; violação real não seria detectada | `tests/Gabi.Architecture.Tests/Gabi.Architecture.Tests.csproj` + `LayeringTests.cs` — adicionar ProjectReferences aos domínios OU usar `Types.FromAssembly(Assembly.LoadFrom(...))` |

### P2 — Scalability / Operational Stability

| # | ID | Item | Arquivo |
|---|---|---|---|
| SCAL-1 | **SCAL-01** 🟡 | Sem global admission control — backpressure só per-source; a 200 sources cada uma no teto per-source, o Hangfire queue cresce para milhões de jobs sem nenhum ceiling global; drain time é O(total_items / single_worker_throughput) | `PipelineBackpressureConfig.cs` — adicionar contadores globais (`TotalPendingFetch`, `TotalPendingEmbed`) e gate global em cada executor antes do check per-source |
| SCAL-2 | **SCAL-02** 🟡 | `ScheduleAsync` sem advisory lock nem active-check — dedup indireto via `job_registry.status="pending"` protege re-triggers externos mas não protege race entre dois callers simultâneos (ex: DLQ replay + backpressure reschedule); gap estreito mas não fechado por contrato | `HangfireJobQueueRepository.ScheduleAsync` — adicionar transaction + `GetLatestActiveForSourceAndJobTypeAsync` check para tipos single-in-flight |
| SCAL-3 | **SCAL-03** 🟡 | Single pipeline worker (WorkerCount=1) sem per-source time-slicing — uma fonte lenta (fetch 5s/item × 10k items = 14h) monopoliza todos os estágios não-embed para todas as 200 fontes; design intencional (anti-tarpitting) mas operacionalmente não viável a escala | `Worker/Program.cs` — considerar WorkerCount=2–4 para pipeline-stages + fair-queue per-source (round-robin ou lease-based scheduling) |

### P2 — Technical Debt / Dead Code

| # | ID | Item | Arquivo |
|---|---|---|---|
| SYNC-1 | **SYNC-01** 🟡 | Código morto: `Gabi.Sync.Jobs.JobQueueRepository` (Dapper + SKIP LOCKED) e `Gabi.Sync.Jobs.JobWorkerService` (polling worker) nunca registrados em DI; `Gabi.Postgres.Repositories.JobQueueRepository` marcado `[Obsolete]` e também não registrado. Produção usa apenas `HangfireJobQueueRepository`. Risco: confusão futura sobre qual implementação é canônica | Remover `Gabi.Sync.Jobs.JobQueueRepository` + `JobWorkerService` + `JobWorker` + `RetryPolicy`; remover `Gabi.Postgres.Repositories.JobQueueRepository`; ou mover para pasta `_legacy/` com nota clara |

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
- P2 IO: IO-10/11/12 (N+1 em PipelineStatsService+SourceQueryService — rota quente), IO-03 (OpenAI sem ACL — crítico), IO-07 (>40 status literals), IO-08/09 (gravity centers: Program.cs 716L, FetchJobExecutor.cs 1166L), IO-13 (coming_soon para fases implementadas), IO-01/02/04/05/06 (localhost defaults, abstrações mistas, Redis port)
- P2 ARCH: ARCH-01 (DomainLayer architecture test vacuosamente verdadeiro — não detecta violações reais de camada)
- P2 EH: EH-03/04 (WAL projection PARTIALLY FIXED — per-event retry ausente em EH-03; slot-advance-sem-checkpoint em EH-04 — gap estreito), EH-06 (contratos inconsistentes), EH-01/02/05 (logging + sinalização) | EH-07 ✅ FEITO (scope leak corrigido)
- P2 SYNC: SYNC-01 (código morto: Gabi.Sync.Jobs.JobQueueRepository + JobWorkerService + Gabi.Postgres.Repositories.JobQueueRepository [Obsolete] — nunca registrados; apenas HangfireJobQueueRepository é ativo)
- P2 IO: IO-14 (FetchAndParseJsonApiAsync — JsonDocument.ParseAsync sem byte cap, path link-only tem guard, path JSON API não tem), IO-15 (GenericPaginatedDiscoveryDriver yield break silencioso em falha de página — discovery parcialmente incompleta sem registro de falha)
- P2 EH: EH-08 (embed_and_index sem single-in-flight guard — double TEI API call possível; xmin previne double-write mas não double work)
- P2 SCAL: SCAL-01 (sem global admission cap — somente per-source; 200 fontes no teto = milhões de jobs sem ceiling global), SCAL-02 (ScheduleAsync sem lock — dedup indireto não é contrato; race estreito com DLQ replay), SCAL-03 (WorkerCount=1 para pipeline-stages — fonte lenta monopoliza todos os estágios para todas as fontes; sem time-slicing)
- P2 geral: `Result<T>`, `Dictionary<string,object>` em payloads, `IdempotencyKey` não wired, Redis/ES auth, NuGet audit completo, `TreatWarningsAsErrors`, migrations CONCURRENTLY, build determinístico, deploy blue/green, backups testados, `OpenTelemetry.Instrumentation.EntityFrameworkCore` stable.

---

## 10. Governança de Execução do Plano

1. Este arquivo é a única fonte de planejamento operacional corrente.
2. Qualquer atualização deve alterar: Snapshot Atual, Inventário DEF, Backlog Único.
3. Evidência mínima para mover item a `feito`: diff de código + teste automatizado ou execução comprovada.
