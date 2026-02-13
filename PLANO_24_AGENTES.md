# Plano de Execução: 26 Agentes - Pipeline Completo GABI

## 🎯 Visão Geral

**Objetivo**: Implementar pipeline completo do Zero Kelvin até Hash + Crawler  
**Estratégia**: Fase 0 (Design) → Caminho C (Arquitetura) → Caminho A (Estruturadas) → Caminho B (Crawler)  
**Total de Agentes**: 26 (incluindo Fase 0 de Design)  
**Timeline Estimada**: 4 semanas  
**Nota**: O PipelineOrchestrator já existe em `Gabi.Sync/Pipeline/PipelineOrchestrator.cs` e será extraído para `Gabi.Pipeline`

---

## 📜 Regras Transversais

### TDD (Test-Driven Development)
- **Regra**: Nenhum código de produção sem um teste que falhou antes
- **Ciclo**: Red → Green → Refactor
- **Cobertura**: Mínimo 60% (meta: 80%)

### Zero Kelvin
- Critério de aceitação global de cada sprint
- Após cada sprint: `docker compose down -v`, `./scripts/setup.sh`, `./scripts/dev app start`
- Script `tests/zero-kelvin-test.sh` como gate obrigatório

### Data Governance
- Tabelas com `created_at`/`updated_at`
- Soft delete: `removed_from_source_at` (nunca hard delete)
- Unicidade: `(ContentHash, SourceId)`
- Audit trail para dados sensíveis (LGPD)

---

## 📋 Resumo por Sprint

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ SPRINT 0: Design da Sincronização - 1 documento - 2-3 dias                   │
│ SPRINT 1: Arquitetura (Caminho C) - 6 Agentes (C1-C6) - 1 semana             │
│ SPRINT 2: Estruturadas (Caminho A) - 9 Agentes (A1-A9) - 1 semana            │
│ SPRINT 3: Crawler (Caminho B) - 8 Agentes (B1-B8) - 1 semana                 │
│ SPRINT 4: Integração - 2 Agentes (I1-I2) - 3 dias                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🎨 SPRINT 0: Fase 0 - Design da Sincronização (Snapshot + Diff + Reconcile)

**Objetivo**: Definir arquitetura de sincronização profissional antes de implementar.

### Entregáveis:
- [ ] `docs/plans/YYYY-MM-DD-sync-reconciliation-design.md`
- [ ] Definição de identificador estável por fonte (Natural Key)
- [ ] Estratégia de snapshot para cada tipo de fonte:
  - CSV: extrair lista de (id, url, metadados) do arquivo
  - API: paginar e extrair IDs
  - Crawler: extrair URLs canônicas
- [ ] Especificação da fase de Reconcile:
  - Na fonte e não na base → INSERT
  - Na fonte e na base → UPDATE (se hash mudou)
  - Na base e não na fonte → SOFT DELETE (removed_from_source_at)
- [ ] Schema de soft delete (campo removed_from_source_at)
- [ ] Métricas de sync (added/updated/removed/unchanged)
- [ ] Estratégia full vs incremental por fonte

**Gate**: Documento aprovado e revisado

---

## 🏗️ SPRINT 1: Caminho C - Arquitetura (Foundation)

### Objetivo
Criar a base arquitetural para jobs hierárquicos e orquestração de pipeline.

### Agente C1: Gabi.Jobs Setup
**Tarefa**: Criar projeto Gabi.Jobs + estrutura base
**Entregáveis**:
- `src/Gabi.Jobs/Gabi.Jobs.csproj`
- `IJobFactory.cs` - Interface central de criação
- `IJobCreator.cs` - Interface base para criadores
- `IJobStateMachine.cs` - Interface da máquina de estados
- Referências em `GabiSync.sln`
**Dependências**: Fase 0 (design aprovado)
**Teste**: `dotnet build` passa

---

### Agente C2: SourceJobCreator
**Tarefa**: Implementar criador de jobs por source
**Entregáveis**:
- `SourceJobCreator.cs` - Cria job pai para uma source
- Método: `CreateSourceJobAsync(string sourceId, DiscoveryResult result)`
- Configuração de prioridade baseada em source
- Payload JSON com metadados da source
**Dependências**: C1
**Teste**: Criar job para tcu_sumulas retorna JobId válido

---

### Agente C3: DocumentJobCreator
**Tarefa**: Implementar criador de jobs por documento
**Entregáveis**:
- `DocumentJobCreator.cs` - Cria jobs filhos por documento
- Método: `CreateDocumentJobsAsync(Guid parentJobId, IEnumerable<DocumentInfo> docs)`
- Suporte a batch creation (evitar N+1)
- Herança de prioridade do job pai
**Dependências**: C1, C2
**Teste**: Criar 1000 jobs filhos em < 1 segundo

---

### Agente C4: JobStateMachine
**Tarefa**: Implementar máquina de estados de jobs
**Entregáveis**:
- `JobStateMachine.cs` - Gerencia transições de estado
- Estados: `Pending → Running → (Completed | Failed | Skipped)`
- Eventos: `OnTransition`, `OnCompleted`, `OnFailed`
- Validação de transições (não pode ir de Completed para Running)
- Persistência de estado no PostgreSQL
**Dependências**: C1
**Teste**: Todas as transições válidas/inválidas testadas

---

### Agente C5: Specialized Workers
**Tarefa**: Criar workers especializados por tipo
**Entregáveis**:
- `DiscoveryWorker.cs` - Processa jobs do tipo "discover"
- `FetchWorker.cs` - Processa jobs do tipo "fetch"
- `HashWorker.cs` - Processa jobs do tipo "hash"
- `WorkerRegistry.cs` - Roteia jobs para workers
**Dependências**: C1, C4
**Teste**: Cada worker processa job do seu tipo

---

### Agente C6: Gabi.Pipeline Setup + PhaseCoordinator + Resilience + Schema
**Tarefa**: Extrair PipelineOrchestrator de Gabi.Sync para Gabi.Pipeline + implementar coordenação, resiliência e schema
**Entregáveis**:
- `src/Gabi.Pipeline/Gabi.Pipeline.csproj`
- `PipelineOrchestrator.cs` - Coordena todas as fases (extrair de `Gabi.Sync/Pipeline/PipelineOrchestrator.cs`)
- `IPhaseCoordinator.cs` - Interface para coordenadores de fase
- `PhaseCoordinator.cs` - Executa fases em ordem
- `CircuitBreaker.cs` - Abre circuito após N falhas
- `RetryPolicy.cs` - Backoff exponencial com jitter
- Migration: `AddJobHierarchy.cs` com campos: `ParentJobId`, `DocumentId`, `ContentHash`, `IsDuplicate`
- Migration: `AddSoftDeleteAndNaturalKey.cs` com campos: `ExternalId`, `RemovedFromSourceAt`, `RemovedReason`
- Índices: `idx_jobs_parent`, `idx_jobs_document`, `idx_jobs_hash`
- Índice: `idx_documents_removed` (para queries eficientes)
- Índice único: `(SourceId, ExternalId)`
- Atualizar `IngestJobEntity` e `DocumentEntity`
- Configuração por source (sources.yaml)
**Dependências**: C1, C2, C3
**Testes**: 
- Orquestrador inicializa sem erros
- Circuit breaker abre após 5 falhas consecutivas
- Migration aplica sem erros

---

## 📦 SPRINT 2: Caminho A - Fontes Estruturadas (CSV)

### Objetivo
Implementar fetch, hash e parse para fontes CSV do TCU.

### Agente A1: Gabi.Fetch Setup
**Tarefa**: Criar projeto Gabi.Fetch + ContentFetcher
**Entregáveis**:
- `src/Gabi.Fetch/Gabi.Fetch.csproj`
- `IContentFetcher.cs` - Interface principal
- `ContentFetcher.cs` - Implementação HTTP
- Streaming HTTP (não carregar arquivo inteiro em memória)
**Dependências**: C1
**Teste**: Fetch de URL retorna stream não-nulo

---

### Agente A2: DocumentCounter
**Tarefa**: Implementar contador de documentos
**Entregáveis**:
- `IDocumentCounter.cs` - Interface
- `CsvDocumentCounter.cs` - Conta linhas em CSV
- Suporte a header row
- Progress reporting (eventos)
- Método: `CountAsync(Stream content, ParseConfig config)`
**Dependências**: A1
**Teste**: Contar linhas em CSV de 100MB em < 5s

---

### Agente A3: MetadataExtractor
**Tarefa**: Extrair metadados de fontes
**Entregáveis**:
- `IMetadataExtractor.cs` - Interface
- `HttpMetadataExtractor.cs` - Extrai de headers HTTP
- `CsvMetadataExtractor.cs` - Extrai de colunas CSV
- Campos: title, date, url, external_id
- Normalização de datas para ISO 8601
**Dependências**: A1
**Teste**: Extrair metadata de tcu_sumulas.csv

---

### Agente A4: Gabi.Hash Setup
**Tarefa**: Criar projeto Gabi.Hash + ContentHasher
**Entregáveis**:
- `src/Gabi.Hash/Gabi.Hash.csproj`
- `IContentHasher.cs` - Interface
- `ContentHasher.cs` - SHA-256 determinístico
- Normalização: whitespace, encoding (UTF-8)
- Fallback: hash de (url + date + title) se conteúdo vazio
**Dependências**: C1
**Teste**: Mesmo conteúdo = mesmo hash

---

### Agente A5: DeduplicationService
**Tarefa**: Implementar serviço de deduplicação
**Entregáveis**:
- `IDeduplicationService.cs` - Interface
- `DeduplicationService.cs` - Verifica duplicatas
- `DuplicateCheckResult.cs` - Resultado da verificação
- Consulta eficiente por hash (índice)
- Registra referência ao documento original
**Dependências**: A4, C8
**Teste**: Detectar duplicata em < 10ms

---

### Agente A6: CSV Streaming Parser
**Tarefa**: Implementar parser CSV com streaming
**Entregáveis**:
- `ICsvParser.cs` - Interface
- `StreamingCsvParser.cs` - Parser de linha em linha
- Suporte a: delimiter, quote, escape, encoding
- Transformers: strip_quotes, parse_int, parse_date
- Evento `OnRowParsed` para processamento em tempo real
**Dependências**: A1
**Teste**: Parse de CSV 500MB com < 100MB memória

---

### Agente A7: Pipeline Wiring (Fetch → Hash → Parse)
**Tarefa**: Conectar fases no orquestrador
**Entregáveis**:
- `FetchPhase.cs` - Coordena fase de fetch
- `HashPhase.cs` - Coordena fase de hash
- `ParsePhase.cs` - Coordena fase de parse
- Transição automática: fetch completo → cria jobs de hash
- Transição: hash completo → cria jobs de parse
**Dependências**: C6, A1, A4, A6
**Teste**: Pipeline tcu_sumulas executa sem erros

---

### Agente A8: CSV Sources Configuration
**Tarefa**: Configurar fontes CSV no pipeline
**Entregáveis**:
- Mapeamento de todas as fontes CSV (tcu_acordaos, tcu_normas, etc.)
- Configuração de estratégias por fonte
- Testes de integração para cada fonte
- Documentação de tempos esperados
**Dependências**: A7
**Teste**: tcu_sumulas completo em < 5 minutos

---

### Agente A9: Reconcile Service (Snapshot + Diff + Reconcile)
**Tarefa**: Implementar fase de reconciliação
**Entregáveis**:
- `IReconcileService.cs` - Interface
- `ReconcileService.cs` - Implementação do padrão Snapshot + Diff + Reconcile
- Métodos: `ReconcileAsync(string sourceId, Snapshot snapshot)`
- Lógica:
  - INSERT: documentos na fonte mas não na base
  - UPDATE: documentos com hash diferente
  - SOFT DELETE: documentos na base mas não na fonte (set removed_from_source_at)
- Métricas: added_count, updated_count, removed_count, unchanged_count
**Dependências**: A4 (Hash), A5 (Deduplication), C6 (Schema)
**Teste**: Reconcile de fonte com 1000 docs retorna métricas corretas

---

## 🕷️ SPRINT 3: Caminho B - Fontes Não-Estruturadas (Crawler)

### Objetivo
Implementar crawler para PDFs e APIs.

### Agente B1: Gabi.Crawler Setup
**Tarefa**: Criar projeto Gabi.Crawler + WebCrawler
**Entregáveis**:
- `src/Gabi.Crawler/Gabi.Crawler.csproj`
- `IWebCrawler.cs` - Interface
- `WebCrawler.cs` - Implementação base
- Fila de URLs (queue) - breadth-first
- Suporte a cookies e sessões
**Dependências**: C1
**Teste**: Crawl de site simples retorna URLs

---

### Agente B2: LinkExtractor
**Tarefa**: Extrair links de HTML
**Entregáveis**:
- `ILinkExtractor.cs` - Interface
- `CssLinkExtractor.cs` - Usa AngleSharp/CsQuery
- Suporte a seletores CSS configuráveis
- Filtros: include_patterns, exclude_patterns
- Extração de: href, text, contexto
**Dependências**: B1
**Teste**: Extrair links de página do TCU

---

### Agente B3: PDF Downloader
**Tarefa**: Download e parsing de PDFs
**Entregáveis**:
- `IPdfDownloader.cs` - Interface
- `PdfDownloader.cs` - Download com streaming
- `IPdfParser.cs` - Interface
- `BasicPdfParser.cs` - Extrai texto e metadata
- Armazenamento temporário em `/tmp/gabi-pdfs/`
**Dependências**: B1
**Teste**: Download e parse de PDF do TCU

---

### Agente B4: PolitenessPolicy
**Tarefa**: Implementar política de gentileza
**Entregáveis**:
- `IPolitenessPolicy.cs` - Interface
- `RobotsTxtParser.cs` - Parse de robots.txt
- `RateLimiter.cs` - Controle de requisições/segundo
- `CrawlDelayer.cs` - Delay entre requisições
- User-Agent configurável
**Dependências**: B1
**Teste**: Respeita robots.txt do portal.tcu.gov.br

---

### Agente B5: TCU Publications Crawler
**Tarefa**: Crawler específico para publicações TCU
**Entregáveis**:
- `TcuPublicationsCrawler.cs` - Implementação específica
- Configuração para `tcu_publicacoes` (sources.yaml)
- Navegação de paginação
- Extração de links PDF
- Download e enfileiramento para processamento
**Dependências**: B1, B2, B3, B4
**Teste**: Descobrir 10+ PDFs em execução

---

### Agente B6: TCU Technical Notes Crawler
**Tarefa**: Crawler para notas técnicas SEFTI
**Entregáveis**:
- `TcuTechnicalNotesCrawler.cs` - Implementação específica
- Configuração para `tcu_notas_tecnicas_ti`
- Adaptação para estrutura do site SEFTI
- Extração de metadados específicos
**Dependências**: B5
**Teste**: Descobrir 5+ notas técnicas

---

### Agente B7: Câmara API Adapter
**Tarefa**: Adapter para API da Câmara dos Deputados
**Entregáveis**:
- `CamaraApiAdapter.cs` - Adapter específico
- Configuração para `camara_leis_ordinarias`
- Paginação de API (page/per_page)
- Transformação de resposta JSON para DiscoveredLink
- Rate limiting específico para API
**Dependências**: C1
**Teste**: Descobrir leis de 2024

---

### Agente B8: DiscoveryEngine Expansion
**Tarefa**: Expandir DiscoveryEngine com novas strategies
**Entregáveis**:
- `WebCrawlStrategy.cs` - Strategy para web_crawl
- `ApiPaginationStrategy.cs` - Strategy para api_pagination
- Integração com Gabi.Crawler
- Registro automático de crawlers por source
**Dependências**: B1, B7
**Teste**: tcu_publicacoes descobre links

---

## 🔌 SPRINT 4: Integração & Testing

### Objetivo
Integrar tudo e validar com Teste Zero Kelvin.

### Agente I1: API Endpoints
**Tarefa**: Criar endpoints de controle do pipeline
**Entregáveis**:
- `POST /api/v1/pipeline/run` - Iniciar pipeline
- `GET /api/v1/pipeline/status/{jobId}` - Status
- `POST /api/v1/pipeline/cancel/{jobId}` - Cancelar
- `GET /api/v1/sources/{id}/documents` - Documentos
- `GET /api/v1/documents/{id}/hash` - Fingerprint
- Documentação Swagger
**Dependências**: Todas as anteriores
**Teste**: Todos endpoints retornam 200 OK

---

### Agente I2: Zero Kelvin Testing
**Tarefa**: Testar pipeline completo do zero
**Entregáveis**:
- Script `tests/zero-kelvin-test.sh`
- Teste para tcu_sumulas (fonte pequena)
- Teste para tcu_acordaos (fonte grande)
- Validação de idempotência
- Métricas de throughput
- Relatório de resultados
**Dependências**: Todas as anteriores
**Teste**: `./scripts/zero-kelvin-test.sh` passa

---

## 📊 Coordenação entre Agentes

### Dependências Críticas

```
Fase 0 (Design) → Todos
C1 (Setup) → C2, C3, C4, C5
C4 (StateMachine) → C5 (Workers)
C6 (Orchestrator) → C2, C3

A1 (Fetch Setup) → A2, A3, A6
A4 (Hash) → A5 (Deduplication)
A5 (Deduplication) → A9 (Reconcile)
A7 (Wiring) → A1, A4, A6, C6
A9 (Reconcile) → A8 (CSV Config)

B1 (Crawler Setup) → B2, B3, B4
B5 (TCU Crawler) → B1, B2, B3, B4
B7 (Camara API) → B1
B8 (Discovery Expansion) → B1, B7

I1 (API) → Todas
I2 (Testing) → Todas
```

### Comunicação entre Agentes

1. **Contratos primeiro**: Agentes de interface definem contratos antes da implementação
2. **Schema migrations**: Agente C8 faz migration antes dos outros precisarem dos campos
3. **Integração contínua**: A cada PR, verificar se build passa
4. **Testes de contrato**: Usar testes de integração para validar interfaces

---

## 🎯 Critérios de Aceitação por Agente

### Cada agente deve entregar:

1. **Código compilando**:
   ```bash
   dotnet build src/Gabi.{Modulo}/Gabi.{Modulo}.csproj
   ```

2. **Testes unitários** (mínimo 60% cobertura, meta: 80%):
   ```bash
   dotnet test tests/Gabi.{Modulo}.Tests/
   ```

3. **Documentação**:
   - XML docs em interfaces públicas
   - README.md no módulo (se novo)

4. **Integração**:
   - Referência em `GabiSync.sln`
   - DI registrado em `Program.cs` (se aplicável)

---

## 📈 Métricas de Sucesso do Projeto

| Métrica | Sprint 1 | Sprint 2 | Sprint 3 | Sprint 4 |
|---------|----------|----------|----------|----------|
| Fontes ativas | 8 | 8 | 11 | 11 |
| Jobs/segundo | - | 100+ | 100+ | 100+ |
| Crawler success | - | - | 95% | 95% |
| Hash collision | - | <0.01% | <0.01% | <0.01% |
| Zero Kelvin | - | - | - | ✅ PASS |

---

## 🚀 Comandos para Iniciar

```bash
# Preparação (Agente C1)
dotnet new classlib -n Gabi.Jobs -o src/Gabi.Jobs
dotnet sln add src/Gabi.Jobs/Gabi.Jobs.csproj

# Cada agente após código pronto
dotnet build
dotnet test

# Antes de merge
dotnet format --verify-no-changes
```

---

## 📚 Recursos

- `PIPELINE_COMPLETO_ROADMAP.md` - Detalhamento técnico
- `sources_v2.yaml` - Configuração das fontes
- `day_sprint.md` - Checklist de tarefas
- `README.md` - Teste Zero Kelvin

---

**Nota para Agentes**: Leiam o `PIPELINE_COMPLETO_ROADMAP.md` antes de começar para entender o contexto completo.
