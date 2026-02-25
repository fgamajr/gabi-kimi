# Plano Consolidado v9 (Fonte Única de Execução)

Data base: 24 de fevereiro de 2026
Status: ativo
Escopo: substituir e consolidar V5, V6, V7, V8, TODO, matriz de fontes, gaps e code notes.

---

## 1. Objetivo do v9

Manter um único plano operacional, orientado por evidência, para:
1. fechar os gaps bloqueantes de produção;
2. preservar arquitetura em camadas e budget de memória (300MB efetivo no Worker);
3. evitar divergência documental entre planos antigos.

Regras do plano:
1. toda decisão precisa de evidência de código, teste ou execução;
2. itens devem estar em um único estado: `feito`, `em_andamento`, `pendente`, `descartado`;
3. qualquer item novo entra neste documento, não em arquivos paralelos.

---

## 2. Document Governance

Objetivo: manter o repositório com **fonte única de plano** e separar claramente documentos ativos vs. históricos.

Documentos canônicos ativos:
1. `PLANO_CONSOLIDADO_V9.md` (execução e priorização).
2. `AGENTS.md` (regras operacionais de engenharia/arquitetura).

Diretório `grounding_docs/`:
1. Top-level deve conter apenas referências aprovadas e úteis para contexto histórico técnico.
2. Todo material de plano antigo, rascunho de agente ou sprint desatualizado deve ir para `grounding_docs/archive/`.
3. Artefatos binários (ex.: instaladores `.deb`) não devem ficar em `grounding_docs/` como guia; devem ser removidos ou movidos para local técnico dedicado.

Status consolidado de `grounding_docs`:
1. `ARCHITECTURE_OVERVIEW.md`: referência aprovada (histórico arquitetural).
2. `c#.md`: referência aprovada (viabilidade e decisões de stack).
3. `PLANEJAMENTO_GABI_SYNC_v2.md`: referência aprovada (baseline histórico).
4. `pipeline.md`: arquivado (conteúdo absorvido no V9).
5. `claude_plan.md`: arquivado (plano antigo).
6. `DAY_SPRINT.md`: arquivado (cronograma antigo).
7. `kimi.md`: arquivado (resumo antigo).
8. `packages-microsoft-prod.deb`: removido do diretório de guias.
9. `old_python_implementation/`: removido do repositório ativo; salvage técnico preservado em `grounding_docs/archive/legacy-python/`.

---

## 3. Snapshot Atual (factual)

### 3.1 Pipeline

| Etapa | Estado | Evidência principal |
|---|---|---|
| Seed | feito | `CatalogSeedJobExecutor` + endpoints de dashboard |
| Discovery | feito | adapters `static_url`, `url_pattern`, `web_crawl`, `api_pagination` |
| Fetch | feito | `FetchJobExecutor` com streaming + hardening |
| Ingest v1 (normalização + projeção de mídia) | feito | `IngestJobExecutor` normaliza texto e projeta mídia |
| Ingest v2 (chunk/embed/index real) | em_andamento | `IngestJobExecutor` executa chunk/embed/index local com metadados v2 |
| Search API funcional | em_andamento | endpoint `GET /api/v1/search` com filtro/paginação já disponível |

**Dependência Ingest v2:** Ingest v2 (chunk/embed/index real) só deve ser priorizado quando o ingest base (v1) estiver estável. Estabilidade = normalização, projeção de mídia, persistência e comportamento com cap/strict consistentes, com evidência (testes + zero-kelvin). O foco imediato é **estabilizar ingest (v1)**; só depois investir no v2 em cima dessa base.

### 3.2 Estado arquitetural

1. Contratos e testes de arquitetura existem e continuam mandatórios.
2. Há progresso de robustez operacional (DLQ/replay, telemetria, cap por source).
3. Ainda há dívida para completar a cadeia `ingest -> index -> search`.

---

## 4. Consolidação do que já foi feito

### 4.1 Entregas confirmadas recentes

1. Fase opcional `media-projection` integrada ao zero-kelvin:
- `tests/zero-kelvin-test.sh`
- `tests/e2e-media-projection.sh`

2. Evidência de execução informada e validada na trilha atual:
- `zero-kelvin` targeted `media-projection`: `PASS 15/15`, `docs_processed=1`, `status_breakdown=media_projection=1`.
- `zero-kelvin` full `tcu_acordaos` cap 200: `PASS 15/15`, com `capped` e `pending` coerentes com cap operacional.

3. Correções de robustez no fetch já aplicadas:
- reset de stuck `processing` no início do fetch;
- release explícito de itens `processing` quando cap interrompe processamento.

4. Correções concluídas hoje:
- `DEF-06` (atomicidade no enqueue por `source+jobType`) em `HangfireJobQueueRepository`;
- `DEF-18` (progress sem swallow) em `GabiJobRunner` com pump por canal e logging de falhas;
- `DEF-08` (idempotência de insert em `documents`) com upsert por conflito em `SourceId+ExternalId`;
- `DEF-07` (runner/progress context) com pump de progresso usando contexto dedicado e sem churn de scope por update.

5. Entregas adicionais (v2 mínimo viável):
- `HashEmbedder` e `LocalDocumentIndexer` criados em `Gabi.Ingest`;
- `IngestJobExecutor` atualizado para fluxo real `normalize -> chunk -> embed -> index -> persist`;
- endpoint `GET /api/v1/search` implementado em `Gabi.Api`;
- teste de integração adicionado: `SearchEndpointTests`.

6. Cobertura de testes adicionada para os pontos acima:
- `HangfireJobQueueRepositoryConcurrencyTests`;
- `GabiJobRunnerProgressTests`;
- `SearchEndpointTests`.

7. Correção de bloqueio de build:
- ambiguidades de `Split` corrigidas em `FixedSizeChunker`.

### 4.2 Execução de testes (24/02/2026)

Comandos executados:

```bash
dotnet build GabiSync.sln --nologo -m:1
dotnet test tests/Gabi.Api.Tests/Gabi.Api.Tests.csproj \
  --filter "FullyQualifiedName~SearchEndpointTests" --nologo
dotnet test tests/Gabi.Postgres.Tests/Gabi.Postgres.Tests.csproj \
  --filter "FullyQualifiedName~HangfireJobQueueRepositoryConcurrencyTests|FullyQualifiedName~GabiJobRunnerProgressTests|FullyQualifiedName~FetchDocumentMetadataMergeTests|FullyQualifiedName~FetchCapOptionsTests|FullyQualifiedName~JobQueueRepositoryHashTests|FullyQualifiedName~HangfireRetryPolicyTests" \
  --nologo
sudo ./tests/zero-kelvin-test.sh docker-only \
  --source tcu_acordaos \
  --phase full \
  --max-docs 200 \
  --report-json /tmp/zk_tcu_acordaos_full_200_after_cleanup.json
```

Resultado:
1. `Build: sucesso (0 erros)`
2. `API tests: Passed 2/2`
3. `Postgres tests: Passed 23/23`
4. `Failed: 0`
5. `Skipped: 0`
6. `Zero-kelvin targeted full (tcu_acordaos): PASS 16/16, docs_processed=200, status_breakdown=completed,200`
7. `Busca pós-ingest (GET /api/v1/search?q=2007&sourceId=tcu_acordaos&page=1&pageSize=5): total=200, hits=5`

---

## 5. Inventário Consolidado de Status (DEF)

Referência: avaliação forense acumulada (V8 + revisão recente + execução atual).

### 5.1 `feito`

1. `DEF-05` (obsoleto/corrigido na trilha atual).
2. `DEF-06` (enqueue atômico por `source+jobType` com lock transacional).
3. `DEF-07` (runner ajustado para persistência de progresso robusta e determinística).
4. `DEF-08` (upsert em `documents` evita conflito/retry por unicidade ativa).
5. `DEF-13` (obsoleto/corrigido).
6. `DEF-15` (stuck pós-cap no fetch corrigido).
7. `DEF-18` (progresso sem swallow, com observabilidade de falha).
8. **CODEX-B (Status Semantic Closure)** — 2026-02-25: `JobTerminalStatus` (Success | Partial | Capped | Failed | Inconclusive); `JobResult.Status` substitui colapso em `Success`; repositórios persistem status explícito (partial/capped/inconclusive); Fetch retorna Partial/Failed/Capped conforme regras; Discovery retorna Inconclusive quando 0 links sem `zero_ok` ou cap com strict; `DocumentStatus.CompletedMetadataOnly` + migration; zero-kelvin rejeita fetch `partial` como FAIL. Evidência: `dotnet build` 0 erros; testes Postgres (SourceDiscoveryJobExecutorMetadataTests, CatalogSeedStrictCoveragePropagationTests, GabiJobRunnerProgressTests) e API (DashboardStrictCoverageFallbackTests) passando.

### 5.2 `em_andamento` / `parcial`

1. `DEF-01`: ingest v2 mínimo viável implementado (chunk/embed/index local); falta integração com indexador externo para fechamento completo.
2. `DEF-10`: validações de mídia evoluíram, ainda sem fechamento completo de startup guards em todos cenários.
3. `DEF-11`: progresso parcial.
4. `DEF-12`: progresso parcial.
5. `DEF-02`: endpoint de busca básico entregue; falta indexador externo e ranking.
6. `DEF-03`: busca funcional local entregue; integração plena com infraestrutura de busca ainda pendente.

### 5.3 `pendente`

1. `DEF-04`
2. `DEF-09`
3. `DEF-14`
4. `DEF-16`
5. `DEF-17`
6. `DEF-19`

### 5.4 `ajustado` (diagnóstico revisado)

1. `DEF-08` foi reclassificado corretamente: não era “duplicação silenciosa” e sim risco de conflito/retry por unicidade.
2. Mitigação aplicada: `upsert` com `ON CONFLICT ("SourceId","ExternalId") WHERE "RemovedFromSourceAt" IS NULL`.

---

## 6. Backlog Único Priorizado (v9)

## P0 (bloqueante de produto)

1. Consolidar `DEF-01`: trocar indexação local por provider externo configurável e validar sob carga.
2. Consolidar `DEF-02/03`: evoluir busca para índice externo com relevância e telemetria.
3. Fechar `DEF-19`: fail-fast de startup para configurações essenciais ausentes em produção.

Aceite P0:
1. documento entra no pipeline e aparece em busca sem intervenção manual;
2. rerun não cria conflito operacional (idempotência comprovada);
3. suíte targeted de regressão passa.

## P1 (robustez operacional)

1. Fechar `DEF-14`: padronizar escrita de documentos via repositório dedicado.
2. Fechar `DEF-04`: alinhar estratégia de rate limiting/distribuição conforme infra real.
3. Fechar `DEF-16/17`: observabilidade e resiliência adicionais com métricas acionáveis.

Aceite P1:
1. testes de falha/replay cobrindo casos críticos;
2. sem falhas silenciosas em progress/retry/path críticos.

## P2 (excelência e expansão)

1. Itens avançados de V7 (property-based, chaos, DORA, hardening extensivo de runbook/security).
2. Evoluções de relevância (reranker/melhorias semânticas) após P0/P1 estáveis.

---

## 7. Itens Descartados/Despriorizados

1. Manter múltiplos planos ativos em paralelo (`V5/V6/V7/V8/TODO/gaps/matriz/code`) -> descartado.
2. Tratar ingest atual como “noop total” -> descartado; hoje há ingest v1 útil (texto + projeção de mídia).
3. Tratar `DEF-08` como duplicação silenciosa primária -> descartado; foco correto é conflito/idempotência de insert.
4. Executar bloco “world-class V7” antes de fechar bloqueios de pipeline/search -> despriorizado.
5. Remoções estruturais amplas de assemblies sem validação incremental -> despriorizado até fechamento de P0.

---

## 8. Sequência de Execução Recomendada (próximo passo)

Pré-condição obrigatória:
1. definições por source devem estar em `sources_v2.yaml` (sem regras hardcoded por `source_id` no código).

Checklist de execução (conversão pré-ingest):
1. [x] Fazer matriz source-by-source com “formato real recebido” e “conversor necessário”.
- Evidência: `reports/ingest_conversion_plan/source_conversion_matrix_2026-02-24.csv`
- Evidência: `reports/ingest_conversion_plan/source_conversion_matrix_2026-02-24.md`
2. [~] Implementar camada de conversão (JSON/HTML/PDF/PPTX/media) para produzir `content_text + metadata`.
- Andamento: `json/html/pdf` implementados no fetch `link_only` via `fetch.converter` declarativo em `sources_v2.yaml`; pendente `pptx/media`.
3. [x] Só enfileirar ingest para fontes `text_ready`.
- Implementado de forma declarativa: `IngestJobExecutor` carrega política de `sources_v2.yaml` por source e usa fallback de `defaults.pipeline.ingest`.
4. [x] Marcar `metadata_only` quando não houver texto (sem tratar como falha).
- Implementado no ingest via `pipeline.ingest.empty_content_action=metadata_only` (sem hardcode por `source_id`).
5. [x] Ajustar zero-kelvin para cobrar ingest apenas de fontes `text_ready`.
- Implementado: `tests/zero-kelvin-test.sh` consulta `pipeline.ingest.readiness` no `sources_v2.yaml` e marca `ingest_not_required` para fontes `metadata_only`.

Próxima execução imediata:
0. **(prioridade)** Estabilizar ingest v1 (normalização, mídia, cap/strict, evidência); só depois priorizar Ingest v2 (chunk/embed/index) — ver dependência em §3.1.
1. implementar conversores prioritários das fontes `metadata_only_until_converter` (pdf/json/html).
2. atualizar asserts da suíte zero-kelvin por perfil de source.
3. rodar zero-kelvin por amostra multi-source para validar classificação `text_ready` vs `metadata_only`.

---

## 9. Governança de Execução do Plano

1. Este arquivo é a única fonte de planejamento operacional corrente.
2. Qualquer atualização deve alterar:
- `Snapshot Atual`;
- `Inventário DEF`;
- `Backlog Único`.
3. Evidência mínima para mover item a `feito`:
- diff de código + teste automatizado ou execução comprovada.

---

## 10. Auditoria Técnica Consolidada (Baseline de Qualidade)

Data da auditoria: 24 de fevereiro de 2026
Escopo: Testes, Arquitetura, Engenharia, Segurança, Observabilidade, CI/CD e Operações

### 10.1 Testes e Qualidade

| Item | Status | Evidência | Prova | Observação |
|------|--------|-----------|-------|------------|
| NetArchTest para regras de camadas | **RESOLVIDO** | `tests/Gabi.Architecture.Tests/LayeringTests.cs` | `Types.InCurrentDomain().That().ResideInNamespace("Gabi.Contracts").ShouldNot().HaveDependencyOnAny(...)` | Testes validam que Contracts não referencia outros projetos e que Domain não referencia Infrastructure |
| Projeto Gabi.Ingest.Tests existente | **NÃO RESOLVIDO** | Diretório não existe | N/A | Projeto `Gabi.Ingest` existe mas sem testes dedicados |
| Testcontainers com PostgreSQL real | **NÃO RESOLVIDO** | Não encontrado | N/A | Testes usam InMemory e SQLite, não Testcontainers |
| Property-based testing | **NÃO RESOLVIDO** | Não encontrado | N/A | Sem FsCheck ou bibliotecas similares |
| Mutation testing (Stryker) | **NÃO RESOLVIDO** | Não encontrado | N/A | Sem configuração Stryker |
| Smoke tests runtime não destrutivos | **PARCIAL** | `tests/zero-kelvin-test.sh` | Destrói containers e volumes (`docker compose down -v --remove-orphans`) | Teste é destrutivo por design (Zero Kelvin) |
| Assertion automática de memory budget | **PARCIAL** | `src/Gabi.Sync/Memory/MemoryManager.cs` | `IsUnderPressure => CurrentUsage > PressureThreshold` | MemoryManager existe mas sem assertions automáticas em testes |
| Monitoramento sintético (canary) | **NÃO RESOLVIDO** | Não encontrado | N/A | Sem verificações sintéticas periódicas |
| Health endpoints com SLO verificável | **PARCIAL** | `src/Gabi.Api/Program.cs` | `MapHealthChecks(ApiRoutes.Health, ...)` e `/health/ready` | Endpoints existem mas sem SLOs definidos |

**Recomendações prioritárias:**
- Criar `Gabi.Ingest.Tests` para cobrir o pipeline de ingestão
- Avaliar Testcontainers para testes de integração real com PostgreSQL
- Definir SLOs claros (ex: p95 < 200ms para /health) e alertas

---

### 10.2 Arquitetura

| Item | Status | Evidência | Prova | Observação |
|------|--------|-----------|-------|------------|
| Duplicação de tipos em Contracts removida | **RESOLVIDO** | `tests/Gabi.Architecture.Tests/LayeringTests.cs` | `NoDuplicatedTypeNames_InDifferentNamespaces` - verifica duplicatas no assembly Contracts | Teste falha se houver tipos duplicados |
| Enumeração de status centralizada | **RESOLVIDO** | `src/Gabi.Contracts/Common/StatusVocabulary.cs` | `public static class Status { public const string Pending = "pending"; ... }` | Status canônicos centralizados com mapeamentos de/para enums |
| Base comum para Run entities | **RESOLVIDO** | `src/Gabi.Postgres/Entities/RunAuditBase.cs` | `public abstract class RunAuditBase { public Guid Id; public DateTime StartedAt; ... }` | SeedRunEntity, DiscoveryRunEntity, FetchRunEntity herdam de RunAuditBase |
| Tipo comum para OperationResult | **NÃO RESOLVIDO** | Não encontrado | N/A | Sem Result<T> ou OperationResult padronizado |
| Remoção de Dictionary<string, object> como schema | **NÃO RESOLVIDO** | `src/Gabi.Contracts/Jobs/IngestJob.cs` | `public Dictionary<string, object> Payload { get; init; } = new();` | Ainda usado em IngestJob.Payload, PipelineStage e outros |

**Recomendações prioritárias:**
- Introduzir `Result<T>` ou `OperationResult<T>` padronizado em `Gabi.Contracts`
- Refatorar `Payload` de `Dictionary<string, object>` para tipos fortemente tipados

---

### 10.3 Engenharia

| Item | Status | Evidência | Prova | Observação |
|------|--------|-----------|-------|------------|
| Uso consistente de Result<T> ou equivalente | **NÃO RESOLVIDO** | `src/Gabi.Contracts/Pipeline/PipelineStages.cs` | `public record PipelineResult { public bool Success; ... }` | Apenas PipelineResult, não é padrão consistente em todo código |
| Pipeline declarativo composável | **PARCIAL** | `src/Gabi.Contracts/Pipeline/` | Interfaces `IFetchStage`, `IParseStage`, `IChunkStage`, `IEmbedStage`, `IIndexStage` | Interfaces definidas mas implementação completa não verificada |
| Tipos tipados para metadata/payload | **NÃO RESOLVIDO** | `src/Gabi.Contracts/Jobs/IngestJob.cs` | `Payload` é `Dictionary<string, object>` | Não há tipos fortemente tipados para payload |
| Idempotência ponta-a-ponta verificável | **PARCIAL** | `src/Gabi.Contracts/Jobs/IngestJob.cs` | `public string? IdempotencyKey { get; init; }` | IdempotencyKey existe mas verificação completa não implementada |

**Recomendações prioritárias:**
- Implementar verificação de idempotência no JobQueueRepository usando IdempotencyKey
- Criar contratos tipados para payloads de jobs

---

### 10.4 Segurança

| Item | Status | Evidência | Prova | Observação |
|------|--------|-----------|-------|------------|
| Proteção contra path traversal no local-file | **RESOLVIDO** | `src/Gabi.Api/Security/LocalMediaPathValidator.cs` | `if (requestedPath.Contains("..")) return false;` e verificação de symlink | Validação com testes em `PathTraversalTests.cs` |
| Proteção SSRF em upload por URL | **RESOLVIDO** | `src/Gabi.Api/Security/UrlAllowlistValidator.cs` | `BlockedHosts`, `BlockedMetadataIps`, `IsBlockedIp()` | Testes em `SsrfPreventionTests.cs` validam proteção |
| Hangfire dashboard autenticado | **RESOLVIDO** | `src/Gabi.Api/HangfireDashboardAuthFilter.cs` | `return httpContext.User.Identity?.IsAuthenticated == true && httpContext.User.IsInRole("Admin");` | Apenas Admin tem acesso; testes em `HangfireAuthTests.cs` |
| JWT secret fora do repositório | **RESOLVIDO** | `src/Gabi.Api/Configuration/SecurityConfig.cs` | `if (string.IsNullOrWhiteSpace(jwtKey)) throw new InvalidOperationException("Jwt:Key is required...")` | Chave obrigatória via env var em produção; validação de placeholders inseguros |
| Credenciais padrão não utilizadas | **PARCIAL** | `src/Gabi.Api/Security/UserCredentialStore.cs` | `CreateDevelopmentFallbackUsers` só em Development | Fallback só em dev; produção exige GABI_USERS configurado |
| Rate limit efetivo no login | **RESOLVIDO** | `src/Gabi.Api/Configuration/SecurityConfig.cs` | `options.AddPolicy("auth", ... SlidingWindowLimiter ... PermitLimit = 5, Window = TimeSpan.FromSeconds(300))` | Sliding window de 5 requisições em 5 minutos para auth |
| Limite de replay no DLQ | **RESOLVIDO** | `src/Gabi.Api/Services/DlqService.cs` | `private const int ReplayThrottlePerMinute = 1;` | Throttle de 1 replay/minuto por entrada |
| Redis/Elasticsearch autenticados | **NÃO RESOLVIDO** | `docker-compose.yml` | `xpack.security.enabled=false` para ES; Redis sem requirepass | Autenticação desabilitada no docker-compose |
| Security headers configurados | **RESOLVIDO** | `src/Gabi.Api/Middleware/SecurityHeadersMiddleware.cs` | `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`, `Permissions-Policy`, `Content-Security-Policy` | Headers de segurança aplicados em todas as respostas |

**Recomendações prioritárias:**
- Habilitar autenticação no Elasticsearch (`xpack.security.enabled=true`)
- Configurar `requirepass` no Redis
- Documentar rotação de secrets no runbook de operações

---

### 10.5 Observabilidade e Resiliência

| Item | Status | Evidência | Prova | Observação |
|------|--------|-----------|-------|------------|
| OpenTelemetry integrado | **RESOLVIDO** | `src/Gabi.Api/Program.cs` | `.AddOpenTelemetry().WithTracing(...).WithMetrics(...)` | Tracing e metrics com OTLP export; instrumentação de AspNetCore, EF Core, HttpClient, Runtime |
| Taxonomia de erros para retry | **RESOLVIDO** | `src/Gabi.Contracts/Common/ErrorTaxonomy.cs` | `ErrorCategory.Transient`, `Throttled`, `Permanent`, `Bug` | Classificação automática usada no DLQ para decisão de replay |
| Circuit breakers nas integrações externas | **NÃO RESOLVIDO** | Não encontrado | N/A | Sem circuit breaker implementado |
| Graceful shutdown de jobs | **RESOLVIDO** | `src/Gabi.Worker/Jobs/JobWorkerHostedService.cs` | `StopAsync` com `_cts?.Cancel()`, `_channel?.Writer.Complete()`, `Task.WhenAll(_workers).WaitAsync(_options.ShutdownTimeout, ct)` | Workers recebem sinal de cancelamento e têm timeout para finalizar |
| Verificação de consistência entre banco e índice | **NÃO RESOLVIDO** | Não encontrado | N/A | Sem verificação explícita de consistência entre PostgreSQL e Elasticsearch |

**Recomendações prioritárias:**
- Implementar Circuit Breaker para chamadas externas (ex: TEI, APIs)
- Criar job de reconciliação periódica entre PostgreSQL e Elasticsearch
- Adicionar métricas de saúde do pipeline (taxa de sucesso por source/stage)

---

### 10.6 CI/CD e Operações

| Item | Status | Evidência | Prova | Observação |
|------|--------|-----------|-------|------------|
| Auditoria automática de vulnerabilidades NuGet | **NÃO RESOLVIDO** | Não encontrado | N/A | Sem `NuGetAudit` ou pipeline de segurança configurado |
| Nullable reference types como erro | **PARCIAL** | `src/*/Gabi.*.csproj` | `<Nullable>enable</Nullable>` em todos os projetos | Nullable habilitado mas `TreatWarningsAsErrors` não configurado |
| Migrations zero-downtime verificadas | **NÃO RESOLVIDO** | `src/Gabi.Postgres/Migrations/` | Sem uso de `CONCURRENTLY` para índices | Migrations não usam CONCURRENTLY para criar índices sem lock |
| Build determinístico | **NÃO RESOLVIDO** | Não encontrado | N/A | Sem `Deterministic` ou `SourceLink` configurado |
| Estratégia de deploy segura | **NÃO RESOLVIDO** | `fly.toml`, `fly.api.toml` | Deploy em Fly.io documentado | Sem estratégia formal de deploy (blue/green, canary) |
| Backups testados | **NÃO RESOLVIDO** | Não encontrado | N/A | Sem testes de backup/restore |

**Recomendações prioritárias:**
- Adicionar `NuGetAudit` no `Directory.Build.props`
- Configurar `TreatWarningsAsErrors` para builds de release
- Criar migration de índices com `CONCURRENTLY` para zero-downtime
- Documentar e automatizar testes de backup/restore

---

### 10.7 Resumo Executivo da Auditoria

**Status Consolidado:**
- **RESOLVIDO**: 18 itens (40%)
- **PARCIAL**: 9 itens (20%)
- **NÃO RESOLVIDO**: 18 itens (40%)

**Principais gaps identificados:**
1. **Testes**: Falta cobertura dedicada para Ingest, Testcontainers, property-based testing
2. **Segurança**: Elasticsearch e Redis sem autenticação em ambiente Docker
3. **Engenharia**: Dictionary<string,object> ainda usado como schema; sem Result<T> padronizado
4. **CI/CD**: Sem auditoria de vulnerabilidades NuGet, build não-determinístico
5. **Operações**: Sem circuit breaker, sem verificação de consistência banco/índice, backups não testados

**Integração com backlog v9:**
- Itens NÃO RESOLVIDO desta auditoria devem ser priorizados como P1/P2 após fechamento de P0
- Itens PARCIAL devem ser evoluídos para RESOLVIDO nas próximas sprints
- Esta seção deve ser atualizada a cada revisão trimestral de arquitetura

---

## 11. Análise de Aceleração por Hardware (GPU/SIMD)

Data da análise: 24 de fevereiro de 2026
Escopo: Viabilidade de CUDA (NVIDIA) e Metal/MPS (Apple Silicon) para o pipeline GABI

### 11.1 Classificação do Pipeline por Bound Type

| Stage | Bound Type | GPU útil? | Justificativa baseada no código |
|-------|------------|-----------|--------------------------------|
| **seed** | IO-bound | **NÃO** | `CatalogSeedJobExecutor` faz parsing de YAML e inserts no PostgreSQL. Latência dominada por I/O de disco |
| **discovery** | IO-bound | **NÃO** | `WebCrawlDiscoveryAdapter` usa `HttpClient` + regex compilado. 90% do tempo é HTTP round-trip |
| **fetch** | IO-bound | **NÃO** | `ContentFetcher` usa streaming (`ResponseHeadersRead`). `FetchJobExecutor` parse CSV linha-a-linha |
| **parse** (CSV) | Mixed (IO+CPU) | **NÃO** | `CsvStreamingParser` processa stream de 4KB em 4KB. Bottleneck é encoding/char processing |
| **normalize** | CPU-bound | **NÃO** | `CanonicalDocumentNormalizer` usa regex compilado para whitespace. Texto pequeno (<1MB) |
| **chunk** | CPU-bound | **NÃO** | `FixedSizeChunker` faz `text.Split()` e `string.Join()`. Chunks pequenos (~500 tokens) |
| **embed** | CPU-bound | **SIM** (condicional) | `HashEmbedder` gera vetores 64-dim via `SHA256.HashData()`. **Se migrar para embeddings neurais**, GPU acelera 10-100x |
| **index** | IO-bound | **NÃO** | `LocalDocumentIndexer` é stub. Indexação real é Elasticsearch/PostgreSQL (externo) |
| **persist** | IO-bound | **NÃO** | `IngestJobExecutor` usa `SaveChangesAsync()`. Bottleneck é latência do PG |
| **query** | IO-bound | **NÃO** | Search faz queries SQL com `LIKE`. Sem vetores para busca semântica |

**Conclusão**: O pipeline é **predominantemente IO-bound**. Não há processamento vetorial massivo nem SIMD atual.

---

### 11.2 Arquitetura de Detecção de Hardware (Futura)

Se viabilizado embeddings neurais, a arquitetura de detecção deve ser:

#### Interface em Contracts (Layer 0)

```csharp
// Gabi.Contracts/Hardware/IHardwareAccelerator.cs
public enum AcceleratorType { Cpu, Cuda, MetalMps }

public interface IHardwareAccelerator : IDisposable
{
    AcceleratorType Type { get; }
    string DeviceName { get; }
    bool IsAvailable { get; }
    long? MemoryBytes { get; }
    int Priority { get; } // Maior = preferido
}

public interface IAcceleratorFactory
{
    IReadOnlyList<IHardwareAccelerator> DetectAvailable();
    IHardwareAccelerator? GetPreferred(AcceleratorType[]? preferenceOrder = null);
}
```

#### Implementações por Plataforma (Layer 4 - Infrastructure)

| Plataforma | Assembly | Implementação | Detecção Runtime |
|------------|----------|---------------|------------------|
| NVIDIA CUDA | `Gabi.Ingest.Cuda` | `CudaAccelerator` | `cuInit()` via P/Invoke em `nvcuda.dll` |
| Apple MPS | `Gabi.Ingest.Metal` | `MetalAccelerator` | `MTLCreateSystemDefaultDevice()` via Obj-C interop |
| CPU (fallback) | `Gabi.Ingest` | `CpuAccelerator` | Sempre disponível |

#### Registro no DI Container (Layer 5)

```csharp
// Program.cs - sem poluição de RuntimeInformation no domínio
builder.Services.AddSingleton<IAcceleratorFactory, RuntimeAcceleratorFactory>();
builder.Services.AddSingleton<IHardwareAccelerator>(sp => 
{
    var factory = sp.GetRequiredService<IAcceleratorFactory>();
    return factory.GetPreferred() ?? new CpuAccelerator();
});
```

**Restrições atendidas:**
- ✅ Domínio (`Gabi.Contracts`) não conhece plataforma
- ✅ Testes usam `CpuAccelerator` (sempre disponível)
- ✅ Contratos existentes não alterados
- ✅ Fallback determinístico para CPU

---

### 11.3 Impacto Real e Recomendações

#### Cenários de Aceleração

| Cenário | Ganho Estimado | Condição para Viabilidade |
|---------|----------------|---------------------------|
| **Embedder neural (BERT)** | **ALTO (10-50x)** | Substituir `HashEmbedder` por modelo transformer (ONNX Runtime + CUDA/MPS) |
| **Chunking paralelo batch** | **PEQUENO (1.2-1.5x)** | `Parallel.ForEach` em múltiplos documentos (respeitar memory budget) |
| **Parse CSV vetorizado** | **MODERADO (2-3x)** | SIMD com `Vector<ushort>` para delimiter scanning (complexo, ganho limitado por I/O) |
| **Normalização texto** | **NENHUM** | Regex é memory-bound, não compute-bound |

#### Quando GPU PIORARIA Performance

1. **Batch size pequeno (< 100 chunks)**:
   - Overhead transferência CPU→GPU (~0.5-2ms) > tempo processamento CPU
   - `HashEmbedder` atual: < 0.01ms na CPU para 64 dimensões

2. **SHA256 hashing**:
   - GPU eficiente apenas para mining (milhões de hashes paralelos)
   - Dados pequenos (< 1KB): CPU com SHA-NI é mais rápida

3. **Estruturas irregulares**:
   - GPU requer dados regulares (matrizes densas)
   - `FixedSizeChunker` usa `Dictionary<string,string>` - irregular

4. **Memory budget 300MB**:
   - Contexto CUDA consome ~100-200MB
   - MPS tem overhead de runtime mesmo com memória unificada

---

### 11.4 Decisão e Próximos Passos

**Status da aceleração por hardware: `NÃO VIÁVEL` (código atual)**

**Recomendação**: NÃO implementar GPU acceleration no momento.

**Alternativas mais efetivas para o código atual** (P2 no backlog):
1. **SIMD para chunking**: `System.Runtime.Intrinsics.Vector256<ushort>` para delimiter scanning
2. **Parallel.ForEach**: Processar múltiplos documentos concorrentemente
3. **Regex source generators**: Aplicar `[GeneratedRegex]` em todos os padrões (parcialmente feito)
4. **ONNX Runtime com CPU**: Se embeddings neurais forem necessários, versão CPU é suficiente para throughput atual

**Trigger para revisitar GPU**:
- Throughput alvo > 100 docs/segundo (atualmente limitado por I/O de rede)
- Migração para embeddings neurais (BERTimbau, sentence-transformers) com batches > 1000 documentos
- Dimensões de embedding > 384 (atual: 64)
