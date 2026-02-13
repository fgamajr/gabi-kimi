# 📊 Status Geral do Projeto GABI

**Data**: 2026-02-12  
**Fase Atual**: Fase 3 COMPLETA → Iniciando Fase 4 (Pipeline Completo)

---

### 🎨 FASE 0: Design da Sincronização (NOVA)
**Objetivo**: Definir arquitetura Snapshot + Diff + Reconcile
**Entregáveis**:
- Documento em `docs/plans/`
- Identificador estável (Natural Key)
- Estratégia de soft delete
- Métricas de sync

---

## ✅ O que Já Fizemos

### Fase 1: Foundation (Semana 1) ✅
- .NET 8 SDK instalado
- 6 projetos criados e compilando
- Contratos definidos (21 arquivos)
- Clean Architecture implementada

### Fase 2: Docker + Discovery (Semana 2) ✅
- PostgreSQL 15 + Elasticsearch 8 + Redis 7
- DiscoveryEngine com StaticUrl e UrlPattern
- 37 URLs descobertas (tcu_acordaos: 35 anos, tcu_normas: 1, tcu_sumulas: 1)

### Fase 3: Dashboard + Security (Semana 3) ✅ COMPLETA!

#### Dashboard API
- ✅ SourceDetailsResponse com estatísticas
- ✅ DiscoveredLinkDetailDto com pipeline status
- ✅ LinkListResponse paginado
- ✅ Endpoints: /dashboard/stats, /jobs, /pipeline
- ✅ Endpoints: /sources/{id}/links, /sources/{id}/links/{linkId}

#### Security Stack
- ✅ JWT Bearer Auth (login em /api/v1/auth/login)
- ✅ RBAC: Admin, Operator, Viewer
- ✅ Rate Limiting: 100/min read, 10/min write
- ✅ Security Headers: HSTS, X-Content-Type-Options, etc.
- ✅ Global Exception Handler
- ✅ CORS configurado

#### Frontend
- ✅ PipelineOverview (5 estágios)
- ✅ SourcesTable com ações
- ✅ LinkDetailsModal
- ✅ JobsPanel com progresso

---

## 🎯 O que Vamos Fazer Agora (Fase 4)

### Pipeline Completo: Zero Kelvin → Discovery → Fetch → Jobs → Hash → Crawler

**Estratégia**: Caminho C → A → B

```
Caminho C (Arquitetura): Fundação para jobs hierárquicos
    ↓
Caminho A (Estruturadas): Fetch + Hash + Parse para CSVs
    ↓
Caminho B (Crawler): Web crawler + API adapters
```

### Módulos a Criar

| Módulo | Para | Status |
|--------|------|--------|
| Gabi.Jobs | Jobs hierárquicos (pai/filho) | 🔴 Novo |
| Gabi.Pipeline | Orquestração de fases | 🔴 Novo |
| Gabi.Fetch | Content fetching | 🔴 Novo |
| Gabi.Hash | SHA-256 + deduplicação | 🔴 Novo |
| Gabi.Crawler | Web crawling | 🔴 Novo |

### Fontes Alvo

| Fonte | Tipo | Discovery | Pipeline Completo |
|-------|------|-----------|-------------------|
| tcu_acordaos | CSV Pattern | ✅ | 🎯 Sprint 2 |
| tcu_normas | CSV Static | ✅ | 🎯 Sprint 2 |
| tcu_sumulas | CSV Static | ✅ | 🎯 Sprint 2 |
| tcu_publicacoes | PDF Crawler | 🔴 | 🎯 Sprint 3 |
| camara_leis | API Pagination | 🔴 | 🎯 Sprint 3 |

---

## 📋 Plano de 24 Agentes

### Sprint 1: Arquitetura (7 agentes) - 1 semana
- C1: Gabi.Jobs Setup
- C2: SourceJobCreator
- C3: DocumentJobCreator
- C4: JobStateMachine
- C5: Specialized Workers
- C6: Pipeline Orchestrator + Resilience + Schema
- C7: PhaseCoordinator + Resilience + Schema

**Nota**: O PipelineOrchestrator já existe em `Gabi.Sync/Pipeline/PipelineOrchestrator.cs` e será extraído para `Gabi.Pipeline`

### Sprint 2: Estruturadas (9 agentes) - 1 semana
- A1: Gabi.Fetch Setup
- A2: DocumentCounter
- A3: MetadataExtractor
- A4: Hash Module
- A5: Deduplication Service
- A6: CSV Streaming Parser
- A7: Pipeline Wiring
- A8: CSV Sources Configuration
- **A9: Reconcile Service** (Snapshot + Diff + Reconcile)

### Sprint 3: Crawler (8 agentes) - 1 semana
- B1: Gabi.Crawler Setup
- B2: LinkExtractor
- B3: PDF Downloader
- B4: PolitenessPolicy
- B5: TcuPublicationsCrawler
- B6: TcuTechnicalNotesCrawler
- B7: CamaraApiAdapter
- B8: DiscoveryEngine Expansion

### Sprint 4: Integração (2 agentes) - 3 dias
- I1: API Endpoints
- I2: Zero Kelvin Testing

**Total: 26 agentes/documentos** (Fase 0 + 25 agentes de implementação)

---

## 📁 Documentação Criada/Atualizada

| Arquivo | O que foi feito |
|---------|-----------------|
| `roadmap.md` | ✅ Adicionada Fase 3 (Dashboard+Security) e Fase 4 (Pipeline Completo) |
| `day_sprint.md` | ✅ Marcado o que já fizemos, adicionado Pipeline Completo |
| `PLANO_24_AGENTES.md` | ✅ Novo - detalhamento de cada agente |
| `PIPELINE_COMPLETO_ROADMAP.md` | ✅ Já existia - arquitetura detalhada |
| `README.md` | ✅ Teste Zero Kelvin + Idempotência |

---

## 🚀 Próximo Passo Imediato

**Decisão**: Usar 24 agentes simultâneos?

**Opções**:
1. **Sim, 24 agentes** - Sprint 1 começa agora (C1-C8)
2. **Não, começar menor** - Apenas C1-C4 (fundamentos)
3. **Validar primeiro** - Fazer POC de um fluxo end-to-end simples

**Recomendação**: Opção 1 (24 agentes) porque:
- As dependências estão bem mapeadas
- Os contratos já existem (Gabi.Contracts)
- A arquitetura está estabilizada
- Podemos paralelizar muito trabalho

---

## 📊 Estado dos Arquivos

```
gabi-kimi/
├── roadmap.md              ✅ Atualizado com Fases 3 e 4
├── day_sprint.md           ✅ Atualizado com checklist completo
├── PLANO_24_AGENTES.md     ✅ Criado - guia para cada agente
├── PIPELINE_COMPLETO_ROADMAP.md  ✅ Já existia
├── README.md               ✅ Teste Zero Kelvin documentado
└── src/
    ├── Gabi.Api/           ✅ Dashboard + Security
    ├── Gabi.Contracts/     ✅ DTOs completos
    ├── Gabi.Discover/      ✅ Parcial (falta WebCrawl, ApiPagination)
    ├── Gabi.Postgres/      ✅ EF Core + Migrations
    ├── Gabi.Sync/          ✅ Básico (extrair para Gabi.Jobs)
    └── Gabi.Worker/        ✅ Entry point
```

---

## 🎯 Definição de Pronto (DoD)

Para cada agente:
- ✅ Código compilando
- ✅ Testes unitários (60%+ cobertura, meta: 80%)
- ✅ Documentação XML
- ✅ Integração no build
- ✅ PR revisado

Para cada sprint:
- ✅ Teste Zero Kelvin passando
- ✅ Métricas de throughput > 100 docs/s
- ✅ Documentação atualizada

---

**Pronto para começar?** 🚀
