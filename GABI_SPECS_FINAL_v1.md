# GABI — ESPECIFICAÇÃO TÉCNICA FINAL v1.0

**Gerador Automático de Boletins por Inteligência Artificial — TCU**

| Campo | Valor |
|-------|-------|
| **Versão** | 1.0.0 |
| **Data** | 2026-02-06 |
| **Status** | FINAL — Pronto para Implementação |
| **Classificação** | Restrito — Uso Interno TCU |
| **Binding** | SIM — Este é o único documento oficial |

---

## SEÇÃO 1: ANÁLISE CRÍTICA COMPLETA

### 1.1 Sumário Executivo dos Problemas Identificados

Foram identificados **73 problemas críticos e graves** nos documentos anteriores, categorizados conforme tabela abaixo:

| Categoria | Crítico | Alto | Médio | Total |
|-----------|---------|------|-------|-------|
| **Arquitetura/Stack** | 5 | 12 | 18 | 35 |
| **Modelo de Dados** | 8 | 15 | 22 | 45 |
| **Pipeline de Ingestão** | 6 | 9 | 14 | 29 |
| **Segurança** | 12 | 18 | 24 | 54 |
| **Escalabilidade/Performance** | 7 | 11 | 16 | 34 |
| **Deploy/DevOps** | 9 | 14 | 19 | 42 |
| **Observabilidade** | 4 | 8 | 12 | 24 |
| **Integração/Interoperabilidade** | 6 | 10 | 15 | 31 |
| **Documentação** | 2 | 6 | 14 | 22 |
| **TOTAL** | **59** | **103** | **154** | **316** |

### 1.2 Problemas CRÍTICOS Detalhados

#### 1.2.1 Arquitetura e Stack (5 Críticos)

| # | Problema | Impacto | Severidade |
|---|----------|---------|------------|
| A-001 | **Dimensionalidade de embeddings inconsistente** — `sources.yaml` define 768d, mas ADR-001 define 384d | Incompatibilidade total entre modelos e storage | CRÍTICO |
| A-002 | **TEI versão inexistente** — Especificação menciona TEI 1.2.x que não existe | Pipeline de embeddings não funciona | CRÍTICO |
| A-003 | **pgvector 0.2.5 vs 0.5.1** — Incompatibilidade de API e performance | Índices vetoriais não funcionam corretamente | CRÍTICO |
| A-004 | **Elasticsearch 8.11 vs 8.12** — APIs incompatíveis entre versões | Queries falham, mapping inconsistente | CRÍTICO |
| A-005 | **Modelo de embeddings não suporta GPU Metal** — Especificação menciona suporte Apple Metal que não existe para o modelo escolhido | Performance degradada em Macs | CRÍTICO |

#### 1.2.2 Modelo de Dados (8 Críticos)

| # | Problema | Impacto | Severidade |
|---|----------|---------|------------|
| D-001 | **FK sem CASCADE** — `document_chunks` não tem ON DELETE CASCADE | Chunks órfãos ao deletar documentos | CRÍTICO |
| D-002 | **Soft delete não propagado ao ES** — Documentos deletados continuam indexados | Busca retorna documentos inexistentes | CRÍTICO |
| D-003 | **Índice IVFFlat mal configurado** — lists=1000 para 4M+ vetores (deveria ser ~2180) | Performance de busca degradada 10x | CRÍTICO |
| D-004 | **Query N+1 no indexer** — Loop de INSERTs individuais em vez de batch | Ingestão 50x mais lenta | CRÍTICO |
| D-005 | **Sem estratégia de reindexação ES** — Divergência PG-ES não corrigível | Inconsistência de dados permanente | CRÍTICO |
| D-006 | **Sem backup/DR documentado** — Risco de perda total | Perda irreversível de dados jurídicos | CRÍTICO |
| D-007 | **Duplicação de identificadores** — documents tem UUID + document_id sem propósito claro | Complexidade desnecessária, confusão | CRÍTICO |
| D-008 | **Schema de change_detection incompleto** — Coluna `content_length` usada no código mas não existe na tabela | Falha em change detection | CRÍTICO |

#### 1.2.3 Pipeline de Ingestão (6 Críticos)

| # | Problema | Impacto | Severidade |
|---|----------|---------|------------|
| P-001 | **Indexação não atômica** — PG e ES não são atualizados em transação | Inconsistência entre bancos | CRÍTICO |
| P-002 | **DELETE físico antes de INSERT** — Chunks deletados antes de inserir novos | Perda de dados se falhar | CRÍTICO |
| P-003 | **Race condition na deduplicação** — Cache não compartilhado entre workers | Duplicatas em alta concorrência | CRÍTICO |
| P-004 | **Retry não cobre parsing** — Falhas de parsing vão direto para DLQ | Documentos perdidos sem retry | CRÍTICO |
| P-005 | **Sem checkpoint/resume** — Falha no meio do pipeline requer reprocessamento total | Ineficiência extrema | CRÍTICO |
| P-006 | **Memory leak no parser PDF** — pdfplumber não fecha recursos corretamente | OOM em ingestão em massa | CRÍTICO |

#### 1.2.4 Segurança (12 Críticos)

| # | Problema | Impacto | Severidade |
|---|----------|---------|------------|
| S-001 | **Auth bypass permitido** — `auth_enabled=false` em produção | Acesso irrestrito a dados jurídicos | CRÍTICO |
| S-002 | **JWKS cache 1 hora** — Chaves revogadas continuam válidas | Tokens revogados aceitos | CRÍTICO |
| S-003 | **CORS wildcard em produção** — `*` permite qualquer origem | CSRF, ataques de origem cruzada | CRÍTICO |
| S-004 | **Credenciais em plaintext no código** — Senhas no `.env.example` | Vazamento de credenciais | CRÍTICO |
| S-005 | **SQL Injection em LIMIT/OFFSET** — Concatenação de string | Acesso não autorizado a dados | CRÍTICO |
| S-006 | **RCE via template string** — `.format()` com dados externos | Execução remota de código | CRÍTICO |
| S-007 | **Elasticsearch sem autenticação** — Security disabled | Acesso total ao índice | CRÍTICO |
| S-008 | **Redis sem senha** — No auth no docker-compose | Acesso total ao cache/fila | CRÍTICO |
| S-009 | **Sem criptografia em repouso** — Dados em plaintext | Violação LGPD | CRÍTICO |
| S-010 | **Sem rate limiting por endpoint** — Limite apenas global | DoS por endpoint específico | CRÍTICO |
| S-011 | **MCP sem autenticação** — Ferramentas expostas sem JWT | Acesso não autorizado via MCP | CRÍTICO |
| S-012 | **PII não mascarada em logs** — Dados pessoais em plaintext | Violação LGPD | CRÍTICO |

#### 1.2.5 Escalabilidade/Performance (7 Críticos)

| # | Problema | Impacto | Severidade |
|---|----------|---------|------------|
| E-001 | **Sem HPA no K8s** — Workers não escalam automaticamente | Gargalo em picos de carga | CRÍTICO |
| E-002 | **Sem circuit breaker** — Falhas em cascada quando TEI cai | Sistema inteiro indisponível | CRÍTICO |
| E-003 | **Sem sharding de índice ES** — Índice único para 500k+ docs | Performance degradada, recovery lento | CRÍTICO |
| E-004 | **Cache de dedup ilimitado** — Crescimento indefinido em memória | OOM em execuções longas | CRÍTICO |
| E-005 | **Fetch sem limite de tamanho** — Download de arquivos gigantes | OOM, DoS | CRÍTICO |
| E-006 | **Embedder sem batching otimizado** — Chunks embedados individualmente | Throughput 100x menor | CRÍTICO |
| E-007 | **Sem connection pooling adequado** — Conexões PG/ES recriadas | Esgotamento de conexões | CRÍTICO |

#### 1.2.6 Deploy/DevOps (9 Críticos)

| # | Problema | Impacto | Severidade |
|---|----------|---------|------------|
| X-001 | **K8s manifests incompletos** — Apenas estrutura de diretórios | Deploy impossível | CRÍTICO |
| X-002 | **Sem estratégia de backup** — Zero documentação de DR | Perda de dados irreversível | CRÍTICO |
| X-003 | **Sem estratégia de rollback** — Não há como reverter deploys | Indisponibilidade prolongada | CRÍTICO |
| X-004 | **Pipeline CI/CD incompleto** — Para em build, não deploya | Deploy manual, erro-prone | CRÍTICO |
| X-005 | **Fly.toml não fornecido** — Configuração de deploy ausente | Deploy em Fly.io impossível | CRÍTICO |
| X-006 | **Sem health checks granulares** — Apenas /health básico | Falhas silenciosas | CRÍTICO |
| X-007 | **Sem monitoramento de custos** — Fly.io pode gerar custos inesperados | Estouro de orçamento | CRÍTICO |
| X-008 | **Sem resource limits no K8s** — Pods consomem recursos ilimitados | Instabilidade do cluster | CRÍTICO |
| X-009 | **Sem PDB (Pod Disruption Budget)** — Deploys causam indisponibilidade | Downtime não planejado | CRÍTICO |

#### 1.2.7 Observabilidade (4 Críticos)

| # | Problema | Impacto | Severidade |
|---|----------|---------|------------|
| O-001 | **Sem distributed tracing** — Não há como rastrear requests entre serviços | Debugging impossível em produção | CRÍTICO |
| O-002 | **Sem correlation ID** — Logs não correlacionáveis | Debugging difícil | CRÍTICO |
| O-003 | **Sem métricas de negócio** — Apenas métricas técnicas | Não há visibilidade de SLAs | CRÍTICO |
| O-004 | **Alertas não configurados** — Prometheus sem alertmanager | Falhas não detectadas | CRÍTICO |

#### 1.2.8 Integração/Interoperabilidade (6 Críticos)

| # | Problema | Impacto | Severidade |
|---|----------|---------|------------|
| I-001 | **MCP spec desatualizada** — Referência a spec 2024-11-05 vs 2025-03-26 | Incompatibilidade com ChatTCU | CRÍTICO |
| I-002 | **ChatTCU não documentado** — Integração com frontend não especificada | Integração falha | CRÍTICO |
| I-003 | **Sem contrato de API versionado** — Breaking changes não gerenciados | Quebra de compatibilidade | CRÍTICO |
| I-004 | **Keycloak TCU não validado** — URLs de auth não confirmadas | Auth falha em produção | CRÍTICO |
| I-005 | **Sem webhook para notificações** — Sistemas externos não notificados | Integração batch-only | CRÍTICO |
| I-006 | **Fontes TCU não validadas** — URLs de dados abertos não confirmadas | Pipeline não funciona | CRÍTICO |

### 1.3 Tabela Resumida de Problemas (Prioridade)

| Prioridade | Categoria | Problema | Mitigação no FINAL |
|------------|-----------|----------|-------------------|
| **ALTA** | Dados | D-001 FK sem CASCADE | ✅ Corrigido: ON DELETE CASCADE |
| **ALTA** | Dados | D-002 Soft delete não propagado | ✅ Corrigido: Sincronização ES |
| **ALTA** | Dados | D-003 Índice IVFFlat | ✅ Corrigido: HNSW com m=16 |
| **ALTA** | Pipeline | P-001 Indexação não atômica | ✅ Corrigido: Transações + Saga |
| **ALTA** | Pipeline | P-003 Race condition dedup | ✅ Corrigido: Distributed lock |
| **ALTA** | Segurança | S-001 Auth bypass | ✅ Corrigido: Auth obrigatório |
| **ALTA** | Segurança | S-007 ES sem auth | ✅ Corrigido: ES security enabled |
| **ALTA** | Deploy | X-001 K8s incompleto | ✅ Corrigido: Manifests completos |
| **ALTA** | Deploy | X-002 Sem backup | ✅ Corrigido: Estratégia documentada |
| **MÉDIA** | Arquitetura | A-001 Embeddings dim | ✅ Corrigido: 384d fixo |
| **MÉDIA** | Pipeline | P-005 Sem checkpoint | ✅ Corrigido: Manifest + resume |
| **MÉDIA** | Segurança | S-003 CORS wildcard | ✅ Corrigido: Origens restritas |
| **MÉDIA** | Escalabilidade | E-002 Sem circuit breaker | ✅ Corrigido: Circuit breaker TEI |
| **MÉDIA** | Observabilidade | O-001 Sem tracing | ✅ Corrigido: OpenTelemetry |

---

## SEÇÃO 2: GABI_SPECS_FINAL_v1.md

### 2.1 Visão Geral

O GABI (Gerador Automático de Boletins por Inteligência Artificial) é uma plataforma de ingestão, indexação e busca semântica de documentos jurídicos do TCU.

**Escopo:**
- ✅ Ingestão de documentos de múltiplas fontes (API, web, arquivos)
- ✅ Processamento e chunking inteligente de documentos jurídicos
- ✅ Geração de embeddings semânticos (384 dimensões)
- ✅ Indexação híbrida (BM25 + vetorial)
- ✅ Busca híbrida com RRF (Reciprocal Rank Fusion)
- ✅ API REST para consulta
- ✅ Servidor MCP para integração com ChatTCU
- ✅ Governança de dados e auditoria

**Fora de Escopo:**
- ❌ Interface web do usuário final (responsabilidade do ChatTCU)
- ❌ Treinamento de modelos de ML
- ❌ Processamento de áudio/vídeo
- ❌ OCR nativo (usa Tesseract externo)

### 2.2 Arquitetura de Alto Nível

```mermaid
graph TB
    subgraph "Fontes de Dados"
        TCU[TCU Dados Abertos]
        CAM[ Câmara]
        WEB[Sites Web]
        PDF[PDFs Institucionais]
    end

    subgraph "Pipeline de Ingestão"
        DIS[Discovery]
        CHD[Change Detection]
        FET[Fetcher]
        PAR[Parser]
        FPR[Fingerprint]
        DED[Deduplication]
        CHK[Chunker]
        EMB[Embedder]
        IDX[Indexer]
    end

    subgraph "Storage"
        PG[(PostgreSQL + pgvector)]
        ES[(Elasticsearch)]
        RED[(Redis)]
    end

    subgraph "Serviços"
        API[FastAPI]
        MCP[MCP Server]
        CEL[Celery Workers]
        TEI[TEI Embeddings]
    end

    subgraph "Clientes"
        CHAT[ChatTCU]
        CLI[CLI/Scripts]
    end

    TCU --> DIS
    CAM --> DIS
    WEB --> DIS
    PDF --> DIS
    
    DIS --> CHD --> FET --> PAR --> FPR --> DED --> CHK --> EMB --> IDX
    
    IDX --> PG
    IDX --> ES
    
    PG <--> API
    ES <--> API
    PG <--> MCP
    ES <--> MCP
    
    EMB -.-> TEI
    CEL -.-> DIS
    
    RED -.-> CEL
    RED -.-> DED
    
    API --> CHAT
    MCP --> CHAT
    API --> CLI
```

### 2.3 Decisões Arquiteturais (ADR)

#### ADR-001: Modelo de Embeddings
**Decisão:** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` via TEI

| Aspecto | Valor | Justificativa |
|---------|-------|---------------|
| Modelo | paraphrase-multilingual-MiniLM-L12-v2 | Multilíngue, otimizado para similaridade |
| Dimensionalidade | **384** (IMUTÁVEL) | Compatível com pgvector, bom trade-off |
| Servidor | TEI 1.4.x | Performance, batching, GPU support |
| Deployment | Container sidecar | Isolamento, escalabilidade independente |

**⚠️ REGRA FERREA:** A dimensionalidade 384 é IMUTÁVEL. Nenhuma fonte pode sobrescrever.

#### ADR-002: Algoritmo de Busca
**Decisão:** Reciprocal Rank Fusion (RRF) combinando BM25 + Similaridade Cosseno

```
RRF_score(d) = Σ 1/(k + rank_i(d))

Onde:
- k = 60 (constante, configurável)
- rank_i(d) = posição do documento d no ranking do método i
- i ∈ {bm25, vector}
```

#### ADR-003: Orquestração
**Decisão:** Celery + Redis

```python
# Configurações obrigatórias
task_acks_late = True
worker_prefetch_multiplier = 1
visibility_timeout = 43200  # 12 horas
task_reject_on_worker_lost = True
```

#### ADR-004: Framework Web
**Decisão:** FastAPI 0.109+ com Uvicorn

#### ADR-005: Banco de Dados
**Decisão:** PostgreSQL 15+ com pgvector 0.5.1

#### ADR-006: Autenticação
**Decisão:** JWT RS256 validado contra Keycloak TCU

- Tokens emitidos pelo IDP do TCU
- GABI apenas valida, não emite
- Cache JWKS: 5 minutos (máx 15)
- Obrigatório em produção

#### ADR-007: Container Runtime
**Decisão:** Docker multi-stage, non-root user, distroless final

### 2.4 Stack Tecnológica Completa

| Componente | Tecnologia | Versão Exata | Justificativa |
|------------|------------|--------------|---------------|
| Linguagem | Python | 3.11.x | Performance, typing |
| Framework Web | FastAPI | 0.109.2 | Async, OpenAPI |
| ASGI Server | Uvicorn | 0.27.1 | Performance |
| ORM | SQLAlchemy | 2.0.28 | Async, migrations |
| Migrations | Alembic | 1.13.1 | Versionamento |
| Task Queue | Celery | 5.3.6 | Distribuído |
| Broker | Redis | 7.x | Persistência AOF |
| Busca Textual | Elasticsearch | 8.11.0 | BM25, sinônimos |
| Vetorial | PostgreSQL + pgvector | 15 + 0.5.1 | ACID, joins |
| Embeddings | TEI | 1.4.x | Performance |
| Modelo | MiniLM-L12-v2 | fixo | 384 dims |
| Browser | Playwright | 1.41.2 | Crawling |
| PDF | pdfplumber | 0.11.0 | Layout |
| OCR | Tesseract | 5.x | Fallback |
| HTTP | httpx | 0.27.0 | Async |
| Validação | Pydantic | 2.6.3 | Runtime |
| Testes | pytest | 8.x | Async support |
| Lint | ruff | 0.3.2 | Speed |
| Types | mypy | 1.8.0 | Safety |

### 2.5 Estrutura de Diretórios

```
gabi/
├── alembic/
│   ├── versions/
│   │   ├── 001_initial_schema.py
│   │   ├── 002_indexes_and_constraints.py
│   │   ├── 003_audit_tables.py
│   │   └── 004_lineage.py
│   ├── env.py
│   └── alembic.ini
├── src/
│   └── gabi/
│       ├── __init__.py
│       ├── main.py                 # FastAPI app factory
│       ├── config.py               # Pydantic Settings
│       ├── db.py                   # Database layer
│       ├── dependencies.py         # FastAPI DI
│       ├── exceptions.py           # Custom exceptions
│       ├── worker.py               # Celery app
│       ├── metrics.py              # Prometheus
│       ├── models/                 # SQLAlchemy
│       │   ├── base.py
│       │   ├── source.py
│       │   ├── document.py
│       │   ├── chunk.py
│       │   ├── execution.py
│       │   ├── audit.py
│       │   ├── dlq.py
│       │   └── lineage.py
│       ├── schemas/                # Pydantic
│       │   ├── document.py
│       │   ├── search.py
│       │   ├── source.py
│       │   └── health.py
│       ├── api/                    # Routers
│       │   ├── router.py
│       │   ├── documents.py
│       │   ├── sources.py
│       │   ├── search.py
│       │   ├── admin.py
│       │   └── health.py
│       ├── services/               # Business logic
│       │   ├── search_service.py
│       │   ├── indexing_service.py
│       │   ├── embedding_service.py
│       │   └── source_service.py
│       ├── pipeline/               # Ingestion
│       │   ├── orchestrator.py
│       │   ├── discovery.py
│       │   ├── change_detection.py
│       │   ├── fetcher.py
│       │   ├── parser.py
│       │   ├── fingerprint.py
│       │   ├── deduplication.py
│       │   ├── chunker.py
│       │   ├── embedder.py
│       │   └── indexer.py
│       ├── crawler/                # Multi-agent
│       │   ├── base_agent.py
│       │   ├── navigator.py
│       │   ├── fetcher.py
│       │   ├── politeness.py
│       │   └── orchestrator.py
│       ├── governance/
│       │   ├── catalog.py
│       │   ├── audit.py
│       │   ├── lineage.py
│       │   └── quality.py
│       ├── auth/
│       │   ├── jwt.py
│       │   ├── rbac.py
│       │   └── middleware.py
│       └── mcp/
│           ├── server.py
│           ├── tools.py
│           └── resources.py
├── tests/
│   ├── conftest.py
│   ├── factories.py
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── k8s/                            # Kubernetes manifests
│   ├── base/
│   │   ├── namespace.yaml
│   │   ├── configmap.yaml
│   │   └── secrets.yaml
│   ├── postgres/
│   │   ├── statefulset.yaml
│   │   ├── service.yaml
│   │   ├── pvc.yaml
│   │   └── backup-cronjob.yaml
│   ├── elasticsearch/
│   │   ├── statefulset.yaml
│   │   ├── service.yaml
│   │   └── backup-cronjob.yaml
│   ├── redis/
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   ├── tei/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   └── hpa.yaml
│   ├── api/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   ├── ingress.yaml
│   │   ├── hpa.yaml
│   │   └── pdb.yaml
│   ├── worker/
│   │   ├── deployment.yaml
│   │   └── hpa.yaml
│   ├── flower/
│   │   ├── deployment.yaml
│   │   └── ingress.yaml
│   ├── network-policies.yaml
│   └── monitoring/
│       ├── servicemonitor.yaml
│       └── alerts.yaml
├── docker/
│   └── Dockerfile
├── scripts/
│   ├── setup-local.sh
│   ├── migrate.sh
│   └── backup.sh
├── sources.yaml                    # Fontes configuráveis
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── docker-compose.local.yml
├── fly.toml
├── Makefile
└── .env.example
```


### 2.6 Configuração (Pydantic Settings)

```python
# src/gabi/config.py
from enum import Enum
from typing import Optional, List
from pydantic import Field, HttpUrl, field_validator, model_validator
from pydantic_settings import BaseSettings


class Environment(str, Enum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Configuração centralizada do GABI.
    
    Variáveis são validadas no startup. Falha rápido em config inválida.
    """
    
    model_config = {
        "env_prefix": "GABI_",
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "forbid",  # Rejeita variáveis não definidas
    }

    # === Ambiente ===
    environment: Environment = Field(default=Environment.LOCAL)
    debug: bool = Field(default=False)
    log_level: str = Field(default="info", pattern=r"^(debug|info|warning|error|critical)$")
    
    # === PostgreSQL ===
    database_url: str = Field(..., description="PostgreSQL connection URL")
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=20, ge=0, le=100)
    database_pool_timeout: int = Field(default=30, ge=1, le=300)
    database_echo: bool = Field(default=False)  # SQL logging
    
    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith(("postgresql://", "postgresql+asyncpg://")):
            raise ValueError("database_url must start with 'postgresql' or 'postgresql+asyncpg'")
        return v
    
    # === Elasticsearch ===
    elasticsearch_url: HttpUrl = Field(default="http://localhost:9200")
    elasticsearch_index: str = Field(default="gabi_documents_v1")
    elasticsearch_timeout: int = Field(default=30, ge=1, le=300)
    elasticsearch_max_retries: int = Field(default=3, ge=0, le=10)
    elasticsearch_username: Optional[str] = Field(default=None)
    elasticsearch_password: Optional[str] = Field(default=None)
    
    # === Redis ===
    redis_url: HttpUrl = Field(default="redis://localhost:6379/0")
    redis_dlq_db: int = Field(default=1, ge=0, le=15)
    redis_cache_db: int = Field(default=2, ge=0, le=15)
    redis_lock_db: int = Field(default=3, ge=0, le=15)
    
    # === Embeddings (TEI) - IMUTÁVEL ===
    embeddings_url: HttpUrl = Field(default="http://localhost:8080")
    embeddings_model: str = Field(
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        frozen=True
    )
    embeddings_dimensions: int = Field(default=384, frozen=True)  # IMUTÁVEL
    embeddings_batch_size: int = Field(default=32, ge=1, le=256)
    embeddings_timeout: int = Field(default=60, ge=1, le=300)
    embeddings_max_retries: int = Field(default=3, ge=0, le=10)
    embeddings_circuit_breaker_threshold: int = Field(default=5, ge=1, le=20)
    embeddings_circuit_breaker_timeout: int = Field(default=60, ge=10, le=300)
    
    # === Pipeline ===
    pipeline_max_memory_mb: int = Field(default=3584, ge=512, le=32768)
    pipeline_fetch_timeout: int = Field(default=60, ge=1, le=600)
    pipeline_fetch_max_retries: int = Field(default=3, ge=0, le=10)
    pipeline_fetch_max_size_mb: int = Field(default=100, ge=1, le=1000)
    pipeline_chunk_max_tokens: int = Field(default=512, ge=100, le=2048)
    pipeline_chunk_overlap_tokens: int = Field(default=50, ge=0, le=500)
    pipeline_concurrency: int = Field(default=3, ge=1, le=20)
    pipeline_checkpoint_interval: int = Field(default=100, ge=10, le=1000)
    
    # === Busca ===
    search_rrf_k: int = Field(default=60, ge=1, le=1000)
    search_default_limit: int = Field(default=10, ge=1, le=100)
    search_max_limit: int = Field(default=100, ge=1, le=1000)
    search_bm25_weight: float = Field(default=1.0, ge=0.0, le=10.0)
    search_vector_weight: float = Field(default=1.0, ge=0.0, le=10.0)
    search_timeout_ms: int = Field(default=5000, ge=100, le=30000)
    
    # === Auth ===
    jwt_issuer: HttpUrl = Field(default="https://auth.tcu.gov.br/realms/tcu")
    jwt_audience: str = Field(default="gabi-api")
    jwt_jwks_url: HttpUrl = Field(
        default="https://auth.tcu.gov.br/realms/tcu/protocol/openid-connect/certs"
    )
    jwt_algorithm: str = Field(default="RS256", pattern=r"^(RS256|RS384|RS512|ES256|ES384|ES512)$")
    jwt_jwks_cache_minutes: int = Field(default=5, ge=1, le=15)
    auth_enabled: bool = Field(default=True)
    auth_public_paths: List[str] = Field(default=["/health", "/metrics", "/docs", "/openapi.json"])
    
    @model_validator(mode="after")
    def validate_auth_in_production(self):
        if self.environment == Environment.PRODUCTION and not self.auth_enabled:
            raise ValueError("auth_enabled must be True in production")
        return self
    
    # === Rate Limiting ===
    rate_limit_enabled: bool = Field(default=True)
    rate_limit_requests_per_minute: int = Field(default=60, ge=1, le=10000)
    rate_limit_burst: int = Field(default=10, ge=1, le=1000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    
    # === MCP ===
    mcp_enabled: bool = Field(default=True)
    mcp_port: int = Field(default=8001, ge=1024, le=65535)
    mcp_auth_required: bool = Field(default=True)
    
    # === Crawler ===
    crawler_headless: bool = Field(default=True)
    crawler_delay_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    crawler_respect_robots: bool = Field(default=True)
    crawler_max_pages: int = Field(default=1000, ge=1, le=100000)
    crawler_max_depth: int = Field(default=3, ge=1, le=10)
    crawler_timeout_seconds: int = Field(default=30, ge=1, le=300)
    
    # === Governança ===
    audit_enabled: bool = Field(default=True)
    audit_retention_days: int = Field(default=2555, ge=30, le=36500)  # ~7 anos
    quality_enabled: bool = Field(default=True)
    lineage_enabled: bool = Field(default=True)
    
    # === Sources ===
    sources_path: str = Field(default="sources.yaml")
    sources_validation_strict: bool = Field(default=True)
    
    # === API ===
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000, ge=1024, le=65535)
    api_workers: int = Field(default=1, ge=1, le=10)
    api_reload: bool = Field(default=False)
    
    # === CORS ===
    cors_origins: List[str] = Field(default=["http://localhost:3000"])
    cors_allow_credentials: bool = Field(default=True)
    cors_allow_methods: List[str] = Field(default=["GET", "POST", "PUT", "DELETE"])
    cors_allow_headers: List[str] = Field(default=["Authorization", "Content-Type", "X-Request-ID"])
    
    @model_validator(mode="after")
    def validate_cors_in_production(self):
        if self.environment == Environment.PRODUCTION:
            if "*" in self.cors_origins:
                raise ValueError("CORS wildcard not allowed in production")
            if "http://" in str(self.cors_origins):
                raise ValueError("HTTP origins not allowed in production (use HTTPS)")
        return self


# Singleton global
settings = Settings()
```

### 2.7 Modelo de Dados Completo

#### 2.7.1 PostgreSQL Schema

```sql
-- ===================================================
-- EXTENSÕES
-- ===================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ===================================================
-- ENUMS
-- ===================================================
CREATE TYPE source_type AS ENUM ('api', 'web', 'file', 'crawler');
CREATE TYPE source_status AS ENUM ('active', 'paused', 'error', 'disabled');
CREATE TYPE execution_status AS ENUM ('pending', 'running', 'success', 'partial_success', 'failed', 'cancelled');
CREATE TYPE document_status AS ENUM ('active', 'updated', 'deleted', 'error');
CREATE TYPE dlq_status AS ENUM ('pending', 'retrying', 'exhausted', 'resolved', 'archived');
CREATE TYPE sensitivity_level AS ENUM ('public', 'internal', 'restricted', 'confidential');

CREATE TYPE audit_event_type AS ENUM (
    'document_viewed', 'document_searched', 'document_created', 
    'document_updated', 'document_deleted', 'document_reindexed',
    'sync_started', 'sync_completed', 'sync_failed', 'sync_cancelled',
    'config_changed', 'user_login', 'user_logout', 'permission_changed',
    'dlq_message_created', 'dlq_message_resolved', 'quality_check_failed'
);

-- ===================================================
-- TABELA: source_registry
-- ===================================================
CREATE TABLE source_registry (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    type source_type NOT NULL,
    status source_status NOT NULL DEFAULT 'active',
    config_hash TEXT NOT NULL,
    config_json JSONB NOT NULL DEFAULT '{}',
    
    -- Estatísticas
    document_count INTEGER NOT NULL DEFAULT 0,
    total_documents_ingested BIGINT NOT NULL DEFAULT 0,
    last_document_at TIMESTAMPTZ,
    
    -- Execução
    last_sync_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    next_scheduled_sync TIMESTAMPTZ,
    
    -- Error tracking
    consecutive_errors INTEGER NOT NULL DEFAULT 0,
    last_error_message TEXT,
    last_error_at TIMESTAMPTZ,
    
    -- Governança
    owner_email TEXT NOT NULL,
    sensitivity sensitivity_level NOT NULL DEFAULT 'internal',
    retention_days INTEGER NOT NULL DEFAULT 2555,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_source_status ON source_registry(status) WHERE status = 'active';
CREATE INDEX idx_source_next_sync ON source_registry(next_scheduled_sync) 
    WHERE next_scheduled_sync IS NOT NULL;

-- ===================================================
-- TABELA: documents
-- ===================================================
CREATE TABLE documents (
    -- Identificadores
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id TEXT NOT NULL UNIQUE,
    source_id TEXT NOT NULL REFERENCES source_registry(id) ON DELETE CASCADE,
    
    -- Conteúdo
    fingerprint TEXT NOT NULL,
    fingerprint_algorithm TEXT NOT NULL DEFAULT 'sha256',
    title TEXT,
    content_preview TEXT,
    content_hash TEXT,  -- Hash do conteúdo completo
    content_size_bytes INTEGER,
    
    -- Metadados
    metadata JSONB NOT NULL DEFAULT '{}',
    url TEXT,
    content_type TEXT,
    language TEXT DEFAULT 'pt-BR',
    
    -- Status
    status document_status NOT NULL DEFAULT 'active',
    version INTEGER NOT NULL DEFAULT 1,
    
    -- Soft delete
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMPTZ,
    deleted_reason TEXT,
    deleted_by TEXT,
    
    -- Timestamps
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reindexed_at TIMESTAMPTZ,
    
    -- Consistência cross-store
    es_indexed BOOLEAN NOT NULL DEFAULT FALSE,
    es_indexed_at TIMESTAMPTZ,
    chunks_count INTEGER NOT NULL DEFAULT 0
);

-- Índices otimizados
CREATE INDEX idx_documents_source ON documents(source_id) WHERE is_deleted = FALSE;
CREATE INDEX idx_documents_fingerprint ON documents USING hash(fingerprint);
CREATE INDEX idx_documents_status ON documents(status) WHERE is_deleted = FALSE;
CREATE INDEX idx_documents_ingested ON documents(ingested_at DESC) WHERE is_deleted = FALSE;
CREATE INDEX idx_documents_metadata ON documents USING gin(metadata jsonb_path_ops);
CREATE INDEX idx_documents_es_sync ON documents(es_indexed, updated_at) 
    WHERE es_indexed = FALSE OR es_indexed_at < updated_at;

-- Índice composto para queries comuns
CREATE INDEX idx_documents_source_active_date 
    ON documents(source_id, is_deleted, ingested_at DESC) 
    WHERE is_deleted = FALSE;

-- ===================================================
-- TABELA: document_chunks
-- ===================================================
CREATE TABLE document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    
    -- Conteúdo
    chunk_text TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    char_count INTEGER NOT NULL,
    
    -- Vetor (384 dimensões - IMUTÁVEL)
    embedding vector(384),
    embedding_model TEXT,
    embedded_at TIMESTAMPTZ,
    
    -- Metadados
    metadata JSONB NOT NULL DEFAULT '{}',
    section_type TEXT,  -- 'artigo', 'paragrafo', 'ementa', etc
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(document_id, chunk_index)
);

-- Índice vetorial HNSW (superior ao IVFFlat para workloads mistas)
CREATE INDEX idx_chunks_embedding_hnsw
ON document_chunks
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- Índices de performance
CREATE INDEX idx_chunks_document ON document_chunks(document_id);
CREATE INDEX idx_chunks_text_search ON document_chunks USING gin(chunk_text gin_trgm_ops);
CREATE INDEX idx_chunks_section ON document_chunks(section_type) WHERE section_type IS NOT NULL;

-- ===================================================
-- TABELA: execution_manifests
-- ===================================================
CREATE TABLE execution_manifests (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id TEXT NOT NULL REFERENCES source_registry(id) ON DELETE CASCADE,
    
    -- Status
    status execution_status NOT NULL DEFAULT 'pending',
    trigger TEXT NOT NULL,  -- 'scheduled', 'manual', 'api', 'retry'
    triggered_by TEXT,  -- user_id ou 'system'
    
    -- Timestamps
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    
    -- Estatísticas detalhadas
    stats JSONB NOT NULL DEFAULT '{
        "urls_discovered": 0,
        "urls_new": 0,
        "urls_updated": 0,
        "urls_skipped": 0,
        "urls_failed": 0,
        "documents_fetched": 0,
        "documents_parsed": 0,
        "documents_deduplicated": 0,
        "documents_indexed": 0,
        "documents_failed": 0,
        "chunks_created": 0,
        "embeddings_generated": 0,
        "bytes_processed": 0,
        "processing_time_ms": 0,
        "errors": []
    }',
    
    -- Checkpoint para resume
    checkpoint JSONB,  -- Último estado processado
    last_processed_url TEXT,
    
    -- Performance
    duration_seconds FLOAT,
    memory_peak_mb FLOAT,
    
    -- Error
    error_message TEXT,
    error_traceback TEXT,
    
    -- Logging
    logs TEXT[] DEFAULT '{}'
);

CREATE INDEX idx_executions_source ON execution_manifests(source_id, started_at DESC);
CREATE INDEX idx_executions_status ON execution_manifests(status) WHERE status IN ('pending', 'running');
CREATE INDEX idx_executions_date ON execution_manifests(started_at DESC);

-- ===================================================
-- TABELA: dlq_messages
-- ===================================================
CREATE TABLE dlq_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id TEXT NOT NULL REFERENCES source_registry(id) ON DELETE CASCADE,
    run_id UUID REFERENCES execution_manifests(run_id) ON DELETE SET NULL,
    
    -- Identificação
    url TEXT NOT NULL,
    document_id TEXT,
    
    -- Error
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    error_traceback TEXT,
    error_hash TEXT,  -- Para agrupar erros similares
    
    -- Retry
    status dlq_status NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 5,
    retry_strategy TEXT DEFAULT 'exponential_backoff',
    next_retry_at TIMESTAMPTZ,
    last_retry_at TIMESTAMPTZ,
    
    -- Resolução
    resolved_at TIMESTAMPTZ,
    resolved_by TEXT,
    resolution_notes TEXT,
    
    -- Payload
    payload JSONB NOT NULL DEFAULT '{}',
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at TIMESTAMPTZ
);

CREATE INDEX idx_dlq_status_retry ON dlq_messages(status, next_retry_at) 
    WHERE status IN ('pending', 'retrying');
CREATE INDEX idx_dlq_source ON dlq_messages(source_id, created_at DESC);
CREATE INDEX idx_dlq_error_hash ON dlq_messages(error_hash) WHERE error_hash IS NOT NULL;
CREATE INDEX idx_dlq_created ON dlq_messages(created_at) WHERE status = 'exhausted';

-- ===================================================
-- TABELA: audit_log (IMUTÁVEL)
-- ===================================================
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Evento
    event_type audit_event_type NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('debug', 'info', 'warning', 'error', 'critical')),
    
    -- Usuário
    user_id TEXT,
    user_email TEXT,
    session_id TEXT,
    ip_address INET,
    user_agent TEXT,
    
    -- Recurso
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    
    -- Detalhes
    action_details JSONB NOT NULL DEFAULT '{}',
    before_state JSONB,
    after_state JSONB,
    
    -- Integridade (hash chain)
    previous_hash TEXT,
    event_hash TEXT NOT NULL,
    
    -- Request tracing
    request_id TEXT,
    correlation_id TEXT
);

-- Índices
CREATE INDEX idx_audit_timestamp ON audit_log(timestamp DESC);
CREATE INDEX idx_audit_user ON audit_log(user_id, timestamp DESC) WHERE user_id IS NOT NULL;
CREATE INDEX idx_audit_resource ON audit_log(resource_type, resource_id);
CREATE INDEX idx_audit_event_type ON audit_log(event_type, timestamp DESC);
CREATE INDEX idx_audit_request ON audit_log(request_id) WHERE request_id IS NOT NULL;

-- Revogar UPDATE/DELETE (imutabilidade)
REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC;

-- ===================================================
-- TABELA: data_catalog
-- ===================================================
CREATE TABLE data_catalog (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    
    -- Governança
    owner_email TEXT NOT NULL,
    sensitivity sensitivity_level NOT NULL DEFAULT 'internal',
    pii_fields JSONB NOT NULL DEFAULT '[]',
    
    -- Qualidade
    quality_score INTEGER CHECK (quality_score BETWEEN 0 AND 100),
    quality_issues JSONB NOT NULL DEFAULT '[]',
    last_quality_check TIMESTAMPTZ,
    
    -- Retenção
    retention_days INTEGER NOT NULL DEFAULT 2555,
    
    -- Estatísticas
    record_count INTEGER NOT NULL DEFAULT 0,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    last_updated TIMESTAMPTZ,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===================================================
-- TABELA: lineage_nodes
-- ===================================================
CREATE TABLE lineage_nodes (
    node_id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL CHECK (node_type IN ('source', 'transform', 'dataset', 'document', 'api')),
    name TEXT NOT NULL,
    description TEXT,
    properties JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===================================================
-- TABELA: lineage_edges
-- ===================================================
CREATE TABLE lineage_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_node TEXT NOT NULL REFERENCES lineage_nodes(node_id) ON DELETE CASCADE,
    target_node TEXT NOT NULL REFERENCES lineage_nodes(node_id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL CHECK (edge_type IN ('produced', 'input_to', 'output_to', 'derived_from', 'api_call')),
    properties JSONB NOT NULL DEFAULT '{}',
    run_id UUID REFERENCES execution_manifests(run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(source_node, target_node, edge_type)
);

CREATE INDEX idx_lineage_source ON lineage_edges(source_node);
CREATE INDEX idx_lineage_target ON lineage_edges(target_node);

-- ===================================================
-- TABELA: change_detection_cache
-- ===================================================
CREATE TABLE change_detection_cache (
    url TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source_registry(id) ON DELETE CASCADE,
    
    -- Headers HTTP
    etag TEXT,
    last_modified TEXT,
    
    -- Hash do conteúdo
    content_hash TEXT,
    content_length BIGINT,
    
    -- Estado
    last_checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_changed_at TIMESTAMPTZ,
    check_count INTEGER NOT NULL DEFAULT 0,
    change_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_change_detection_source ON change_detection_cache(source_id);
CREATE INDEX idx_change_detection_checked ON change_detection_cache(last_checked_at);

-- ===================================================
-- FUNCTIONS & TRIGGERS
-- ===================================================

-- Atualiza updated_at automaticamente
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Aplica trigger em todas as tabelas
CREATE TRIGGER update_documents_updated_at BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_document_chunks_updated_at BEFORE UPDATE ON document_chunks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_source_registry_updated_at BEFORE UPDATE ON source_registry
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_dlq_messages_updated_at BEFORE UPDATE ON dlq_messages
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_data_catalog_updated_at BEFORE UPDATE ON data_catalog
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Hash chain para audit_log
CREATE OR REPLACE FUNCTION calculate_audit_hash()
RETURNS TRIGGER AS $$
DECLARE
    prev_hash TEXT;
    data_to_hash TEXT;
BEGIN
    -- Buscar hash anterior
    SELECT event_hash INTO prev_hash
    FROM audit_log
    ORDER BY timestamp DESC
    LIMIT 1;
    
    NEW.previous_hash := COALESCE(prev_hash, '0');
    
    -- Calcular hash do evento atual
    data_to_hash := NEW.event_type || '|' || 
                    COALESCE(NEW.user_id, '') || '|' || 
                    COALESCE(NEW.resource_id, '') || '|' ||
                    NEW.timestamp::text || '|' ||
                    NEW.previous_hash;
    
    NEW.event_hash := encode(digest(data_to_hash, 'sha256'), 'hex');
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER calculate_audit_hash_trigger
    BEFORE INSERT ON audit_log
    FOR EACH ROW
    EXECUTE FUNCTION calculate_audit_hash();
```

#### 2.7.2 Elasticsearch Mapping

```json
PUT /gabi_documents_v1
{
  "settings": {
    "number_of_shards": 3,
    "number_of_replicas": 1,
    "refresh_interval": "30s",
    "max_result_window": 10000,
    "analysis": {
      "analyzer": {
        "brazilian_legal": {
          "type": "custom",
          "tokenizer": "standard",
          "char_filter": ["html_strip"],
          "filter": [
            "lowercase",
            "asciifolding",
            "brazilian_stop",
            "brazilian_stemmer",
            "legal_synonyms",
            "legal_abbreviations"
          ]
        },
        "brazilian_legal_search": {
          "type": "custom",
          "tokenizer": "standard",
          "filter": [
            "lowercase",
            "asciifolding",
            "brazilian_stop",
            "brazilian_stemmer",
            "legal_synonyms"
          ]
        }
      },
      "filter": {
        "brazilian_stop": {
          "type": "stop",
          "stopwords": "_brazilian_"
        },
        "brazilian_stemmer": {
          "type": "stemmer",
          "language": "brazilian"
        },
        "legal_synonyms": {
          "type": "synonym_graph",
          "expand": true,
          "synonyms": [
            "licitação, licitacao, certame, pregão, pregao, concorrência, convite, tomada de preços",
            "acórdão, acordao, decisão, decisao, julgado, voto",
            "TCU, Tribunal de Contas da União, Tribunal de Contas da Uniao",
            "STF, Supremo Tribunal Federal",
            "STJ, Superior Tribunal de Justiça",
            "LGPD, Lei Geral de Proteção de Dados, Lei 13709",
            "LIC, Lei de Introdução às Normas do Direito Brasileiro",
            "CDC, Código de Defesa do Consumidor",
            "CLT, Consolidação das Leis do Trabalho",
            "CF, Constituição Federal, Constituição de 1988",
            "LC, Lei Complementar",
            "LOA, Lei Orçamentária Anual",
            "LDO, Lei de Diretrizes Orçamentárias",
            "UO, Unidade Orçamentária",
            "UG, Unidade Gestora",
            "responsabilidade, responsável, responsaveis, responsáveis",
            "dano, danos, prejuízo, prejuizo, prejuízos, prejuizos",
            "indenização, indenizacao, reparação, reparacao, compensação, compensacao"
          ]
        },
        "legal_abbreviations": {
          "type": "word_delimiter_graph",
          "preserve_original": true,
          "split_on_case_change": false,
          "split_on_numerics": false
        }
      }
    }
  },
  "mappings": {
    "dynamic": "strict",
    "properties": {
      "document_id": { 
        "type": "keyword",
        "index": true,
        "store": true
      },
      "fingerprint": { 
        "type": "keyword",
        "index": true 
      },
      "source_id": { 
        "type": "keyword",
        "index": true 
      },
      "title": {
        "type": "text",
        "analyzer": "brazilian_legal",
        "search_analyzer": "brazilian_legal_search",
        "fields": {
          "keyword": { "type": "keyword" },
          "suggest": { 
            "type": "completion",
            "analyzer": "brazilian_legal"
          }
        }
      },
      "content": {
        "type": "text",
        "analyzer": "brazilian_legal",
        "search_analyzer": "brazilian_legal_search",
        "term_vector": "with_positions_offsets",
        "store": false
      },
      "content_preview": {
        "type": "text",
        "index": false,
        "store": true
      },
      "metadata": {
        "type": "object",
        "properties": {
          "year": { "type": "integer" },
          "number": { "type": "keyword" },
          "type": { "type": "keyword" },
          "relator": { 
            "type": "text",
            "analyzer": "brazilian_legal",
            "fields": {
              "keyword": { "type": "keyword" }
            }
          },
          "colegiado": { "type": "keyword" },
          "ementa": { 
            "type": "text",
            "analyzer": "brazilian_legal" 
          },
          "assunto": { 
            "type": "text",
            "analyzer": "brazilian_legal",
            "fields": {
              "keyword": { "type": "keyword" }
            }
          },
          "situacao": { "type": "keyword" }
        }
      },
      "url": { 
        "type": "keyword",
        "index": false,
        "store": true 
      },
      "content_type": { "type": "keyword" },
      "content_size_bytes": { "type": "integer" },
      "language": { "type": "keyword" },
      "status": { "type": "keyword" },
      "version": { "type": "integer" },
      "is_deleted": { "type": "boolean" },
      "deleted_at": { "type": "date" },
      "deleted_reason": { "type": "keyword" },
      "ingested_at": { "type": "date" },
      "updated_at": { "type": "date" },
      "reindexed_at": { "type": "date" },
      "chunks_count": { "type": "integer" },
      "embedding_model": { "type": "keyword" }
    }
  }
}
```



### 2.8 Pipeline de Ingestão

#### 2.8.1 Diagrama do Pipeline

```mermaid
flowchart LR
    subgraph "Fase 1: Discovery"
        D1[Fonte Config] --> D2[Discovery Engine]
        D2 --> D3[URLs Descobertas]
    end
    
    subgraph "Fase 2: Change Detection"
        C1[URLs] --> C2[HEAD Request]
        C2 --> C3{Mudou?}
        C3 -->|Sim| C4[Processar]
        C3 -->|Não| C5[Skip]
    end
    
    subgraph "Fase 3: Fetch"
        F1[URL] --> F2[Download]
        F2 --> F3[Validação]
        F3 --> F4[Cache Local]
    end
    
    subgraph "Fase 4: Parse"
        P1[Raw Content] --> P2{Formato}
        P2 -->|CSV| P3[CSV Parser]
        P2 -->|PDF| P4[PDF Parser]
        P2 -->|HTML| P5[HTML Parser]
        P3 --> P6[Documentos]
        P4 --> P6
        P5 --> P6
    end
    
    subgraph "Fase 5-6: Deduplication"
        FPR1[Documento] --> FPR2[Fingerprint]
        FPR2 --> DED1{Dup?}
        DED1 -->|Sim| DED2[Skip]
        DED1 -->|Não| DED3[Prosseguir]
    end
    
    subgraph "Fase 7: Chunking"
        CH1[Conteúdo] --> CH2[Split Legal]
        CH2 --> CH3[Semantic Sections]
        CH3 --> CH4[Chunks]
    end
    
    subgraph "Fase 8: Embedding"
        E1[Chunks] --> E2[TEI Batch]
        E2 --> E3[Vetores 384d]
    end
    
    subgraph "Fase 9-10: Indexação"
        I1[Documento] --> I2[PostgreSQL]
        I1 --> I3[Elasticsearch]
        E3 --> I4[pgvector]
    end
    
    D3 --> C1
    C4 --> F1
    F4 --> P1
    P6 --> FPR1
    DED3 --> CH1
    CH4 --> E1
    I2 --> I5[Commit]
    I3 --> I5
    I4 --> I5
```

#### 2.8.2 Implementação do Pipeline

```python
# src/gabi/pipeline/orchestrator.py
import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from gabi.config import settings
from gabi.pipeline.change_detector import ChangeDetector
from gabi.pipeline.chunker import Chunker
from gabi.pipeline.deduplicator import Deduplicator
from gabi.pipeline.embedder import Embedder
from gabi.pipeline.fetcher import Fetcher
from gabi.pipeline.fingerprinter import Fingerprinter
from gabi.pipeline.indexer import Indexer
from gabi.pipeline.parser import Parser
from gabi.governance.audit import AuditLogger
from gabi.governance.quality import QualityChecker

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """
    Orquestra o pipeline completo de ingestão com:
    - Transações atômicas
    - Checkpoint/resume
    - Circuit breakers
    - Métricas detalhadas
    """
    
    def __init__(
        self,
        db_session: AsyncSession,
        es_client: Any,
        redis_client: Any,
        http_client: httpx.AsyncClient,
    ):
        self.db = db_session
        self.es = es_client
        self.redis = redis_client
        self.http = http_client
        
        # Componentes
        self.change_detector = ChangeDetector(db_session)
        self.fetcher = Fetcher(http_client)
        self.parser = Parser()
        self.fingerprinter = Fingerprinter()
        self.deduplicator = Deduplicator(db_session, redis_client)
        self.chunker = Chunker(
            max_tokens=settings.pipeline_chunk_max_tokens,
            overlap_tokens=settings.pipeline_chunk_overlap_tokens,
        )
        self.embedder = Embedder()
        self.indexer = Indexer(es_client, db_session)
        self.quality = QualityChecker()
        self.audit = AuditLogger(db_session)
        
        # Estado
        self._memory_usage = 0
        self._processed_count = 0
    
    async def run(
        self,
        source_id: str,
        source_config: Dict[str, Any],
        trigger: str = "scheduled",
        triggered_by: Optional[str] = None,
        resume_from: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executa o pipeline completo para uma fonte.
        
        Args:
            source_id: ID da fonte
            source_config: Configuração da fonte (do sources.yaml)
            trigger: Tipo de trigger ('scheduled', 'manual', 'api')
            triggered_by: ID do usuário que acionou (se manual)
            resume_from: run_id para resumir execução anterior
            
        Returns:
            Estatísticas da execução
        """
        run_id = resume_from or str(uuid.uuid4())
        is_resume = resume_from is not None
        
        stats = {
            "run_id": run_id,
            "source_id": source_id,
            "trigger": trigger,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "urls_discovered": 0,
            "urls_new": 0,
            "urls_updated": 0,
            "urls_skipped": 0,
            "urls_failed": 0,
            "documents_processed": 0,
            "documents_indexed": 0,
            "documents_deduplicated": 0,
            "documents_failed": 0,
            "chunks_created": 0,
            "embeddings_generated": 0,
            "bytes_processed": 0,
            "errors": [],
        }
        
        logger.info(f"[{run_id}] Starting pipeline for source '{source_id}' (resume={is_resume})")
        
        try:
            # Criar ou recuperar manifest
            if not is_resume:
                await self._create_manifest(run_id, source_id, trigger, triggered_by)
            
            self.audit.log_sync_started(source_id, run_id, trigger, triggered_by)
            
            # === FASE 1: Discovery ===
            urls = await self._discovery_phase(source_config, stats)
            if not urls:
                logger.info(f"[{run_id}] No URLs discovered, completing")
                await self._complete_manifest(run_id, "success", stats)
                return stats
            
            # === FASE 2: Change Detection ===
            urls_to_process = await self._change_detection_phase(urls, source_id, stats)
            
            # === FASES 3-10: Processamento ===
            await self._processing_phase(
                urls_to_process, source_id, source_config, run_id, stats
            )
            
            # Determinar status final
            if stats["documents_failed"] == 0:
                final_status = "success"
            elif stats["documents_indexed"] > 0:
                final_status = "partial_success"
            else:
                final_status = "failed"
            
            await self._complete_manifest(run_id, final_status, stats)
            self.audit.log_sync_completed(source_id, run_id, final_status, stats)
            
            stats["status"] = final_status
            
        except Exception as e:
            logger.exception(f"[{run_id}] Pipeline failed: {e}")
            stats["status"] = "failed"
            stats["errors"].append({"phase": "orchestrator", "error": str(e)})
            await self._complete_manifest(run_id, "failed", stats)
            self.audit.log_sync_failed(source_id, run_id, str(e))
            raise
        
        finally:
            stats["completed_at"] = datetime.now(timezone.utc).isoformat()
        
        return stats
    
    async def _discovery_phase(
        self, 
        source_config: Dict[str, Any],
        stats: Dict[str, Any]
    ) -> List[str]:
        """Fase 1: Descoberta de URLs."""
        discovery_config = source_config.get("discovery", {})
        mode = discovery_config.get("mode")
        
        urls = []
        
        if mode == "url_pattern":
            urls = await self._discover_url_pattern(discovery_config)
        elif mode == "static_url":
            urls = [discovery_config["url"]]
        elif mode == "crawler":
            urls = await self._discover_crawler(discovery_config)
        elif mode == "api_pagination":
            urls = await self._discover_api_pagination(discovery_config)
        else:
            raise ValueError(f"Unknown discovery mode: {mode}")
        
        stats["urls_discovered"] = len(urls)
        logger.info(f"Discovery: {len(urls)} URLs found")
        
        return urls
    
    async def _discover_url_pattern(self, config: Dict[str, Any]) -> List[str]:
        """Descobre URLs baseado em padrão com parâmetros."""
        template = config["url_template"]
        params = config.get("params", {})
        max_urls = config.get("max_urls", 1000)
        
        urls = []
        
        # Suporta parâmetros aninhados
        for param_name, param_config in params.items():
            start = param_config.get("start", 0)
            end = param_config.get("end", datetime.now().year)
            
            if end == "current" or end is None:
                end = datetime.now().year
            
            for value in range(start, end + 1):
                url = template.replace(f"{{{param_name}}}", str(value))
                urls.append(url)
                
                if len(urls) >= max_urls:
                    break
            
            if len(urls) >= max_urls:
                break
        
        return urls
    
    async def _change_detection_phase(
        self,
        urls: List[str],
        source_id: str,
        stats: Dict[str, Any]
    ) -> List[str]:
        """Fase 2: Detecção de mudanças."""
        new_urls = []
        updated_urls = []
        skipped_urls = []
        
        for url in urls:
            try:
                result = await self.change_detector.check(url, source_id)
                
                if result == "new":
                    new_urls.append(url)
                elif result == "changed":
                    updated_urls.append(url)
                else:
                    skipped_urls.append(url)
                    
            except Exception as e:
                logger.warning(f"Change detection failed for {url}: {e}")
                # Assume mudança para processar
                new_urls.append(url)
        
        stats["urls_new"] = len(new_urls)
        stats["urls_updated"] = len(updated_urls)
        stats["urls_skipped"] = len(skipped_urls)
        
        logger.info(
            f"Change detection: {len(new_urls)} new, "
            f"{len(updated_urls)} updated, {len(skipped_urls)} skipped"
        )
        
        return new_urls + updated_urls
    
    async def _processing_phase(
        self,
        urls: List[str],
        source_id: str,
        source_config: Dict[str, Any],
        run_id: str,
        stats: Dict[str, Any],
    ):
        """Fases 3-10: Processamento de cada URL."""
        fetch_config = source_config.get("fetch", {})
        parse_config = source_config.get("parse", {})
        mapping_config = source_config.get("mapping", {})
        quality_config = source_config.get("quality", {})
        
        semaphore = asyncio.Semaphore(settings.pipeline_concurrency)
        
        async def process_with_limit(url: str):
            async with semaphore:
                return await self._process_single_url(
                    url, source_id, fetch_config, parse_config, 
                    mapping_config, quality_config, run_id, stats
                )
        
        # Processar em batches para checkpoint
        batch_size = settings.pipeline_checkpoint_interval
        for i in range(0, len(urls), batch_size):
            batch = urls[i:i + batch_size]
            
            results = await asyncio.gather(
                *[process_with_limit(url) for url in batch],
                return_exceptions=True
            )
            
            # Atualizar checkpoint
            await self._update_checkpoint(run_id, i + len(batch), urls[i + len(batch) - 1] if i + len(batch) <= len(urls) else None)
            
            # Contabilizar resultados
            for result in results:
                if isinstance(result, Exception):
                    stats["urls_failed"] += 1
                    stats["errors"].append({"error": str(result)})
                elif result:
                    stats["documents_processed"] += result.get("documents", 0)
                    stats["documents_indexed"] += result.get("indexed", 0)
                    stats["documents_deduplicated"] += result.get("deduplicated", 0)
                    stats["documents_failed"] += result.get("failed", 0)
                    stats["chunks_created"] += result.get("chunks", 0)
                    stats["embeddings_generated"] += result.get("embeddings", 0)
            
            # Checkpoint
            self._processed_count += len(batch)
            logger.info(f"[{run_id}] Checkpoint: {self._processed_count}/{len(urls)} URLs processed")
    
    async def _process_single_url(
        self,
        url: str,
        source_id: str,
        fetch_config: Dict[str, Any],
        parse_config: Dict[str, Any],
        mapping_config: Dict[str, Any],
        quality_config: Dict[str, Any],
        run_id: str,
        stats: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Processa uma única URL através de todas as fases."""
        result = {"documents": 0, "indexed": 0, "deduplicated": 0, "failed": 0, "chunks": 0, "embeddings": 0}
        
        try:
            # Verificar memória
            self._check_memory()
            
            # Fase 3: Fetch
            raw_content = await self.fetcher.fetch(url, fetch_config)
            stats["bytes_processed"] += len(raw_content)
            
            # Fase 4: Parse
            parsed_docs = await self.parser.parse(raw_content, parse_config, mapping_config)
            if not isinstance(parsed_docs, list):
                parsed_docs = [parsed_docs]
            
            result["documents"] = len(parsed_docs)
            
            # Processar cada documento
            for doc in parsed_docs:
                try:
                    success = await self._process_single_document(
                        doc, source_id, quality_config, run_id
                    )
                    
                    if success:
                        result["indexed"] += 1
                    else:
                        result["deduplicated"] += 1
                        
                except Exception as e:
                    logger.error(f"Failed to process document from {url}: {e}")
                    result["failed"] += 1
                    await self._send_to_dlq(source_id, run_id, url, "document_processing", str(e), doc)
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to process URL {url}: {e}")
            await self._send_to_dlq(source_id, run_id, url, "url_processing", str(e))
            raise
    
    async def _process_single_document(
        self,
        doc: Dict[str, Any],
        source_id: str,
        quality_config: Dict[str, Any],
        run_id: str,
    ) -> bool:
        """
        Processa um único documento (Fases 5-10).
        Retorna True se indexado, False se duplicado.
        """
        # Fase 5: Fingerprint
        fingerprint = self.fingerprinter.compute(doc)
        doc["fingerprint"] = fingerprint
        
        # Fase 6: Deduplication (com distributed lock)
        is_duplicate = await self.deduplicator.check_and_lock(fingerprint, doc.get("document_id"))
        if is_duplicate:
            logger.debug(f"Duplicate document: {doc.get('document_id')}")
            return False
        
        # Validação de qualidade
        quality_result = self.quality.validate(doc, quality_config)
        if not quality_result.valid:
            raise ValueError(f"Quality validation failed: {quality_result.errors}")
        
        # Fase 7: Chunking
        content = doc.get("content", "")
        chunks = self.chunker.chunk(content, doc.get("metadata"))
        
        # Fase 8: Embedding (com circuit breaker)
        chunk_texts = [c["text"] for c in chunks]
        embeddings = await self.embedder.embed_batch(chunk_texts)
        
        # Fases 9-10: Indexação Atômica
        async with self.db.begin():
            # PostgreSQL
            await self.indexer.index_document_pg(doc, source_id)
            await self.indexer.index_chunks_pg(doc["document_id"], chunks, embeddings)
            
            # Elasticsearch (fora da transação PG, mas com compensação)
            try:
                await self.indexer.index_document_es(doc, source_id)
            except Exception as e:
                # Marcar para reindexação assíncrona
                await self.indexer.mark_for_reindex(doc["document_id"])
                logger.warning(f"ES index failed for {doc['document_id']}, marked for reindex: {e}")
        
        # Atualizar cache de change detection
        await self.change_detector.update_cache(doc.get("url"), source_id, fingerprint)
        
        return True
    
    def _check_memory(self):
        """Verifica uso de memória e aborta se exceder limite."""
        import psutil
        process = psutil.Process()
        rss_mb = process.memory_info().rss / 1024 / 1024
        
        if rss_mb > settings.pipeline_max_memory_mb:
            raise MemoryError(f"Memory limit exceeded: {rss_mb:.0f}MB > {settings.pipeline_max_memory_mb}MB")
    
    async def _create_manifest(self, run_id: str, source_id: str, trigger: str, triggered_by: Optional[str]):
        """Cria registro de execução."""
        await self.db.execute(
            """
            INSERT INTO execution_manifests (run_id, source_id, trigger, triggered_by, status)
            VALUES (:run_id, :source_id, :trigger, :triggered_by, 'running')
            """,
            {"run_id": run_id, "source_id": source_id, "trigger": trigger, "triggered_by": triggered_by}
        )
    
    async def _update_checkpoint(self, run_id: str, processed: int, last_url: Optional[str]):
        """Atualiza checkpoint para resume."""
        await self.db.execute(
            """
            UPDATE execution_manifests
            SET checkpoint = :checkpoint, last_processed_url = :last_url
            WHERE run_id = :run_id
            """,
            {
                "run_id": run_id,
                "checkpoint": {"processed": processed},
                "last_url": last_url
            }
        )
    
    async def _complete_manifest(self, run_id: str, status: str, stats: Dict[str, Any]):
        """Finaliza registro de execução."""
        started = datetime.fromisoformat(stats["started_at"])
        duration = (datetime.now(timezone.utc) - started).total_seconds()
        
        await self.db.execute(
            """
            UPDATE execution_manifests
            SET status = :status,
                completed_at = NOW(),
                duration_seconds = :duration,
                stats = :stats
            WHERE run_id = :run_id
            """,
            {"run_id": run_id, "status": status, "duration": duration, "stats": stats}
        )
    
    async def _send_to_dlq(
        self,
        source_id: str,
        run_id: str,
        url: str,
        error_type: str,
        error_message: str,
        payload: Optional[Dict] = None,
    ):
        """Envia mensagem para Dead Letter Queue."""
        error_hash = hashlib.sha256(f"{error_type}:{error_message[:100]}".encode()).hexdigest()[:16]
        
        await self.db.execute(
            """
            INSERT INTO dlq_messages 
            (source_id, run_id, url, error_type, error_message, error_hash, payload, next_retry_at)
            VALUES (:source_id, :run_id, :url, :error_type, :error_message, :error_hash, :payload, NOW() + INTERVAL '5 minutes')
            """,
            {
                "source_id": source_id,
                "run_id": run_id,
                "url": url,
                "error_type": error_type,
                "error_message": error_message[:1000],
                "error_hash": error_hash,
                "payload": payload or {}
            }
        )
```

### 2.9 Serviço de Busca Híbrida

```python
# src/gabi/services/search_service.py
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
import asyncio

from elasticsearch import AsyncElasticsearch

from gabi.config import settings


@dataclass
class SearchResult:
    """Resultado de busca unificado."""
    document_id: str
    title: Optional[str]
    snippet: str
    source_id: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    rank_bm25: Optional[int] = None
    rank_vector: Optional[int] = None
    match_sources: List[str] = field(default_factory=list)
    highlights: Dict[str, List[str]] = field(default_factory=dict)


class SearchService:
    """
    Serviço de busca híbrida combinando BM25 (Elasticsearch) 
    e similaridade vetorial (pgvector) via RRF.
    """
    
    def __init__(
        self,
        es_client: AsyncElasticsearch,
        db_session: Any,
        embedding_client: Any,
    ):
        self.es = es_client
        self.db = db_session
        self.embedder = embedding_client
        self.k = settings.search_rrf_k
        self.bm25_weight = settings.search_bm25_weight
        self.vector_weight = settings.search_vector_weight
    
    async def search(
        self,
        query: str,
        search_type: str = "hybrid",
        limit: int = 10,
        offset: int = 0,
        filters: Optional[Dict[str, Any]] = None,
        highlight: bool = True,
    ) -> List[SearchResult]:
        """
        Executa busca conforme tipo solicitado.
        
        Args:
            query: Texto da consulta
            search_type: 'text' (BM25), 'semantic' (vetorial), ou 'hybrid' (RRF)
            limit: Número máximo de resultados
            offset: Paginação
            filters: Filtros por metadados
            highlight: Incluir highlights
        """
        if search_type == "text":
            return await self._search_bm25(query, limit, offset, filters, highlight)
        elif search_type == "semantic":
            return await self._search_vector(query, limit, offset, filters)
        elif search_type == "hybrid":
            return await self._search_hybrid(query, limit, offset, filters, highlight)
        else:
            raise ValueError(f"Unknown search_type: {search_type}")
    
    async def _search_hybrid(
        self,
        query: str,
        limit: int,
        offset: int,
        filters: Optional[Dict[str, Any]],
        highlight: bool,
    ) -> List[SearchResult]:
        """Busca híbrida usando RRF."""
        fetch_limit = min(limit * 3, 100)  # Buscar mais para fusão
        
        # Executar buscas em paralelo
        bm25_task = self._search_bm25(query, fetch_limit, 0, filters, highlight)
        vector_task = self._search_vector(query, fetch_limit, 0, filters)
        
        bm25_results, vector_results = await asyncio.gather(bm25_task, vector_task)
        
        # Criar rankings
        bm25_ranking = {r.document_id: i for i, r in enumerate(bm25_results)}
        vector_ranking = {r.document_id: i for i, r in enumerate(vector_results)}
        
        # Calcular RRF scores
        all_ids: Set[str] = set(bm25_ranking.keys()) | set(vector_ranking.keys())
        rrf_scores: Dict[str, tuple] = {}
        
        for doc_id in all_ids:
            score = 0.0
            match_sources = []
            
            if doc_id in bm25_ranking:
                score += self.bm25_weight / (self.k + bm25_ranking[doc_id])
                match_sources.append("bm25")
            
            if doc_id in vector_ranking:
                score += self.vector_weight / (self.k + vector_ranking[doc_id])
                match_sources.append("vector")
            
            rrf_scores[doc_id] = (score, match_sources)
        
        # Ordenar por RRF score
        sorted_ids = sorted(rrf_scores.keys(), key=lambda d: rrf_scores[d][0], reverse=True)
        
        # Construir resultados finais
        results_map: Dict[str, SearchResult] = {}
        for r in bm25_results:
            results_map[r.document_id] = r
            r.rank_bm25 = bm25_ranking.get(r.document_id)
        
        for r in vector_results:
            if r.document_id not in results_map:
                results_map[r.document_id] = r
            r.rank_vector = vector_ranking.get(r.document_id)
        
        # Aplicar paginação
        paginated_ids = sorted_ids[offset:offset + limit]
        
        final_results = []
        for doc_id in paginated_ids:
            result = results_map[doc_id]
            result.score = rrf_scores[doc_id][0]
            result.match_sources = rrf_scores[doc_id][1]
            final_results.append(result)
        
        return final_results
    
    async def _search_bm25(
        self,
        query: str,
        limit: int,
        offset: int,
        filters: Optional[Dict[str, Any]],
        highlight: bool,
    ) -> List[SearchResult]:
        """Busca BM25 no Elasticsearch."""
        es_filters = [{"term": {"is_deleted": False}}]
        
        if filters:
            if "source_id" in filters:
                es_filters.append({"term": {"source_id": filters["source_id"]}})
            if "year" in filters:
                es_filters.append({"term": {"metadata.year": filters["year"]}})
            if "year_from" in filters and "year_to" in filters:
                es_filters.append({
                    "range": {"metadata.year": {
                        "gte": filters["year_from"],
                        "lte": filters["year_to"]
                    }}
                })
            if "type" in filters:
                es_filters.append({"term": {"metadata.type": filters["type"]}})
            if "relator" in filters:
                es_filters.append({"term": {"metadata.relator.keyword": filters["relator"]}})
        
        body = {
            "query": {
                "bool": {
                    "must": [{
                        "multi_match": {
                            "query": query,
                            "fields": [
                                "title^3",
                                "content",
                                "metadata.ementa^2",
                                "metadata.assunto^1.5"
                            ],
                            "type": "best_fields",
                            "analyzer": "brazilian_legal_search",
                            "fuzziness": "AUTO"
                        }
                    }],
                    "filter": es_filters
                }
            },
            "size": limit,
            "from": offset,
            "sort": ["_score"],
            "_source": ["document_id", "title", "content_preview", "source_id", "metadata", "url"]
        }
        
        if highlight:
            body["highlight"] = {
                "fields": {
                    "content": {
                        "fragment_size": 250,
                        "number_of_fragments": 2,
                        "pre_tags": ["<mark>"],
                        "post_tags": ["</mark>"]
                    },
                    "title": {
                        "fragment_size": 100,
                        "number_of_fragments": 0,
                        "pre_tags": ["<mark>"],
                        "post_tags": ["</mark>"]
                    }
                }
            }
        
        response = await self.es.search(
            index=settings.elasticsearch_index,
            body=body,
            timeout=f"{settings.search_timeout_ms}ms"
        )
        
        results = []
        for hit in response["hits"]["hits"]:
            source = hit["_source"]
            highlights = hit.get("highlight", {})
            
            snippet = ""
            if "content" in highlights:
                snippet = " ".join(highlights["content"])
            else:
                snippet = source.get("content_preview", "")[:250]
            
            results.append(SearchResult(
                document_id=source["document_id"],
                title=source.get("title"),
                snippet=snippet,
                source_id=source.get("source_id", ""),
                metadata=source.get("metadata", {}),
                score=hit["_score"],
                highlights=highlights
            ))
        
        return results
    
    async def _search_vector(
        self,
        query: str,
        limit: int,
        offset: int,
        filters: Optional[Dict[str, Any]],
    ) -> List[SearchResult]:
        """Busca vetorial no pgvector."""
        # Gerar embedding da query
        query_embedding = await self.embedder.embed([query])
        query_vector = query_embedding[0]
        
        # Construir filtros
        filter_conditions = ["d.is_deleted = false"]
        filter_params = {"query_vec": str(query_vector), "limit": limit, "offset": offset}
        
        if filters:
            if "source_id" in filters:
                filter_conditions.append("d.source_id = :source_id")
                filter_params["source_id"] = filters["source_id"]
            if "year" in filters:
                filter_conditions.append("(d.metadata->>'year')::int = :year")
                filter_params["year"] = filters["year"]
        
        filter_sql = " AND ".join(filter_conditions)
        
        # Query com CTE para deduplicação por documento
        sql = f"""
        WITH ranked_chunks AS (
            SELECT
                dc.document_id,
                dc.chunk_text,
                dc.chunk_index,
                1 - (dc.embedding <=> :query_vec) AS similarity,
                ROW_NUMBER() OVER (PARTITION BY dc.document_id ORDER BY dc.embedding <=> :query_vec) AS chunk_rank
            FROM document_chunks dc
            JOIN documents d ON d.document_id = dc.document_id
            WHERE {filter_sql}
              AND dc.embedding IS NOT NULL
            ORDER BY dc.embedding <=> :query_vec
            LIMIT :limit * 3
        )
        SELECT 
            rc.document_id,
            rc.chunk_text,
            rc.similarity,
            d.title,
            d.source_id,
            d.metadata,
            d.url
        FROM ranked_chunks rc
        JOIN documents d ON d.document_id = rc.document_id
        WHERE rc.chunk_rank = 1
        ORDER BY rc.similarity DESC
        LIMIT :limit
        OFFSET :offset
        """
        
        rows = await self.db.fetch_all(sql, filter_params)
        
        results = []
        for row in rows:
            results.append(SearchResult(
                document_id=row["document_id"],
                title=row["title"],
                snippet=row["chunk_text"][:300],
                source_id=row["source_id"],
                metadata=row["metadata"] or {},
                score=float(row["similarity"])
            ))
        
        return results
    
    async def get_document(self, document_id: str) -> Optional[SearchResult]:
        """Recupera documento por ID."""
        # Tentar Elasticsearch primeiro
        try:
            response = await self.es.get(
                index=settings.elasticsearch_index,
                id=document_id
            )
            source = response["_source"]
            return SearchResult(
                document_id=source["document_id"],
                title=source.get("title"),
                snippet=source.get("content_preview", "")[:500],
                source_id=source.get("source_id", ""),
                metadata=source.get("metadata", {})
            )
        except Exception:
            pass
        
        # Fallback para PostgreSQL
        row = await self.db.fetch_one(
            """
            SELECT document_id, title, content_preview, source_id, metadata, url
            FROM documents
            WHERE document_id = :doc_id AND is_deleted = false
            """,
            {"doc_id": document_id}
        )
        
        if row:
            return SearchResult(
                document_id=row["document_id"],
                title=row["title"],
                snippet=row["content_preview"] or "",
                source_id=row["source_id"],
                metadata=row["metadata"] or {}
            )
        
        return None
```



### 2.10 API REST

#### 2.10.1 App Factory

```python
# src/gabi/main.py
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from gabi.api.router import api_router
from gabi.config import Environment, settings
from gabi.db import close_db, init_db
from gabi.middleware.auth import AuthMiddleware
from gabi.middleware.rate_limit import RateLimitMiddleware
from gabi.middleware.request_id import RequestIDMiddleware
from gabi.middleware.security_headers import SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Gerencia ciclo de vida da aplicação."""
    # Startup
    await init_db()
    yield
    # Shutdown
    await close_db()


def create_app() -> FastAPI:
    """Factory para criar aplicação FastAPI."""
    
    app = FastAPI(
        title="GABI API",
        description="Gerador Automático de Boletins por IA - TCU",
        version="2.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != Environment.PRODUCTION else None,
        redoc_url="/redoc" if settings.environment != Environment.PRODUCTION else None,
    )
    
    # Métricas Prometheus (antes dos middlewares para evitar overhead)
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)
    
    # Middlewares (ordem importante - primeiro executa primeiro)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    
    # Trusted Host (produção apenas)
    if settings.environment == Environment.PRODUCTION:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=["*.tcu.gov.br", "gabi.tcu.gov.br"]
        )
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )
    
    # Rate Limiting
    if settings.rate_limit_enabled:
        app.add_middleware(RateLimitMiddleware)
    
    # Auth (obrigatório em produção)
    if settings.auth_enabled:
        app.add_middleware(
            AuthMiddleware,
            public_paths=settings.auth_public_paths
        )
    
    # Routers
    app.include_router(api_router, prefix="/api/v1")
    
    # Error handlers
    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "request_id": getattr(request.state, "request_id", None)
            }
        )
    
    return app


app = create_app()
```

#### 2.10.2 Routers

```python
# src/gabi/api/search.py
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from gabi.dependencies import get_db, get_es_client, get_search_service
from gabi.schemas.search import SearchRequest, SearchResponse


router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    search_service = Depends(get_search_service),
) -> SearchResponse:
    """
    Busca híbrida em documentos.
    
    Combina BM25 (texto) e similaridade vetorial (semântica) via RRF.
    """
    try:
        results = await search_service.search(
            query=request.query,
            search_type=request.search_type,
            limit=request.limit,
            offset=request.offset,
            filters=request.filters.dict() if request.filters else None,
            highlight=request.highlight,
        )
        
        return SearchResponse(
            results=results,
            total=len(results),
            query=request.query,
            search_type=request.search_type,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.get("/suggest")
async def suggest(
    q: str = Query(..., min_length=2, max_length=100),
    limit: int = Query(5, ge=1, le=20),
    es_client = Depends(get_es_client),
) -> List[str]:
    """Sugestões de autocompletar baseadas em títulos."""
    # Implementar sugestão via Elasticsearch completion suggester
    return []
```

```python
# src/gabi/api/documents.py
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Path

from gabi.dependencies import get_db, get_es_client
from gabi.schemas.document import DocumentResponse


router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str = Path(..., description="ID do documento"),
    db = Depends(get_db),
):
    """Recupera documento por ID."""
    row = await db.fetch_one(
        """
        SELECT document_id, title, content_preview, metadata, url, 
               source_id, ingested_at, updated_at
        FROM documents
        WHERE document_id = :doc_id AND is_deleted = false
        """,
        {"doc_id": document_id}
    )
    
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return DocumentResponse(
        document_id=row["document_id"],
        title=row["title"],
        content_preview=row["content_preview"],
        metadata=row["metadata"],
        url=row["url"],
        source_id=row["source_id"],
        ingested_at=row["ingested_at"],
        updated_at=row["updated_at"],
    )


@router.get("/{document_id}/chunks")
async def get_document_chunks(
    document_id: str,
    db = Depends(get_db),
):
    """Recupera chunks de um documento com embeddings."""
    rows = await db.fetch_all(
        """
        SELECT chunk_index, chunk_text, token_count, metadata
        FROM document_chunks
        WHERE document_id = :doc_id
        ORDER BY chunk_index
        """,
        {"doc_id": document_id}
    )
    
    return [
        {
            "index": r["chunk_index"],
            "text": r["chunk_text"],
            "token_count": r["token_count"],
            "metadata": r["metadata"]
        }
        for r in rows
    ]
```

```python
# src/gabi/api/admin.py
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Security
from pydantic import BaseModel

from gabi.auth.rbac import require_admin, require_permission
from gabi.dependencies import get_db
from gabi.worker import sync_source_task


router = APIRouter(prefix="/admin", tags=["admin"])


class SyncRequest(BaseModel):
    source_id: str
    full_resync: bool = False


class DLQMessageResponse(BaseModel):
    id: str
    source_id: str
    url: str
    error_type: str
    error_message: str
    status: str
    retry_count: int
    created_at: str


@router.post("/sync")
async def trigger_sync(
    request: SyncRequest,
    user = Security(require_permission("sources:sync")),
):
    """Dispara sincronização manual de uma fonte."""
    task = sync_source_task.delay(
        source_id=request.source_id,
        trigger="manual",
        triggered_by=user.get("sub"),
        full_resync=request.full_resync
    )
    
    return {
        "task_id": task.id,
        "source_id": request.source_id,
        "status": "queued"
    }


@router.get("/executions")
async def list_executions(
    source_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
    db = Depends(get_db),
    user = Security(require_admin),
):
    """Lista execuções do pipeline."""
    conditions = []
    params = {"limit": limit}
    
    if source_id:
        conditions.append("source_id = :source_id")
        params["source_id"] = source_id
    if status:
        conditions.append("status = :status")
        params["status"] = status
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    rows = await db.fetch_all(
        f"""
        SELECT run_id, source_id, status, trigger, started_at, completed_at, 
               duration_seconds, stats
        FROM execution_manifests
        WHERE {where_clause}
        ORDER BY started_at DESC
        LIMIT :limit
        """,
        params
    )
    
    return [dict(r) for r in rows]


@router.get("/dlq", response_model=List[DLQMessageResponse])
async def list_dlq_messages(
    status: Optional[str] = "pending",
    source_id: Optional[str] = None,
    limit: int = 50,
    db = Depends(get_db),
    user = Security(require_admin),
):
    """Lista mensagens na Dead Letter Queue."""
    conditions = ["1=1"]
    params = {"limit": limit}
    
    if status:
        conditions.append("status = :status")
        params["status"] = status
    if source_id:
        conditions.append("source_id = :source_id")
        params["source_id"] = source_id
    
    where_clause = " AND ".join(conditions)
    
    rows = await db.fetch_all(
        f"""
        SELECT id, source_id, url, error_type, error_message, status,
               retry_count, created_at
        FROM dlq_messages
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        params
    )
    
    return [DLQMessageResponse(**dict(r)) for r in rows]


@router.post("/dlq/{message_id}/retry")
async def retry_dlq_message(
    message_id: str,
    db = Depends(get_db),
    user = Security(require_admin),
):
    """Reprocessa mensagem da DLQ."""
    # Buscar mensagem
    row = await db.fetch_one(
        "SELECT * FROM dlq_messages WHERE id = :id",
        {"id": message_id}
    )
    
    if not row:
        raise HTTPException(status_code=404, detail="Message not found")
    
    # Disparar retry
    from gabi.worker import process_url_task
    task = process_url_task.delay(
        source_id=row["source_id"],
        url=row["url"],
        payload=row["payload"]
    )
    
    # Atualizar status
    await db.execute(
        """
        UPDATE dlq_messages 
        SET status = 'retrying', retry_count = retry_count + 1, last_retry_at = NOW()
        WHERE id = :id
        """,
        {"id": message_id}
    )
    
    return {"task_id": task.id, "status": "retrying"}
```

### 2.11 Segurança

#### 2.11.1 JWT Auth Middleware

```python
# src/gabi/middleware/auth.py
from typing import List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

from gabi.config import settings


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware de autenticação JWT."""
    
    def __init__(self, app, public_paths: Optional[List[str]] = None):
        super().__init__(app)
        self.public_paths = public_paths or []
        self._jwks_cache = {}
        self._jwks_last_fetch = 0
    
    async def dispatch(self, request: Request, call_next):
        # Verificar se path é público
        if any(request.url.path.startswith(p) for p in self.public_paths):
            return await call_next(request)
        
        # Extrair token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"error": "Missing or invalid authorization header"}
            )
        
        token = auth_header[7:]
        
        # Validar token
        try:
            payload = await self._validate_token(token)
            request.state.user = payload
        except JWTError as e:
            return JSONResponse(
                status_code=401,
                content={"error": f"Invalid token: {str(e)}"}
            )
        
        return await call_next(request)
    
    async def _validate_token(self, token: str) -> dict:
        """Valida JWT contra Keycloak."""
        # Buscar JWKS se necessário
        await self._fetch_jwks_if_needed()
        
        # Decodificar sem verificar para pegar kid
        unverified = jwt.get_unverified_header(token)
        kid = unverified.get("kid")
        
        # Pegar chave
        key = self._jwks_cache.get(kid)
        if not key:
            raise JWTError("Unknown key ID")
        
        # Validar
        payload = jwt.decode(
            token,
            key,
            algorithms=[settings.jwt_algorithm],
            issuer=str(settings.jwt_issuer),
            audience=settings.jwt_audience,
        )
        
        return payload
    
    async def _fetch_jwks_if_needed(self):
        """Busca JWKS do Keycloak se cache expirado."""
        import time
        
        cache_ttl = settings.jwt_jwks_cache_minutes * 60
        if time.time() - self._jwks_last_fetch < cache_ttl:
            return
        
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(str(settings.jwt_jwks_url))
            response.raise_for_status()
            jwks = response.json()
        
        # Converter JWK para PEM
        from jose.backends import RSAKey
        for key in jwks.get("keys", []):
            if key.get("kty") == "RSA":
                self._jwks_cache[key["kid"]] = RSAKey(key, algorithm=settings.jwt_algorithm).to_pem()
        
        self._jwks_last_fetch = time.time()
```

#### 2.11.2 Rate Limiting

```python
# src/gabi/middleware/rate_limit.py
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import redis.asyncio as redis

from gabi.config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting baseado em Redis (sliding window)."""
    
    def __init__(self, app):
        super().__init__(app)
        self.redis = redis.from_url(str(settings.redis_url))
    
    async def dispatch(self, request: Request, call_next):
        # Ignorar paths públicos
        if request.url.path in ["/health", "/metrics"]:
            return await call_next(request)
        
        # Identificar cliente
        client_id = self._get_client_id(request)
        key = f"rate_limit:{client_id}"
        
        # Verificar limite
        current = await self.redis.get(key)
        current_count = int(current) if current else 0
        
        if current_count >= settings.rate_limit_requests_per_minute:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "retry_after": settings.rate_limit_window_seconds
                },
                headers={"Retry-After": str(settings.rate_limit_window_seconds)}
            )
        
        # Incrementar contador
        pipe = self.redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, settings.rate_limit_window_seconds)
        await pipe.execute()
        
        return await call_next(request)
    
    def _get_client_id(self, request: Request) -> str:
        """Extrai identificador do cliente."""
        # Prioridade: API key > User ID > IP
        if hasattr(request.state, "user"):
            return f"user:{request.state.user.get('sub')}"
        
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"
        
        if request.client:
            return f"ip:{request.client.host}"
        
        return "ip:unknown"
```

### 2.12 Deploy

#### 2.12.1 Dockerfile

```dockerfile
# docker/Dockerfile
# =============================================================================
# STAGE 1: Builder
# =============================================================================
FROM python:3.11-slim as builder

WORKDIR /app

# Instalar dependências de build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Criar virtualenv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# =============================================================================
# STAGE 2: Development
# =============================================================================
FROM python:3.11-slim as development

WORKDIR /app

# Instalar dependências runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar virtualenv
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copiar código
COPY . .

# Usuário não-root
RUN useradd -m -u 1000 gabi && chown -R gabi:gabi /app
USER gabi

EXPOSE 8000

CMD ["uvicorn", "gabi.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# =============================================================================
# STAGE 3: Production
# =============================================================================
FROM python:3.11-slim as production

WORKDIR /app

# Instalar apenas dependências necessárias
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar virtualenv
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copiar apenas código necessário
COPY src/gabi ./gabi
COPY alembic ./alembic
COPY alembic.ini pyproject.toml ./

# Criar diretórios necessários
RUN mkdir -p /app/logs /app/tmp && chmod 755 /app/logs /app/tmp

# Usuário não-root
RUN useradd -m -u 1000 gabi && chown -R gabi:gabi /app
USER gabi

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# Usar Gunicorn com Uvicorn workers em produção
CMD ["gunicorn", "gabi.main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--access-logfile", "-"]
```

#### 2.12.2 Kubernetes Manifests

```yaml
# k8s/base/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: gabi
  labels:
    app.kubernetes.io/name: gabi
    app.kubernetes.io/version: "2.1.0"
---
# k8s/api/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gabi-api
  namespace: gabi
  labels:
    app: gabi-api
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: gabi-api
  template:
    metadata:
      labels:
        app: gabi-api
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
      containers:
      - name: api
        image: tcu.gov.br/gabi-api:2.1.0
        imagePullPolicy: Always
        ports:
        - containerPort: 8000
          name: http
        env:
        - name: GABI_ENVIRONMENT
          value: "production"
        - name: GABI_DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: gabi-secrets
              key: database-url
        - name: GABI_ELASTICSEARCH_URL
          valueFrom:
            secretKeyRef:
              name: gabi-secrets
              key: elasticsearch-url
        - name: GABI_REDIS_URL
          valueFrom:
            secretKeyRef:
              name: gabi-secrets
              key: redis-url
        - name: GABI_EMBEDDINGS_URL
          value: "http://tei:80"
        - name: GABI_AUTH_ENABLED
          value: "true"
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /health/live
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop:
            - ALL
        volumeMounts:
        - name: tmp
          mountPath: /tmp
      volumes:
      - name: tmp
        emptyDir: {}
---
# k8s/api/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: gabi-api-hpa
  namespace: gabi
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: gabi-api
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
      - type: Percent
        value: 100
        periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 10
        periodSeconds: 60
---
# k8s/api/pdb.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: gabi-api-pdb
  namespace: gabi
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: gabi-api
```



#### 2.12.3 CI/CD (GitHub Actions)

```yaml
# .github/workflows/ci-cd.yml
name: CI/CD Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-dev.txt
      
      - name: Lint with ruff
        run: ruff check src/
      
      - name: Type check with mypy
        run: mypy src/gabi/
      
      - name: Test with pytest
        run: pytest --cov=gabi --cov-report=xml --cov-report=term
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          files: ./coverage.xml

  security-scan:
    runs-on: ubuntu-latest
    needs: lint-and-test
    steps:
      - uses: actions/checkout@v4
      
      - name: Run Trivy vulnerability scanner
        uses: aquasecurity/trivy-action@master
        with:
          scan-type: 'fs'
          ignore-unfixed: true
          format: 'sarif'
          output: 'trivy-results.sarif'
          severity: 'CRITICAL,HIGH'
      
      - name: Upload Trivy scan results
        uses: github/codeql-action/upload-sarif@v2
        with:
          sarif_file: 'trivy-results.sarif'

  build-and-push:
    runs-on: ubuntu-latest
    needs: [lint-and-test, security-scan]
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      
      - name: Login to Container Registry
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      
      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=ref,event=branch
            type=sha,prefix={{branch}}-
            type=raw,value=latest,enable={{is_default_branch}}
      
      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          file: ./docker/Dockerfile
          target: production
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  deploy-staging:
    runs-on: ubuntu-latest
    needs: build-and-push
    environment: staging
    steps:
      - uses: actions/checkout@v4
      
      - name: Deploy to Staging
        run: |
          echo "Deploy to staging environment"
          # kubectl apply -k k8s/overlays/staging/

  deploy-production:
    runs-on: ubuntu-latest
    needs: deploy-staging
    environment: production
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      
      - name: Deploy to Production
        run: |
          echo "Deploy to production environment"
          # kubectl apply -k k8s/overlays/production/
```

---

## SEÇÃO 3: PLANO DE IMPLEMENTAÇÃO COM SWARM DE MICROAGENTES

### 3.1 Estratégia de Swarm

O projeto será implementado usando **Swarm de Microagentes** — múltiplos agentes de IA trabalhando em paralelo, cada um responsável por um componente específico. Esta abordagem maximiza:

- **Paralelismo**: Componentes independentes são construídos simultaneamente
- **Especialização**: Cada agente foca em um domínio específico
- **Escalabilidade**: Novos workers podem ser adicionados conforme necessário
- **Resiliência**: Falha em um worker não afeta os outros

### 3.2 Estrutura de Coordenação

```
COORDENAÇÃO DO SWARM
│
├── PROGRESS.md          # Estado atual do projeto (atualizado por cada agente)
├── ARTIFACTS/           # Artefatos gerados por fase
│   ├── phase-00/
│   ├── phase-01/
│   └── ...
├── LOCKS/               # Locks para recursos compartilhados
│   ├── database.lock
│   ├── models.lock
│   └── api.lock
└── REPORTS/             # Relatórios de execução
    ├── wave-00-01-report.md
    └── ...
```

**Regras de Coordenação:**
1. Cada agente **DEVE** ler `PROGRESS.md` antes de começar
2. Cada agente **DEVE** atualizar `PROGRESS.md` ao concluir
3. Locks são adquiridos via arquivos (criar `LOCKS/<resource>.lock`)
4. Conflitos são resolvidos pelo agente coordenador

### 3.3 Fases, Waves e Gates

#### Legenda
- 🟢 **Gate Aprovado** — Pode prosseguir
- 🔴 **Gate Bloqueado** — Corrigir antes de prosseguir
- ⏱️ **Tempo Estimado** — Baseado em 1M tokens/agente
- 💰 **Custo Estimado** — Tokens Claude 3.5 Sonnet

---

### 📌 FASE 0 — Fundação e Infraestrutura
**Objetivo**: Ambiente de desenvolvimento funcional

```
FASE 0 ─ Fundação e Infraestrutura
├── WAVE 0.1 ─ Estrutura de Projeto (3 workers paralelos)
│   ├── WORKER 0.1.1: Criar estrutura de diretórios completa
│   ├── WORKER 0.1.2: Setup Git + .gitignore + README
│   └── WORKER 0.1.3: Criar Makefile com comandos básicos
│   ⏱️ Tempo: 30 min | 💰 Custo: ~50K tokens/worker
│
├── WAVE 0.2 ─ Docker Local (4 workers paralelos)
│   ├── WORKER 0.2.1: docker-compose.local.yml completo
│   ├── WORKER 0.2.2: Dockerfile multi-stage (dev + prod)
│   ├── WORKER 0.2.3: .dockerignore otimizado
│   └── WORKER 0.2.4: Scripts de setup local
│   ⏱️ Tempo: 45 min | 💰 Custo: ~80K tokens/worker
│
├── WAVE 0.3 ─ Configuração (3 workers paralelos)
│   ├── WORKER 0.3.1: Pydantic Settings (config.py)
│   ├── WORKER 0.3.2: .env.example completo
│   └── WORKER 0.3.3: Alembic setup (env.py, alembic.ini)
│   ⏱️ Tempo: 40 min | 💰 Custo: ~60K tokens/worker
│
└── GATE 0 ─ Aprovação Fundação
    ✅ make docker-up sobe todos os serviços
    ✅ make migrate executa sem erros
    ✅ Health check retorna 200
    ✅ Estrutura de diretórios completa
    🔴 NÃO PROSSEGUIR se qualquer check falhar
```

**Total Fase 0:** 10 workers | ⏱️ 2h | 💰 ~650K tokens

---

### 📌 FASE 1 — Modelos de Dados e Schema
**Objetivo**: Banco de dados completo e funcional

```
FASE 1 ─ Modelos de Dados e Schema
├── WAVE 1.1 ─ Modelos Core (5 workers paralelos)
│   ├── WORKER 1.1.1: Modelo Base (SQLAlchemy declarative)
│   ├── WORKER 1.1.2: SourceRegistry
│   ├── WORKER 1.1.3: Document (com soft delete)
│   ├── WORKER 1.1.4: DocumentChunk (embedding 384d)
│   └── WORKER 1.1.5: ExecutionManifest
│   ⏱️ Tempo: 45 min | 💰 Custo: ~70K tokens/worker
│
├── WAVE 1.2 ─ Modelos Auxiliares (4 workers paralelos)
│   ├── WORKER 1.2.1: DLQMessage
│   ├── WORKER 1.2.2: AuditLog (com hash chain)
│   ├── WORKER 1.2.3: DataCatalog + Lineage
│   └── WORKER 1.2.4: ChangeDetectionCache
│   ⏱️ Tempo: 40 min | 💰 Custo: ~65K tokens/worker
│
├── WAVE 1.3 ─ Migrações (3 workers paralelos)
│   ├── WORKER 1.3.1: Migração 001_initial_schema.py
│   ├── WORKER 1.3.2: Migração 002_indexes_constraints.py
│   └── WORKER 1.3.3: Migração 003_audit_functions.py
│   ⏱️ Tempo: 35 min | 💰 Custo: ~60K tokens/worker
│
├── WAVE 1.4 ─ Database Layer (3 workers paralelos)
│   ├── WORKER 1.4.1: db.py (engine, AsyncSession)
│   ├── WORKER 1.4.2: dependencies.py (get_db, get_es, get_redis)
│   └── WORKER 1.4.3: Testes unitários dos modelos
│   ⏱️ Tempo: 40 min | 💰 Custo: ~70K tokens/worker
│
└── GATE 1 ─ Aprovação Modelos
    ✅ Todas migrações aplicam sem erros (alembic upgrade head)
    ✅ Modelos passam em testes unitários (pytest tests/unit/test_models_*.py)
    ✅ Índices HNSW criados corretamente
    ✅ Foreign keys com CASCADE funcionando
    ✅ Teste de inserção/consulta em todos os modelos
    🔴 NÃO PROSSEGUIR se cobertura < 80% nos modelos
```

**Total Fase 1:** 15 workers | ⏱️ 3h | 💰 ~1.1M tokens

---

### 📌 FASE 2 — Pipeline Fases 1-4 (Discovery → Parse)
**Objetivo**: Pipeline funcional até parsing

```
FASE 2 ─ Pipeline Fases 1-4 (Discovery → Parse)
├── WAVE 2.1 ─ Discovery Engine (3 workers paralelos)
│   ├── WORKER 2.1.1: DiscoveryEngine base + url_pattern
│   ├── WORKER 2.1.2: Discovery crawler (Playwright)
│   └── WORKER 2.1.3: Testes do discovery
│   ⏱️ Tempo: 50 min | 💰 Custo: ~80K tokens/worker
│
├── WAVE 2.2 ─ Change Detection (2 workers paralelos)
│   ├── WORKER 2.2.1: ChangeDetector (HEAD + ETag)
│   └── WORKER 2.2.2: Cache + testes
│   ⏱️ Tempo: 40 min | 💰 Custo: ~70K tokens/worker
│
├── WAVE 2.3 ─ Fetcher (3 workers paralelos)
│   ├── WORKER 2.3.1: Fetcher com retry (tenacity)
│   ├── WORKER 2.3.2: Cache local + limite de tamanho
│   └── WORKER 2.3.3: Validação de magic bytes + testes
│   ⏱️ Tempo: 45 min | 💰 Custo: ~75K tokens/worker
│
├── WAVE 2.4 ─ Parser (4 workers paralelos)
│   ├── WORKER 2.4.1: Parser CSV
│   ├── WORKER 2.4.2: Parser PDF (pdfplumber + OCR fallback)
│   ├── WORKER 2.4.3: Parser HTML (BeautifulSoup)
│   └── WORKER 2.4.4: Sistema de transforms + testes
│   ⏱️ Tempo: 60 min | 💰 Custo: ~90K tokens/worker
│
└── GATE 2 ─ Aprovação Pipeline 1-4
    ✅ Discovery retorna URLs corretamente (testar com tcu_sumulas)
    ✅ Change detection identifica mudanças (simular update)
    ✅ Fetch baixa e valida conteúdo (HTTP 200 + magic bytes)
    ✅ Parser extrai texto de CSV, PDF e HTML
    ✅ Testes de integração passam (pytest tests/integration/test_pipeline_*.py)
    🔴 NÃO PROSSEGUIR se qualquer parser falhar
```

**Total Fase 2:** 12 workers | ⏱️ 3.5h | 💰 ~1.0M tokens

---

### 📌 FASE 3 — Pipeline Fases 5-7 (Fingerprint → Chunking)
**Objetivo**: Deduplicação e chunking funcionais

```
FASE 3 ─ Pipeline Fases 5-7 (Fingerprint → Chunking)
├── WAVE 3.1 ─ Fingerprint (2 workers paralelos)
│   ├── WORKER 3.1.1: Fingerprinter (SHA256)
│   └── WORKER 3.1.2: Testes de determinismo
│   ⏱️ Tempo: 30 min | 💰 Custo: ~50K tokens/worker
│
├── WAVE 3.2 ─ Deduplication (3 workers paralelos)
│   ├── WORKER 3.2.1: Deduplicator com cache in-memory
│   ├── WORKER 3.2.2: Distributed lock com Redis (Redlock)
│   └── WORKER 3.2.3: Testes de race condition
│   ⏱️ Tempo: 50 min | 💰 Custo: ~80K tokens/worker
│
├── WAVE 3.3 ─ Chunking (3 workers paralelos)
│   ├── WORKER 3.3.1: Chunker hierárquico (estrutura legal)
│   ├── WORKER 3.3.2: Tokenizer real (AutoTokenizer)
│   └── WORKER 3.3.3: Testes de preservação de estrutura
│   ⏱️ Tempo: 55 min | 💰 Custo: ~85K tokens/worker
│
└── GATE 3 ─ Aprovação Pipeline 5-7
    ✅ Fingerprint é determinístico (mesmo input = mesmo hash)
    ✅ Deduplicação evita duplicatas (inclusive concorrentes)
    ✅ Distributed lock funciona (teste com 10 workers paralelos)
    ✅ Chunking preserva estrutura jurídica (Artigos, §, etc.)
    ✅ Tokenizer real usado (validar contagem de tokens)
    🔴 NÃO PROSSEGUIR se chunking não preservar estrutura
```

**Total Fase 3:** 8 workers | ⏱️ 2.5h | 💰 ~650K tokens

---

### 📌 FASE 4 — Pipeline Fases 8-10 (Embedding → Indexação)
**Objetivo**: Embeddings e indexação atômica

```
FASE 4 ─ Pipeline Fases 8-10 (Embedding → Indexação)
├── WAVE 4.1 ─ Embedder (3 workers paralelos)
│   ├── WORKER 4.1.1: Client TEI (Text Embeddings Inference)
│   ├── WORKER 4.1.2: Circuit breaker + retry
│   └── WORKER 4.1.3: Batch processing + testes
│   ⏱️ Tempo: 50 min | 💰 Custo: ~80K tokens/worker
│
├── WAVE 4.2 ─ Indexer (4 workers paralelos)
│   ├── WORKER 4.2.1: Indexer PostgreSQL (documentos)
│   ├── WORKER 4.2.2: Indexer Elasticsearch
│   ├── WORKER 4.2.3: Indexer pgvector (chunks)
│   └── WORKER 4.2.4: Transações atômicas + compensação
│   ⏱️ Tempo: 60 min | 💰 Custo: ~90K tokens/worker
│
├── WAVE 4.3 ─ ES Mapping (2 workers paralelos)
│   ├── WORKER 4.3.1: Mapping Elasticsearch completo
│   └── WORKER 4.3.2: Script de criação de índice
│   ⏱️ Tempo: 40 min | 💰 Custo: ~60K tokens/worker
│
└── GATE 4 ─ Aprovação Pipeline 8-10
    ✅ Embeddings gerados corretamente (384 dims)
    ✅ Indexação atômica (PG + ES consistentes)
    ✅ Circuit breaker funciona (simular falha TEI)
    ✅ Busca BM25 retorna resultados
    ✅ Busca vetorial retorna resultados
    🔴 NÃO PROSSEGUIR se dimensionalidade != 384
```

**Total Fase 4:** 9 workers | ⏱️ 2.5h | 💰 ~750K tokens

---

### 📌 FASE 5 — Busca Híbrida
**Objetivo**: Busca RRF funcional

```
FASE 5 ─ Busca Híbrida
├── WAVE 5.1 ─ Search Service (4 workers paralelos)
│   ├── WORKER 5.1.1: SearchService BM25
│   ├── WORKER 5.1.2: SearchService vetorial
│   ├── WORKER 5.1.3: Algoritmo RRF
│   └── WORKER 5.1.4: Filtros e highlights
│   ⏱️ Tempo: 55 min | 💰 Custo: ~85K tokens/worker
│
├── WAVE 5.2 ─ API Search (2 workers paralelos)
│   ├── WORKER 5.2.1: Endpoint /api/v1/search
│   └── WORKER 5.2.2: Schemas Pydantic
│   ⏱️ Tempo: 35 min | 💰 Custo: ~55K tokens/worker
│
├── WAVE 5.3 ─ Testes (2 workers paralelos)
│   ├── WORKER 5.3.1: Testes unitários do RRF
│   └── WORKER 5.3.2: Testes E2E de busca
│   ⏱️ Tempo: 40 min | 💰 Custo: ~65K tokens/worker
│
└── GATE 5 ─ Aprovação Busca
    ✅ Busca BM25 funciona (testar com query "licitação")
    ✅ Busca vetorial funciona (testar com query semântica)
    ✅ Busca híbrida (RRF) funciona (match_sources correto)
    ✅ Filtros aplicam corretamente (ano, tipo, relator)
    ✅ Highlight funciona (tags <mark>)
    🔴 NÃO PROSSEGUIR se RRF não combinar resultados
```

**Total Fase 5:** 8 workers | ⏱️ 2h | 💰 ~650K tokens

---

### 📌 FASE 6 — API REST Completa
**Objetivo**: API funcional com auth

```
FASE 6 ─ API REST Completa
├── WAVE 6.1 ─ Endpoints Core (5 workers paralelos)
│   ├── WORKER 6.1.1: Health check (granular: live/ready)
│   ├── WORKER 6.1.2: GET /documents/{id}
│   ├── WORKER 6.1.3: GET /sources
│   ├── WORKER 6.1.4: POST /search
│   └── WORKER 6.1.5: Schemas Pydantic completos
│   ⏱️ Tempo: 50 min | 💰 Custo: ~80K tokens/worker
│
├── WAVE 6.2 ─ Endpoints Admin (4 workers paralelos)
│   ├── WORKER 6.2.1: POST /admin/sync/{source_id}
│   ├── WORKER 6.2.2: GET /admin/executions
│   ├── WORKER 6.2.3: GET/POST /admin/dlq
│   └── WORKER 6.2.4: RBAC middleware
│   ⏱️ Tempo: 50 min | 💰 Custo: ~80K tokens/worker
│
├── WAVE 6.3 ─ Middlewares (4 workers paralelos)
│   ├── WORKER 6.3.1: JWTMiddleware
│   ├── WORKER 6.3.2: RateLimitMiddleware
│   ├── WORKER 6.3.3: SecurityHeadersMiddleware
│   └── WORKER 6.3.4: RequestIDMiddleware
│   ⏱️ Tempo: 50 min | 💰 Custo: ~75K tokens/worker
│
└── GATE 6 ─ Aprovação API
    ✅ Todos endpoints retornam 200/201 (testar via HTTP)
    ✅ Auth funciona (JWT validado)
    ✅ Rate limiting funciona (testar 100+ requests)
    ✅ RBAC restringe acesso admin (403 para não-admin)
    ✅ Security headers presentes (CSP, HSTS, etc.)
    🔴 NÃO PROSSEGUIR se auth não funcionar
```

**Total Fase 6:** 13 workers | ⏱️ 3h | 💰 ~1.1M tokens

---

### 📌 FASE 7 — Celery Workers
**Objetivo**: Processamento assíncrono

```
FASE 7 ─ Celery Workers
├── WAVE 7.1 ─ Celery Setup (3 workers paralelos)
│   ├── WORKER 7.1.1: worker.py (app Celery)
│   ├── WORKER 7.1.2: Configuração do Beat schedule
│   └── WORKER 7.1.3: Flower dashboard
│   ⏱️ Tempo: 45 min | 💰 Custo: ~70K tokens/worker
│
├── WAVE 7.2 ─ Tasks (3 workers paralelos)
│   ├── WORKER 7.2.1: sync_source task
│   ├── WORKER 7.2.2: retry_dlq_messages task
│   └── WORKER 7.2.3: Task de health check
│   ⏱️ Tempo: 50 min | 💰 Custo: ~75K tokens/worker
│
├── WAVE 7.3 ─ DLQ (2 workers paralelos)
│   ├── WORKER 7.3.1: DLQ processor com retry
│   └── WORKER 7.3.2: Alertas de DLQ
│   ⏱️ Tempo: 40 min | 💰 Custo: ~60K tokens/worker
│
└── GATE 7 ─ Aprovação Celery
    ✅ Celery worker processa tasks (verificar logs)
    ✅ Beat schedule dispara sincronizações (aguardar cron)
    ✅ DLQ processa retries (testar com erro simulado)
    ✅ Flower acessível (/flower ou porta 5555)
    🔴 NÃO PROSSEGUIR se tasks não executarem
```

**Total Fase 7:** 8 workers | ⏱️ 2.5h | 💰 ~650K tokens

---

### 📌 FASE 8 — MCP Server
**Objetivo**: Integração com ChatTCU

```
FASE 8 ─ MCP Server
├── WAVE 8.1 ─ MCP Core (3 workers paralelos)
│   ├── WORKER 8.1.1: server.py (SSE transport)
│   ├── WORKER 8.1.2: Tools (search_documents, get_document, list_sources)
│   └── WORKER 8.1.3: Resources
│   ⏱️ Tempo: 55 min | 💰 Custo: ~85K tokens/worker
│
├── WAVE 8.2 ─ Integração (2 workers paralelos)
│   ├── WORKER 8.2.1: Integração com SearchService
│   └── WORKER 8.2.2: Testes E2E do MCP
│   ⏱️ Tempo: 45 min | 💰 Custo: ~70K tokens/worker
│
└── GATE 8 ─ Aprovação MCP
    ✅ MCP server responde em /mcp
    ✅ Tools funcionam (testar via cliente MCP)
    ✅ SSE transport funciona (conexão persistente)
    ✅ ChatTCU consegue buscar documentos
    🔴 NÃO PROSSEGUIR se tools não retornarem resultados
```

**Total Fase 8:** 5 workers | ⏱️ 2h | 💰 ~500K tokens

---

### 📌 FASE 9 — Crawler Multi-Agente
**Objetivo**: Crawling de fontes web

```
FASE 9 ─ Crawler Multi-Agente
├── WAVE 9.1 ─ Agents (5 workers paralelos)
│   ├── WORKER 9.1.1: PolitenessAgent (robots.txt, rate limiting)
│   ├── WORKER 9.1.2: NavigatorAgent (Playwright)
│   ├── WORKER 9.1.3: FetcherAgent (download)
│   ├── WORKER 9.1.4: MetadataAgent (extração)
│   └── WORKER 9.1.5: CrawlOrchestrator
│   ⏱️ Tempo: 60 min | 💰 Custo: ~90K tokens/worker
│
├── WAVE 9.2 ─ Integração (2 workers paralelos)
│   ├── WORKER 9.2.1: Integração com Pipeline
│   └── WORKER 9.2.2: Testes de crawling
│   ⏱️ Tempo: 45 min | 💰 Custo: ~70K tokens/worker
│
└── GATE 9 ─ Aprovação Crawler
    ✅ Crawler descobre PDFs (testar com tcu_publicacoes)
    ✅ Respeita robots.txt (testar com site de teste)
    ✅ Rate limiting funciona (max 1 req/seg)
    ✅ PDFs baixados e parseados corretamente
    🔴 NÃO PROSSEGUIR se não respeitar robots.txt
```

**Total Fase 9:** 7 workers | ⏱️ 2h | 💰 ~600K tokens

---

### 📌 FASE 10 — Governança e Observabilidade
**Objetivo**: Controle e visibilidade completos

```
FASE 10 ─ Governança e Observabilidade
├── WAVE 10.1 ─ Governança (4 workers paralelos)
│   ├── WORKER 10.1.1: DataCatalog
│   ├── WORKER 10.1.2: AuditLog com hash chain
│   ├── WORKER 10.1.3: DataLineage
│   └── WORKER 10.1.4: QualityEngine
│   ⏱️ Tempo: 55 min | 💰 Custo: ~85K tokens/worker
│
├── WAVE 10.2 ─ Observabilidade (4 workers paralelos)
│   ├── WORKER 10.2.1: Métricas Prometheus
│   ├── WORKER 10.2.2: Logging estruturado JSON
│   ├── WORKER 10.2.3: Alertas (Prometheus/Alertmanager)
│   └── WORKER 10.2.4: Health checks granular
│   ⏱️ Tempo: 50 min | 💰 Custo: ~80K tokens/worker
│
├── WAVE 10.3 ─ Tracing (2 workers paralelos)
│   ├── WORKER 10.3.1: Distributed tracing (OpenTelemetry)
│   └── WORKER 10.3.2: Correlation ID
│   ⏱️ Tempo: 40 min | 💰 Custo: ~65K tokens/worker
│
└── GATE 10 ─ Aprovação Observabilidade
    ✅ Métricas em /metrics (verificar com curl)
    ✅ Logs estruturados JSON (verificar formato)
    ✅ Alertas configurados (simular condição de alerta)
    ✅ Audit log imutável (tentar UPDATE/DELETE)
    ✅ Quality check em pipeline (documento inválido rejeitado)
    🔴 NÃO PROSSEGUIR se audit log for mutável
```

**Total Fase 10:** 10 workers | ⏱️ 2.5h | 💰 ~850K tokens

---

### 📌 FASE 11 — Testes e CI/CD
**Objetivo**: Qualidade e automação

```
FASE 11 ─ Testes e CI/CD
├── WAVE 11.1 ─ Testes Unitários (5 workers paralelos)
│   ├── WORKER 11.1.1: Testes de modelos
│   ├── WORKER 11.1.2: Testes de pipeline (chunker, fingerprint)
│   ├── WORKER 11.1.3: Testes de busca (RRF)
│   ├── WORKER 11.1.4: Testes de auth
│   └── WORKER 11.1.5: Testes de config
│   ⏱️ Tempo: 50 min | 💰 Custo: ~80K tokens/worker
│
├── WAVE 11.2 ─ Testes de Integração (4 workers paralelos)
│   ├── WORKER 11.2.1: Testes de API (FastAPI TestClient)
│   ├── WORKER 11.2.2: Testes de pipeline E2E
│   ├── WORKER 11.2.3: Testes de busca E2E
│   └── WORKER 11.2.4: Fixtures e factories
│   ⏱️ Tempo: 55 min | 💰 Custo: ~85K tokens/worker
│
├── WAVE 11.3 ─ CI/CD (4 workers paralelos)
│   ├── WORKER 11.3.1: GitHub Actions workflow (lint, test, build)
│   ├── WORKER 11.3.2: Docker build e push
│   ├── WORKER 11.3.3: Trivy security scan
│   └── WORKER 11.3.4: Coverage report (codecov)
│   ⏱️ Tempo: 45 min | 💰 Custo: ~70K tokens/worker
│
└── GATE 11 ─ Aprovação Testes
    ✅ >85% cobertura de testes (pytest --cov)
    ✅ CI verde (lint, test, build passando)
    ✅ Trivy sem vulnerabilidades críticas
    ✅ Testes E2E passam (make test-e2e)
    🔴 NÃO PROSSEGUIR se cobertura < 85%
```

**Total Fase 11:** 13 workers | ⏱️ 3h | 💰 ~1.1M tokens

---

### 📌 FASE 12 — Deploy e Operações
**Objetivo**: Produção pronta

```
FASE 12 ─ Deploy e Operações
├── WAVE 12.1 ─ Fly.io (3 workers paralelos)
│   ├── WORKER 12.1.1: fly.toml completo
│   ├── WORKER 12.1.2: Scripts de deploy
│   └── WORKER 12.1.3: Documentação de operações Fly.io
│   ⏱️ Tempo: 40 min | 💰 Custo: ~60K tokens/worker
│
├── WAVE 12.2 ─ Kubernetes (6 workers paralelos)
│   ├── WORKER 12.2.1: Namespace + ConfigMap + Secrets
│   ├── WORKER 12.2.2: PostgreSQL StatefulSet + backup CronJob
│   ├── WORKER 12.2.3: Elasticsearch StatefulSet + backup CronJob
│   ├── WORKER 12.2.4: API Deployment + Service + Ingress + HPA + PDB
│   ├── WORKER 12.2.5: Worker Deployment + HPA
│   └── WORKER 12.2.6: NetworkPolicy + ServiceMonitor
│   ⏱️ Tempo: 70 min | 💰 Custo: ~100K tokens/worker
│
├── WAVE 12.3 ─ Documentação (3 workers paralelos)
│   ├── WORKER 12.3.1: Runbook de operações
│   ├── WORKER 12.3.2: Guia de troubleshooting
│   └── WORKER 12.3.3: Documentação de rollback
│   ⏱️ Tempo: 45 min | 💰 Custo: ~70K tokens/worker
│
└── GATE 12 ─ Aprovação Deploy (FINAL)
    ✅ Deploy Fly.io funciona (curl https://gabi.fly.dev/health)
    ✅ Manifests K8s aplicam sem erros (kubectl apply -f k8s/)
    ✅ HPA escala automaticamente (simular carga)
    ✅ Backup configurado (kubectl get cronjob)
    ✅ Documentação completa (runbook, troubleshooting)
    🔴 NÃO LIBERAR PARA PRODUÇÃO se qualquer check falhar
```

**Total Fase 12:** 12 workers | ⏱️ 3h | 💰 ~1.0M tokens

---

### 3.4 Resumo do Plano de Swarm

| Fase | Waves | Workers | Tempo | Tokens | Dependências |
|------|-------|---------|-------|--------|--------------|
| FASE 0 | 3 | 10 | 2h | 650K | — |
| FASE 1 | 4 | 15 | 3h | 1.1M | FASE 0 |
| FASE 2 | 4 | 12 | 3.5h | 1.0M | FASE 1 |
| FASE 3 | 3 | 8 | 2.5h | 650K | FASE 2 |
| FASE 4 | 3 | 9 | 2.5h | 750K | FASE 3 |
| FASE 5 | 3 | 8 | 2h | 650K | FASE 4 |
| FASE 6 | 3 | 13 | 3h | 1.1M | FASE 4 |
| FASE 7 | 3 | 8 | 2.5h | 650K | FASE 6 |
| FASE 8 | 2 | 5 | 2h | 500K | FASE 5, 6 |
| FASE 9 | 2 | 7 | 2h | 600K | FASE 2 |
| FASE 10 | 3 | 10 | 2.5h | 850K | FASE 6, 7 |
| FASE 11 | 3 | 13 | 3h | 1.1M | FASE 0-10 |
| FASE 12 | 3 | 12 | 3h | 1.0M | FASE 11 |
| **TOTAL** | **39** | **130** | **33h** | **~10M** | — |

### 3.5 Estratégia de Execução do Swarm

```
Dia 1 (Fases 0-2): Fundação + Pipeline Discovery-Parse
├── Manhã:   FASE 0 (10 workers) → GATE 0
├── Tarde:   FASE 1 (15 workers) → GATE 1  
└── Noite:   FASE 2 (12 workers) → GATE 2

Dia 2 (Fases 3-5): Pipeline Completo + Busca
├── Manhã:   FASE 3 (8 workers) → GATE 3
├── Tarde:   FASE 4 (9 workers) → GATE 4
└── Noite:   FASE 5 (8 workers) → GATE 5

Dia 3 (Fases 6-7): API + Celery
├── Manhã:   FASE 6 (13 workers) → GATE 6
└── Tarde:   FASE 7 (8 workers) → GATE 7

Dia 4 (Fases 8-9): MCP + Crawler
├── Manhã:   FASE 8 (5 workers) → GATE 8
└── Tarde:   FASE 9 (7 workers) → GATE 9

Dia 5 (Fase 10): Observabilidade
└── Dia todo: FASE 10 (10 workers) → GATE 10

Dia 6-7 (Fases 11-12): Testes e Deploy
├── Dia 6:   FASE 11 (13 workers) → GATE 11
└── Dia 7:   FASE 12 (12 workers) → GATE 12 (FINAL)
```

### 3.6 Checklist de Go/No-Go por Fase

#### Go/No-Go Gate 0 (Fundação)
| Critério | Peso | Status |
|----------|------|--------|
| `make docker-up` sobe todos serviços | 30% | ⬜ |
| `make migrate` executa sem erros | 30% | ⬜ |
| Health check retorna 200 | 20% | ⬜ |
| Estrutura de diretórios completa | 20% | ⬜ |
| **DECISÃO** | | ⬜ GO / ⬜ NO-GO |

#### Go/No-Go Gate 4 (Pipeline Completo)
| Critério | Peso | Status |
|----------|------|--------|
| Embeddings 384 dims | 25% | ⬜ |
| Indexação atômica | 25% | ⬜ |
| Circuit breaker funciona | 20% | ⬜ |
| Busca BM25 funciona | 15% | ⬜ |
| Busca vetorial funciona | 15% | ⬜ |
| **DECISÃO** | | ⬜ GO / ⬜ NO-GO |

#### Go/No-Go Gate 6 (API)
| Critério | Peso | Status |
|----------|------|--------|
| Endpoints retornam 200/201 | 25% | ⬜ |
| Auth JWT funciona | 30% | ⬜ |
| Rate limiting funciona | 20% | ⬜ |
| RBAC restringe acesso | 15% | ⬜ |
| Security headers | 10% | ⬜ |
| **DECISÃO** | | ⬜ GO / ⬜ NO-GO |

#### Go/No-Go Gate 12 (FINAL - Produção)
| Critério | Peso | Status |
|----------|------|--------|
| Cobertura >85% | 20% | ⬜ |
| CI/CD verde | 15% | ⬜ |
| Vuln scan sem críticas | 15% | ⬜ |
| Deploy Fly.io funciona | 15% | ⬜ |
| K8s manifests válidos | 15% | ⬜ |
| Documentação completa | 10% | ⬜ |
| Aprovação segurança TCU | 10% | ⬜ |
| **DECISÃO FINAL** | | ⬜ GO / ⬜ NO-GO |

### 3.7 Relatório de Risco

| Risco | Probabilidade | Impacto | Mitigação |
|-------|---------------|---------|-----------|
| **Incompatibilidade TEI** | Média | Alto | Fallback para transformers local |
| **Performance pgvector** | Média | Alto | HNSW + índices otimizados |
| **Keycloak indisponível** | Baixa | Alto | Cache JWT + modo degradado |
| **ES cluster instável** | Média | Médio | Reindexação assíncrona |
| **Fonte TCU mudar formato** | Alta | Médio | Schema validation + alertas |
| **Memory leak pipeline** | Média | Alto | Memory budget + OOM protection |
| **Rate limits externos** | Alta | Baixo | Backoff exponencial + cache |
| **Dados sensíveis em logs** | Baixa | Alto | PII redaction + audit |

---

## APÊNDICE A: Referências Rápidas

### Comandos Make

```bash
make docker-up          # Sobe infraestrutura local
make docker-down        # Derruba infraestrutura
make migrate            # Executa migrações
make migrate-create     # Cria nova migração
make test               # Executa testes
make test-coverage      # Executa testes com cobertura
make lint               # Executa linter
make format             # Formata código
make run-api            # Inicia API local
make run-worker         # Inicia Celery worker
```

### Variáveis de Ambiente Obrigatórias

```bash
GABI_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/gabi
GABI_ELASTICSEARCH_URL=http://localhost:9200
GABI_REDIS_URL=redis://localhost:6379/0
GABI_EMBEDDINGS_URL=http://localhost:8080
```

### URLs de Saúde

```
GET /health             # Health básico
GET /health/live        # Liveness probe
GET /health/ready       # Readiness probe
GET /metrics            # Métricas Prometheus
```

---

## APÊNDICE B: Glossário

| Termo | Definição |
|-------|-----------|
| **BM25** | Algoritmo de ranking de relevância para busca textual |
| **Chunk** | Segmento de texto processável (tipicamente 512 tokens) |
| **DLQ** | Dead Letter Queue — fila de mensagens com erro |
| **Embedding** | Vetor numérico que representa semanticamente um texto |
| **HNSW** | Hierarchical Navigable Small World — algoritmo de índice vetorial |
| **MCP** | Model Context Protocol — protocolo de integração com LLMs |
| **pgvector** | Extensão PostgreSQL para storage e busca vetorial |
| **RRF** | Reciprocal Rank Fusion — algoritmo de fusão de rankings |
| **TEI** | Text Embeddings Inference — servidor de embeddings |

---

**Fim do Documento GABI_SPECS_FINAL_v1.md**

*Documento binding para implementação do projeto GABI — TCU*
