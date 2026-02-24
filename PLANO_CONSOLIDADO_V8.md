# Plano Consolidado v8 (Forensic Architecture Synthesis)

**Versão:** 1.0  
**Data Base:** 23 de fevereiro de 2026  
**Status:** Assessment Pós-Audit (V6/V7 Gap Analysis)  
**Fontes:** V6 Plan, V7 Plan, Codebase Forensics, Architecture Image

---

## 1. Resumo Executivo Forense

### Estado Real vs. Planejado (V6/V7)

| Dimensão | Declarado (V6) | Implementado | Gap Crítico |
|----------|---------------|--------------|-------------|
| **Pipeline E2E** | Seed→Discovery→Fetch→Ingest→Index | Seed→Discovery→Fetch→[VAZIO] | Ingest é shell; Index não existe |
| **Arquitetura em Camadas** | Strict Layer 4→0 | 3 violações de .csproj | Jobs, Sync, Ingest referenciam Postgres |
| **Observabilidade** | OTel + SLOs | OTel completo, sem SLOs | Dashboard funcional, sem alertas |
| **Search** | Lexical + Semantic + Reranker | Zero implementação | Primary use case não atendido |
| **AWS Independence** | Constraint mandatório | ✅ Confirmado | Zero dependências AWS |

### Veredito do Audit Cruzado

**O que ambos os audits confirmaram:**
1. `Gabi.Ingest/` contém apenas `.csproj` — zero arquivos `.cs`
2. `IngestJobExecutor` atualiza status em PostgreSQL mas não processa conteúdo (sem chunk/embed/index)
3. `IElasticIndexer`, `IChunker`, `IEmbedder` existem como interfaces sem implementações
4. Search endpoint não existe — dashboard retorna mocks "coming soon"
5. 3 projetos Layer-4 (`Gabi.Jobs`, `Gabi.Sync`, `Gabi.Ingest`) violam regra de referência a `Gabi.Postgres`
6. AWS independence confirmada — apenas comentário sobre S3/minio em `DocumentEntity`

**Onde o segundo audit exagerou:**
- "Pipeline hollow" / "cliff" — Fetch funciona e persiste dados em PostgreSQL
- "IngestJobExecutor has nothing to execute" — ele atualiza status e gerencia lifecycle de documentos
- "Layer violations block convergence" — violações são de referência .csproj, não uso direto de EF Core em código

**Onde o primeiro audit subestimou:**
- Não detectou que `Gabi.Ingest` é literalmente vazio (apenas shell de projeto)
- Não reportou uso de Dapper em `Gabi.Sync` (violação adicional)
- Classificou como "STUBBED" o que é "MISSING"

---

## 2. Modelo Alvo vs. Realidade

### 2.1 Visão de Arquitetura (da Imagem vs. Código)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ARQUITETURA ALVO (Imagem + V6/V7)                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │  API Gateway │───▶│  RAG Engine  │───▶│   Search     │                  │
│  │   (REST)     │    │  (Chunk+Embed│    │  (Lex+Sem)   │                  │
│  └──────────────┘    └──────┬───────┘    └──────────────┘                  │
│                             │                                               │
│         ┌───────────────────┼───────────────────┐                          │
│         ▼                   ▼                   ▼                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                     │
│  │  Vector DB  │    │  Graph DB   │    │ Elasticsearch│                    │
│  │  (Qdrant/   │    │   (Neo4j)   │    │  (Lexical)   │                    │
│  │   pgvector) │    │             │    │              │                    │
│  └─────────────┘    └─────────────┘    └─────────────┘                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                    REALIDADE IMPLEMENTADA (Código)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │  API (REST)  │───▶│   Dashboard  │───▶│   "Search"   │  ◀── Mock only   │
│  │  JWT+RateLim │    │   (Mocks)    │    │  (vazio)     │                  │
│  └──────────────┘    └──────────────┘    └──────────────┘                  │
│                                                                             │
│         ┌───────────────────┬───────────────────┐                          │
│         ▼                   ▼                   ▼                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                     │
│  │ PostgreSQL  │    │  Hangfire   │    │ Elasticsearch│  ◀── Conexão OK   │
│  │  (Dados)    │    │   (Jobs)    │    │  (Vazio)     │    Index: 0 docs  │
│  └─────────────┘    └─────────────┘    └─────────────┘                     │
│                                                                             │
│  GABI.INGEST/: [VAZIO] ──▶ Chunker? Embedder? Indexer? Não implementados    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Pipeline de Dados — Análise Forense

```yaml
Stage_1_Seed:
  Status: IMPLEMENTED
  Evidence: CatalogSeedJobExecutor.cs
  Functional: YES
  Data_Flow: sources_v2.yaml → source_registry table

Stage_2_Discovery:
  Status: IMPLEMENTED
  Evidence: 4 adapters (StaticUrl, UrlPattern, WebCrawl, ApiPagination)
  Functional: YES
  Data_Flow: URLs → discovered_links table
  Cap: Funciona (200 links/source testado)

Stage_3_Fetch:
  Status: IMPLEMENTED
  Evidence: FetchJobExecutor.cs (1000 linhas)
  Functional: YES
  Data_Flow: HTTP → fetch_items + documents tables
  Memory: 95 MiB pico (abaixo de 300MB)
  Streaming: YES (CSV row-by-row)

Stage_4_Ingest:
  Status: STRUCTURALLY_ABSENT
  Evidence: 
    - Gabi.Ingest/ contains: Gabi.Ingest.csproj ONLY
    - Zero .cs files in project
    - IngestJobExecutor (in Worker) updates DB status only
  Functional: NO
  Data_Flow: documents table (pending) → status updated → (no processing)
  Missing:
    - IDocumentParser implementations
    - IChunker implementations
    - IEmbedder implementations
    - IDocumentIndexer implementations

Stage_5_Index:
  Status: NOT_IMPLEMENTED
  Evidence:
    - IElasticIndexer interface exists (Contracts)
    - Zero implementations found in src/
    - DashboardService.cs:867 returns "coming soon"
    - DocumentEntity.ElasticsearchId column always null
  Functional: NO
  Data_Flow: N/A
```

---

## 3. Matriz de Gaps Consolidada

### 3.1 Gaps Funcionais (Bloqueantes para Produção)

| ID | Componente | V6 Ref | Status | Impacto | Esforço Est. |
|----|-----------|--------|--------|---------|--------------|
| F1 | **Document Parser** | P0.7 | ❌ MISSING | Conteúdo bruto → estruturado | 3-4 dias |
| F2 | **Chunking Service** | P1.3 | ❌ MISSING | Texto → segmentos para embeddings | 2-3 dias |
| F3 | **Embedding Service** | P1.3 | ❌ MISSING | Segmentos → vetores (OpenAI/local) | 2-3 dias |
| F4 | **ES Indexer** | P0.2 | ❌ MISSING | Vetores + texto → Elasticsearch | 2-3 dias |
| F5 | **Search API** | P0.2 | ❌ MISSING | Endpoint query + resultados | 3-4 dias |
| F6 | **Hybrid Search** | P1.3 | ❌ MISSING | Lexical + semantic + rerank | 4-5 dias |

**Cadeia de Dependência:**
```
F1 → F2 → F3 → F4 → F5 → F6
(Sem parser, não há chunks; sem chunks, não há embeddings; etc.)
```

### 3.2 Gaps de Infraestrutura/Arquitetura

| ID | Componente | V6 Ref | Status | Detalhe | Esforço |
|----|-----------|--------|--------|---------|---------|
| A1 | **Gabi.Ingest Project** | P0.7 | ❌ EMPTY | Criar implementações | 1 dia |
| A2 | **Layer Violation: Jobs→Postgres** | AGENTS.md | ⚠️ PARTIAL | .csproj ref sem uso em código | 4-8h |
| A3 | **Layer Violation: Sync→Postgres** | AGENTS.md | ⚠️ ACTIVE | Usa Gabi.Postgres.Entities | 1-2 dias |
| A4 | **Dapper in Sync** | AGENTS.md | ⚠️ ACTIVE | Raw SQL via Dapper | 1-2 dias |
| A5 | **NetArchTest Coverage** | P0.4 | ⚠️ PARTIAL | Não detecta .csproj refs | 2-4h |

### 3.3 Gaps de Qualidade (V6 Phase 3)

| ID | Item | V6 Ref | Status | Ocorrências | Esforço |
|----|------|--------|--------|-------------|---------|
| Q1 | **Result<T> Pattern** | P0.0 | ❌ MISSING | 4 padrões de erro coexistem | 3-4 dias |
| Q2 | **Typed Config** | P0.0b | ❌ MISSING | 15+ Dictionary<string,object> | 2-3 dias |
| Q3 | **Gabi.Ingest.Tests** | P0.7 | ❌ MISSING | Projeto sem código para testar | 2 dias |
| Q4 | **Smoke Tests** | P0.5 | ❌ MISSING | No tests/smoke-test.sh | 4-8h |
| Q5 | **Memory Budget CI** | P0.6 | ❌ MISSING | Sem assertion em CI | 2-4h |
| Q6 | **Testcontainers** | P1.7 | ❌ MISSING | Usa EF InMemory | 2 dias |

### 3.4 Gaps V7 (World-Class Excellence)

| ID | Item | V7 Ref | Status | Nota |
|----|------|--------|--------|------|
| W1 | **Polly Circuit Breaker** | R1 | ❌ MISSING | Apenas retry básico no Fetch |
| W2 | **Graceful Shutdown** | R2 | ⚠️ PARTIAL | IHostedService existe, não validado |
| W3 | **Idempotência E2E** | R3 | ❌ MISSING | Teste não existe |
| W4 | **SLO/SLI Dashboard** | O2 | ❌ MISSING | Métricas OTel sem SLOs |
| W5 | **Captive Dependency Check** | Q5 | ❌ MISSING | Não auditado |
| W6 | **Property-Based Tests** | P1.5 | ❌ MISSING | Sem FsCheck |
| W7 | **Contract Tests (YouTube/Senado)** | P1.6 | ⚠️ PARTIAL | Apenas LexML (falha) |

---

## 4. Análise de Riscos Consolidada

### 4.1 Risco Crítico: Pipeline Termina em Fetch

**Descrição:** Documentos são baixados e armazenados em PostgreSQL, mas nunca processados para busca.

**Evidência:**
```sql
-- PostgreSQL contém documentos com conteúdo
SELECT COUNT(*) FROM documents WHERE status = 'pending';
-- Retorna N documentos processados pelo Fetch

-- Elasticsearch está vazio
GET /documents/_count
-- Retorna 0
```

**Impacto:**
- Sistema coleta dados mas não entrega valor (busca)
- Dashboard mostra atividade mas sem resultado
- Usuário não consegue consultar documentos

**Mitigação:** Prioridade 1 — Implementar F1-F5 antes de qualquer feature V7.

### 4.2 Risco: Fachada de Funcionalidade

**Descrição:** IngestJobExecutor cria spans OTel (`pipeline.chunk`, `pipeline.embed`, `pipeline.index`) mas executa apenas atualização de status em PostgreSQL.

**Evidência:**
```csharp
// IngestJobExecutor.cs — spans criados
using var chunkActivity = PipelineTelemetry.ActivitySource.StartActivity("pipeline.chunk");
using var embedActivity = PipelineTelemetry.ActivitySource.StartActivity("pipeline.embed");
using var indexActivity = PipelineTelemetry.ActivitySource.StartActivity("pipeline.index");
// ... nenhum processamento real ocorre
```

**Impacto:**
- Observabilidade mostra atividade saudável
- Sistema "parece" funcionar em dashboards
- Falha real só detectada ao tentar buscar

**Mitigação:** Remover spans de stages não implementados ou implementar stages.

### 4.3 Risco: Violações de Camada Não Detectadas

**Descrição:** NetArchTest passa (3/3) mas 3 projetos violam regra de referência a Infrastructure.

**Evidência:**
```xml
<!-- Gabi.Jobs.csproj -->
<ProjectReference Include="..\Gabi.Postgres\Gabi.Postgres.csproj" />

<!-- Gabi.Sync.csproj -->
<ProjectReference Include="..\Gabi.Postgres\Gabi.Postgres.csproj" />
```

**Impacto:**
- Portabilidade reduzida (mudar storage exige alterar domain)
- Testabilidade reduzida (não pode mockar facilmente)
- Acoplamento inadvertido pode crescer

**Mitigação:** Priority 2 — Refatorar para usar interfaces de Contracts.

---

## 5. Roadmap V8: Próximos Passos Priorizados

### Fase 1: Pipeline Core (Semanas 1-3) — CRÍTICO
**Objetivo:** Documentos fluem até Elasticsearch e são pesquisáveis.

| Semana | Tarefa | Entregável | Sucesso |
|--------|--------|-----------|---------|
| 1.1 | Implementar Document Parsers | `Gabi.Ingest/Parsers/` | CSV, JSON, PDF parsers funcionais |
| 1.2 | Implementar Chunking Service | `Gabi.Ingest/Chunker.cs` | Texto segmentado por tamanho/overlap |
| 1.3 | Implementar ES Indexer | `Gabi.Ingest/ElasticIndexer.cs` | Documentos indexados em ES |
| 2.1 | Integrar IngestJobExecutor | Wire F1-F3 no executor | Pipeline E2E funciona |
| 2.2 | Implementar Search Endpoint | `POST /api/v1/search` | Query básica retorna resultados |
| 2.3 | Validação E2E | Zero-kelvin com index | Docs aparecem no ES |
| 3.1 | Implementar Embedding Service | Integração OpenAI/TEI | Vetores gerados e indexados |
| 3.2 | Busca Híbrida V1 | Lexical + básico | Resultados ordenados por relevance |

**Gate de Saída Fase 1:**
- [ ] `zero-kelvin-test.sh --source tcu_sumulas --phase full` indexa documentos no ES
- [ ] `GET /api/v1/search?q=teste` retorna resultados reais
- [ ] Zero mocks em dashboard para ES

### Fase 2: Arquitetura & Qualidade (Semanas 4-5)
**Objetivo:** Eliminar dívidas técnicas que dificultam manutenção.

| Semana | Tarefa | Entregável |
|--------|--------|-----------|
| 4.1 | Remover refs Postgres de Jobs/Sync | DI via Contracts apenas |
| 4.2 | Adotar Result<T> | ErrorOr em fluxos críticos |
| 4.3 | Typed Config | Replace Dictionary<string,object> |
| 5.1 | Gabi.Ingest.Tests | Cobertura 80%+ |
| 5.2 | Smoke Tests | tests/smoke-test.sh funcional |
| 5.3 | Memory Budget CI | Assertion em zero-kelvin |

### Fase 3: Resiliência & Produção (Semanas 6-7)
**Objetivo:** Sistema tolera falhas e é observável em produção.

| Semana | Tarefa | Entregável |
|--------|--------|-----------|
| 6.1 | Circuit Breakers | Polly CB para ES, YouTube, OpenAI |
| 6.2 | SLO Dashboard | Grafana + alertas básicos |
| 6.3 | Graceful Shutdown | Validação SIGTERM |
| 7.1 | DLQ Recovery Tests | Teste DLQ→Replay→Sucesso |
| 7.2 | Idempotência E2E | Teste re-execução sem duplicatas |

### Fase 4: Inteligência Normativa (Semanas 8-10) — V6 P1
**Objetivo:** Diferenciais competitivos do V6.

| Semana | Tarefa | Entregável |
|--------|--------|-----------|
| 8.1 | Normative Events Engine | Tabela + parser Senado |
| 8.2 | Temporal Engine | API status-at-date |
| 9.1 | Multi-Source Consolidation | Merge Planalto/Senado/LexML |
| 9.2 | Reranker Integration | Cross-encoder para resultados |
| 10.1 | Testcontainers | PostgreSQL real em testes |
| 10.2 | Contract Tests | YouTube + Senado schemas |

### Fase 5: Excelência V7 (Semanas 11-12)
**Objetivo:** World-class engineering (após V6 100%).

- Property-based tests (FsCheck)
- Chaos engineering (kill containers)
- Performance profiling (BenchmarkDotNet)
- Supply chain security (SBOM, signing)

---

## 6. Métricas de Conclusão V8

| Fase | Itens | Pesos | Meta |
|------|-------|-------|------|
| F1: Pipeline Core | 8 | 40% | 100% para produção |
| F2: Arquitetura | 6 | 20% | 100% para manutenibilidade |
| F3: Resiliência | 6 | 20% | 80% para produção |
| F4: Inteligência | 6 | 15% | 60% para MVP diferenciado |
| F5: Excelência | 5 | 5% | 40% para V7 iniciar |

**Overall V8 Target:** Pipeline funcional + Search operacional + Arquitetura limpa = **60% completo** (produção mínima)

---

## 7. Checklist de Decisões Pendentes

Antes de iniciar Fase 1, decidir:

- [ ] **Embedding Strategy:** OpenAI API (custo) vs. TEI local (infra)?
- [ ] **Vector Storage:** Elasticsearch dense_vector (simples) vs. pgvector (unificado) vs. Qdrant (performance)?
- [ ] **PDF Parsing:** Biblioteca nativa (iText/PdfPig) vs. serviço externo?
- [ ] **Reranker:** Cohere API vs. modelo local (sentence-transformers)?

---

## 8. Anexos

### Anexo A: Evidence Files
- `src/Gabi.Ingest/` — Empty directory (only .csproj)
- `src/Gabi.Worker/Jobs/IngestJobExecutor.cs` — Status updater only
- `src/Gabi.Contracts/Index/IDocumentIndexer.cs` — Interface, no implementations
- `tests/Gabi.Architecture.Tests/LayeringTests.cs` — Passes but doesn't catch .csproj refs

### Anexo B: AWS Independence Confirmation
```bash
# No AWSSDK packages found
grep -r "AWSSDK\|Amazon\." src/**/*.csproj || echo "No AWS deps"
# Result: No AWS deps
```

### Anexo C: Pipeline Memory Validation
```bash
# Zero-kelvin test evidence (V6 A.1)
./tests/zero-kelvin-test.sh --source tcu_sumulas --phase full
# Result: 94.87 MiB peak << 300MB budget
```

---

*Documento consolidado a partir de dual-audit forense e análise de codebase.*  
*Última atualização: 2026-02-23*  
*Status: Pronto para planejamento Fase 1*
