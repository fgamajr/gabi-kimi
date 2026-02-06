# FILE_OWNERSHIP.md — Propriedade de Arquivos e Coordenação

**Status:** BINDING — Todo worker DEVE consultar este documento antes de criar ou modificar qualquer arquivo.

**Regras Fundamentais:**
1. Cada arquivo tem UM dono (o worker que o cria).
2. Outros workers podem IMPORTAR de arquivos que não são seus, mas NUNCA modificá-los.
3. Arquivos compartilhados (marcados com 🔒) são criados na Wave mais cedo e NUNCA alterados depois.
4. Se um worker precisa de algo que não existe, ele PARA e reporta ao coordenador.

---

## 1. Arquivos Compartilhados (🔒 Lock Permanente)

Estes arquivos são criados uma vez e NUNCA modificados por qualquer worker posterior.

| Arquivo | Dono | Criado em | Conteúdo |
|---------|------|-----------|----------|
| `src/gabi/__init__.py` | WORKER 0.1.1 | WAVE 0.1 | `__version__ = "2.1.0"` |
| `src/gabi/types.py` | WORKER 0.3.1 | WAVE 0.3 | Enums e BaseModel de CONTRACTS.md §1 |
| `src/gabi/config.py` | WORKER 0.3.1 | WAVE 0.3 | Pydantic Settings (cópia exata da spec §2.6) |
| `src/gabi/db.py` | WORKER 1.4.1 | WAVE 1.4 | Engine, AsyncSession factory, init_db, close_db |
| `src/gabi/dependencies.py` | WORKER 1.4.2 | WAVE 1.4 | get_db, get_es_client, get_redis, get_search_service |
| `src/gabi/exceptions.py` | WORKER 0.3.1 | WAVE 0.3 | GABIException, NotFoundError, DuplicateError, etc. |
| `src/gabi/models/base.py` | WORKER 1.1.1 | WAVE 1.1 | DeclarativeBase, mixins (TimestampMixin, SoftDeleteMixin) |
| `src/gabi/pipeline/contracts.py` | WORKER 0.3.1 | WAVE 0.3 | Todos os tipos de CONTRACTS.md §2 |
| `sources.yaml` | PRÉ-EXISTENTE | — | Não modificar. Já fornecido. |
| `tests/conftest.py` | WORKER 1.4.3 | WAVE 1.4 | Fixtures compartilhadas (ver GATES.md §1) |
| `tests/factories.py` | WORKER 1.4.3 | WAVE 1.4 | Factory Boy factories para todos os modelos |

---

## 2. Mapa de Propriedade por Fase

### FASE 0 — Fundação

#### WAVE 0.1 — Estrutura

| Worker | Arquivos que CRIA | Depende de |
|--------|-------------------|------------|
| **0.1.1** | Toda a árvore de `__init__.py` (src/gabi/, models/, schemas/, api/, services/, pipeline/, crawler/, governance/, auth/, mcp/) | — |
| **0.1.2** | `.gitignore`, `README.md`, `LICENSE` | — |
| **0.1.3** | `Makefile` | — |

#### WAVE 0.2 — Docker

| Worker | Arquivos que CRIA | Depende de |
|--------|-------------------|------------|
| **0.2.1** | `docker-compose.local.yml` | — |
| **0.2.2** | `docker/Dockerfile` | — |
| **0.2.3** | `.dockerignore` | — |
| **0.2.4** | `scripts/setup-local.sh`, `scripts/migrate.sh` | WORKER 0.2.1 |

#### WAVE 0.3 — Configuração

| Worker | Arquivos que CRIA | Depende de |
|--------|-------------------|------------|
| **0.3.1** | `src/gabi/config.py`, `src/gabi/types.py`, `src/gabi/exceptions.py`, `src/gabi/pipeline/contracts.py` | WAVE 0.1 completa |
| **0.3.2** | `.env.example` | WORKER 0.3.1 (precisa saber os nomes das vars) |
| **0.3.3** | `alembic/env.py`, `alembic.ini`, `pyproject.toml`, `requirements.txt`, `requirements-dev.txt` | WORKER 0.3.1 |

---

### FASE 1 — Modelos de Dados

#### WAVE 1.1 — Modelos Core

| Worker | Arquivos que CRIA | Depende de | Importa de |
|--------|-------------------|------------|------------|
| **1.1.1** | `src/gabi/models/base.py` | WAVE 0.3 | `gabi.types`, `gabi.config` |
| **1.1.2** | `src/gabi/models/source.py` | WORKER 1.1.1 | `gabi.models.base`, `gabi.types` |
| **1.1.3** | `src/gabi/models/document.py` | WORKER 1.1.1 | `gabi.models.base`, `gabi.types` |
| **1.1.4** | `src/gabi/models/chunk.py` | WORKER 1.1.1 | `gabi.models.base` |
| **1.1.5** | `src/gabi/models/execution.py` | WORKER 1.1.1 | `gabi.models.base`, `gabi.types` |

#### WAVE 1.2 — Modelos Auxiliares

| Worker | Arquivos que CRIA | Depende de | Importa de |
|--------|-------------------|------------|------------|
| **1.2.1** | `src/gabi/models/dlq.py` | WORKER 1.1.1 | `gabi.models.base`, `gabi.types` |
| **1.2.2** | `src/gabi/models/audit.py` | WORKER 1.1.1 | `gabi.models.base`, `gabi.types` |
| **1.2.3** | `src/gabi/models/lineage.py` | WORKER 1.1.1 | `gabi.models.base` |
| **1.2.4** | `src/gabi/models/cache.py` | WORKER 1.1.1 | `gabi.models.base` |

#### WAVE 1.3 — Migrações

| Worker | Arquivos que CRIA | Depende de |
|--------|-------------------|------------|
| **1.3.1** | `alembic/versions/001_initial_schema.py` | WAVES 1.1 e 1.2 completas |
| **1.3.2** | `alembic/versions/002_indexes_constraints.py` | WORKER 1.3.1 |
| **1.3.3** | `alembic/versions/003_audit_functions.py` | WORKER 1.3.2 |

**⚠️ REGRA:** Migrações são SEQUENCIAIS. Worker 1.3.2 NÃO pode começar até Worker 1.3.1 concluir.

#### WAVE 1.4 — Database Layer

| Worker | Arquivos que CRIA | Depende de |
|--------|-------------------|------------|
| **1.4.1** | `src/gabi/db.py` | WORKER 0.3.1 (config.py) |
| **1.4.2** | `src/gabi/dependencies.py` | WORKER 1.4.1 |
| **1.4.3** | `tests/conftest.py`, `tests/factories.py`, `tests/unit/test_models_source.py`, `tests/unit/test_models_document.py` | WAVES 1.1-1.3 |

---

### FASE 2 — Pipeline Discovery → Parse

#### WAVE 2.1 — Discovery

| Worker | Arquivos que CRIA | Importa de |
|--------|-------------------|------------|
| **2.1.1** | `src/gabi/pipeline/discovery.py` | `gabi.pipeline.contracts` (DiscoveredURL, DiscoveryResult), `gabi.config` |
| **2.1.2** | `src/gabi/crawler/orchestrator.py`, `src/gabi/crawler/navigator.py`, `src/gabi/crawler/base_agent.py` | `gabi.pipeline.contracts`, `gabi.config` |
| **2.1.3** | `tests/unit/test_discovery.py`, `tests/integration/test_discovery.py` | `gabi.pipeline.discovery`, `tests.factories` |

#### WAVE 2.2 — Change Detection

| Worker | Arquivos que CRIA | Importa de |
|--------|-------------------|------------|
| **2.2.1** | `src/gabi/pipeline/change_detection.py` | `gabi.pipeline.contracts` (ChangeDetectionVerdict, ChangeDetectionBatch), `gabi.models.cache`, `gabi.db` |
| **2.2.2** | `tests/unit/test_change_detection.py` | `gabi.pipeline.change_detection`, `tests.factories` |

#### WAVE 2.3 — Fetcher

| Worker | Arquivos que CRIA | Importa de |
|--------|-------------------|------------|
| **2.3.1** | `src/gabi/pipeline/fetcher.py` | `gabi.pipeline.contracts` (FetchedContent), `gabi.config` |
| **2.3.2** | (integrado no 2.3.1) | — |
| **2.3.3** | `tests/unit/test_fetcher.py` | `gabi.pipeline.fetcher`, `tests.factories` |

#### WAVE 2.4 — Parser

| Worker | Arquivos que CRIA | Importa de |
|--------|-------------------|------------|
| **2.4.1** | `src/gabi/pipeline/parser.py` (inclui CSV parser) | `gabi.pipeline.contracts` (ParsedDocument, ParseResult, FetchedContent), `gabi.config` |
| **2.4.2** | (parser PDF adicionado ao parser.py como classe PDFParser) | `gabi.pipeline.parser` |
| **2.4.3** | (parser HTML adicionado ao parser.py como classe HTMLParser) | `gabi.pipeline.parser` |
| **2.4.4** | `src/gabi/pipeline/transforms.py`, `tests/unit/test_parser.py`, `tests/unit/test_transforms.py` | `gabi.pipeline.parser` |

**⚠️ COORDENAÇÃO PARSER:** Workers 2.4.1-2.4.3 trabalham no mesmo arquivo `parser.py`. O WORKER 2.4.1 cria a estrutura base (classe abstrata `BaseParser`, `ParserFactory`, `CSVParser`). Workers 2.4.2 e 2.4.3 ADICIONAM suas classes ao arquivo existente. Ordem: 2.4.1 → 2.4.2 → 2.4.3 (serializado, não paralelo).

---

### FASE 3 — Fingerprint → Chunking

| Worker | Arquivos que CRIA | Importa de |
|--------|-------------------|------------|
| **3.1.1** | `src/gabi/pipeline/fingerprint.py` | `gabi.pipeline.contracts` (FingerprintedDocument, ParsedDocument) |
| **3.1.2** | `tests/unit/test_fingerprint.py` | `gabi.pipeline.fingerprint` |
| **3.2.1** | `src/gabi/pipeline/deduplication.py` | `gabi.pipeline.contracts` (DeduplicationVerdict, FingerprintedDocument), `gabi.db`, `gabi.models.document` |
| **3.2.2** | (distributed lock integrado ao 3.2.1) | — |
| **3.2.3** | `tests/unit/test_deduplication.py`, `tests/integration/test_dedup_concurrent.py` | `gabi.pipeline.deduplication` |
| **3.3.1** | `src/gabi/pipeline/chunker.py` | `gabi.pipeline.contracts` (Chunk, ChunkingResult), `gabi.config` |
| **3.3.2** | (tokenizer integrado ao 3.3.1) | — |
| **3.3.3** | `tests/unit/test_chunker.py` | `gabi.pipeline.chunker` |

---

### FASE 4 — Embedding → Indexação

| Worker | Arquivos que CRIA | Importa de |
|--------|-------------------|------------|
| **4.1.1** | `src/gabi/pipeline/embedder.py` | `gabi.pipeline.contracts` (EmbeddedChunk, EmbeddingResult, Chunk), `gabi.config` |
| **4.1.2** | (circuit breaker integrado ao 4.1.1) | — |
| **4.1.3** | `tests/unit/test_embedder.py` | `gabi.pipeline.embedder` |
| **4.2.1** | `src/gabi/pipeline/indexer.py` | `gabi.pipeline.contracts` (IndexingInput, IndexingResult), `gabi.db`, `gabi.models.document`, `gabi.models.chunk` |
| **4.2.2** | `src/gabi/services/indexing_service.py` | `gabi.pipeline.indexer`, `gabi.config` |
| **4.2.3** | (pgvector integrado ao 4.2.1) | — |
| **4.2.4** | `tests/integration/test_indexer.py` | `gabi.pipeline.indexer` |
| **4.3.1** | `src/gabi/services/elasticsearch_setup.py` | `gabi.config` (contém mapping JSON da spec §2.7.2) |
| **4.3.2** | `scripts/create_es_index.py` | `gabi.services.elasticsearch_setup` |

---

### FASE 5 — Busca Híbrida

| Worker | Arquivos que CRIA | Importa de |
|--------|-------------------|------------|
| **5.1.1** | `src/gabi/services/search_service.py` (classe SearchService com _search_bm25) | `gabi.pipeline.contracts`, `gabi.schemas.search`, `gabi.config` |
| **5.1.2** | (método _search_vector adicionado ao search_service.py) | — |
| **5.1.3** | (método _search_hybrid e RRF adicionados) | — |
| **5.1.4** | (filtros e highlights adicionados) | — |

**⚠️ COORDENAÇÃO:** Workers 5.1.1-5.1.4 trabalham no mesmo arquivo. Execução SERIALIZADA: 5.1.1 → 5.1.2 → 5.1.3 → 5.1.4.

| Worker | Arquivos que CRIA | Importa de |
|--------|-------------------|------------|
| **5.2.1** | `src/gabi/api/search.py` | `gabi.services.search_service`, `gabi.schemas.search`, `gabi.dependencies` |
| **5.2.2** | `src/gabi/schemas/search.py` | `gabi.types` (SearchType, etc.) |
| **5.3.1** | `tests/unit/test_rrf.py` | `gabi.services.search_service` |
| **5.3.2** | `tests/e2e/test_search_api.py` | `gabi.api.search` |

**⚠️ DEPENDÊNCIA:** Worker 5.2.2 (schemas) DEVE rodar ANTES de 5.2.1 (router) e 5.1.1 (service).

---

### FASE 6 — API REST

#### WAVE 6.1 — Endpoints Core

| Worker | Arquivos que CRIA | Importa de |
|--------|-------------------|------------|
| **6.1.1** | `src/gabi/api/health.py` | `gabi.dependencies`, `gabi.schemas.health` |
| **6.1.2** | `src/gabi/api/documents.py` | `gabi.dependencies`, `gabi.schemas.document` |
| **6.1.3** | `src/gabi/api/sources.py` | `gabi.dependencies`, `gabi.schemas.source` |
| **6.1.4** | `src/gabi/api/router.py` (agrega todos os routers) | `gabi.api.health`, `gabi.api.documents`, `gabi.api.sources`, `gabi.api.search`, `gabi.api.admin` |
| **6.1.5** | `src/gabi/schemas/document.py`, `src/gabi/schemas/source.py`, `src/gabi/schemas/health.py` | `gabi.types` |

**⚠️ DEPENDÊNCIA:** Worker 6.1.5 (schemas) DEVE rodar ANTES de 6.1.1-6.1.4.

#### WAVE 6.2 — Endpoints Admin

| Worker | Arquivos que CRIA | Importa de |
|--------|-------------------|------------|
| **6.2.1** | `src/gabi/api/admin.py` (sync endpoint) | `gabi.dependencies`, `gabi.schemas.admin`, `gabi.auth.rbac` |
| **6.2.2** | (executions endpoint adicionado ao admin.py) | — |
| **6.2.3** | (DLQ endpoints adicionados ao admin.py) | — |
| **6.2.4** | `src/gabi/schemas/admin.py` | `gabi.types` |

**⚠️ COORDENAÇÃO:** Worker 6.2.4 ANTES de 6.2.1-6.2.3. Workers 6.2.1-6.2.3 serializam no mesmo arquivo.

#### WAVE 6.3 — Middlewares

| Worker | Arquivos que CRIA | Importa de |
|--------|-------------------|------------|
| **6.3.1** | `src/gabi/auth/jwt.py`, `src/gabi/auth/middleware.py` | `gabi.config` |
| **6.3.2** | `src/gabi/middleware/rate_limit.py` | `gabi.config` |
| **6.3.3** | `src/gabi/middleware/security_headers.py` | `gabi.config` |
| **6.3.4** | `src/gabi/middleware/request_id.py` | — |

Estes 4 workers SÃO paralelos (arquivos distintos).

| Worker | Arquivos que CRIA | Importa de |
|--------|-------------------|------------|
| **6.MAIN** | `src/gabi/main.py` | Todos os middlewares, `gabi.api.router`, `gabi.config`, `gabi.db` |

**⚠️ DEPENDÊNCIA:** Worker 6.MAIN roda DEPOIS de todos os workers da FASE 6.

---

### FASE 7 — Celery

| Worker | Arquivos que CRIA | Importa de |
|--------|-------------------|------------|
| **7.1.1** | `src/gabi/worker.py` | `gabi.config` |
| **7.1.2** | (beat schedule integrado ao worker.py) | — |
| **7.1.3** | `docker-compose.local.yml` (adiciona serviço flower) | — |
| **7.2.1** | `src/gabi/tasks/sync.py` | `gabi.worker`, `gabi.pipeline.orchestrator`, `gabi.config` |
| **7.2.2** | `src/gabi/tasks/dlq.py` | `gabi.worker`, `gabi.models.dlq`, `gabi.db` |
| **7.2.3** | `src/gabi/tasks/health.py` | `gabi.worker`, `gabi.dependencies` |
| **7.3.1** | (DLQ processor integrado ao tasks/dlq.py) | — |
| **7.3.2** | `src/gabi/tasks/alerts.py` | `gabi.worker`, `gabi.metrics` |

---

### FASE 8 — MCP

| Worker | Arquivos que CRIA | Importa de |
|--------|-------------------|------------|
| **8.1.1** | `src/gabi/mcp/server.py` | `gabi.config` |
| **8.1.2** | `src/gabi/mcp/tools.py` | `gabi.services.search_service`, `gabi.pipeline.contracts` |
| **8.1.3** | `src/gabi/mcp/resources.py` | `gabi.dependencies` |
| **8.2.1** | (integração testada via 8.2.2) | — |
| **8.2.2** | `tests/e2e/test_mcp.py` | `gabi.mcp.server` |

---

### FASE 9 — Crawler

| Worker | Arquivos que CRIA | Importa de |
|--------|-------------------|------------|
| **9.1.1** | `src/gabi/crawler/politeness.py` | `gabi.config` |
| **9.1.2** | `src/gabi/crawler/navigator.py` | `gabi.config`, `gabi.crawler.base_agent` |
| **9.1.3** | `src/gabi/crawler/fetcher.py` | `gabi.pipeline.contracts`, `gabi.config` |
| **9.1.4** | `src/gabi/crawler/metadata.py` | `gabi.pipeline.contracts` |
| **9.1.5** | `src/gabi/crawler/orchestrator.py` | Todos os crawler agents |
| **9.2.1** | (integrado ao pipeline via discovery.py) | — |
| **9.2.2** | `tests/integration/test_crawler.py` | `gabi.crawler.orchestrator` |

---

### FASE 10 — Governança e Observabilidade

| Worker | Arquivos que CRIA | Importa de |
|--------|-------------------|------------|
| **10.1.1** | `src/gabi/governance/catalog.py` | `gabi.models.lineage`, `gabi.db` |
| **10.1.2** | `src/gabi/governance/audit.py` | `gabi.pipeline.contracts` (AuditEntry), `gabi.db` |
| **10.1.3** | `src/gabi/governance/lineage.py` | `gabi.models.lineage`, `gabi.db` |
| **10.1.4** | `src/gabi/governance/quality.py` | `gabi.pipeline.contracts` (QualityCheckResult) |
| **10.2.1** | `src/gabi/metrics.py` | `prometheus_client` |
| **10.2.2** | `src/gabi/logging_config.py` | `gabi.config` |
| **10.2.3** | `k8s/monitoring/alerts.yaml` | — |
| **10.2.4** | (health checks já criados em 6.1.1) | — |
| **10.3.1** | `src/gabi/middleware/tracing.py` | `opentelemetry` |
| **10.3.2** | (correlation ID integrado ao request_id middleware) | — |

---

### FASE 11 — Testes

| Worker | Arquivos que CRIA |
|--------|-------------------|
| **11.1.1** | `tests/unit/test_models_*.py` (todos os modelos) |
| **11.1.2** | `tests/unit/test_chunker.py`, `tests/unit/test_fingerprint.py` |
| **11.1.3** | `tests/unit/test_rrf.py`, `tests/unit/test_search_service.py` |
| **11.1.4** | `tests/unit/test_auth.py`, `tests/unit/test_jwt.py` |
| **11.1.5** | `tests/unit/test_config.py` |
| **11.2.1** | `tests/e2e/test_api_health.py`, `tests/e2e/test_api_search.py` |
| **11.2.2** | `tests/e2e/test_pipeline_e2e.py` |
| **11.2.3** | `tests/e2e/test_search_e2e.py` |
| **11.2.4** | Atualiza `tests/conftest.py` e `tests/factories.py` com fixtures completas |

**⚠️ REGRA:** Se o arquivo de teste já existir (criado em fases anteriores), o worker da FASE 11 COMPLEMENTA (não substitui). Testes anteriores são preservados.

---

### FASE 12 — Deploy

| Worker | Arquivos que CRIA |
|--------|-------------------|
| **12.1.1** | `fly.toml` |
| **12.1.2** | `scripts/deploy-fly.sh` |
| **12.1.3** | `docs/operations-fly.md` |
| **12.2.1** | `k8s/base/namespace.yaml`, `k8s/base/configmap.yaml`, `k8s/base/secrets.yaml` |
| **12.2.2** | `k8s/postgres/statefulset.yaml`, `k8s/postgres/service.yaml`, `k8s/postgres/pvc.yaml`, `k8s/postgres/backup-cronjob.yaml` |
| **12.2.3** | `k8s/elasticsearch/statefulset.yaml`, `k8s/elasticsearch/service.yaml`, `k8s/elasticsearch/backup-cronjob.yaml` |
| **12.2.4** | `k8s/api/deployment.yaml`, `k8s/api/service.yaml`, `k8s/api/ingress.yaml`, `k8s/api/hpa.yaml`, `k8s/api/pdb.yaml` |
| **12.2.5** | `k8s/worker/deployment.yaml`, `k8s/worker/hpa.yaml` |
| **12.2.6** | `k8s/network-policies.yaml`, `k8s/monitoring/servicemonitor.yaml` |
| **12.3.1** | `docs/runbook.md` |
| **12.3.2** | `docs/troubleshooting.md` |
| **12.3.3** | `docs/rollback.md` |

---

## 3. Protocolo de Conflito

**Se dois workers precisam editar o mesmo arquivo:**

1. O worker com número MENOR tem prioridade.
2. O worker com número MAIOR espera o anterior concluir.
3. Ao editar arquivo de outro worker, usar APPEND (adicionar classes/funções no final), nunca modificar código existente.
4. Se precisar alterar assinatura de função existente: PARA e reporta ao coordenador.

**Se um worker descobre que precisa de um tipo que não existe em CONTRACTS.md:**

1. Usa `Dict[str, Any]` temporariamente.
2. Documenta no PROGRESS.md: "CONTRATO FALTANTE: [descrição]".
3. O coordenador adiciona o tipo em CONTRACTS.md antes da próxima wave.

---

## 4. Diagrama de Dependências Críticas

```
WAVE 0.1 (estrutura)
    ↓
WAVE 0.3 (config.py, types.py, contracts.py) ← TUDO depende disto
    ↓
WAVE 1.1 (models/base.py) ← Todos os modelos dependem disto
    ↓
WAVE 1.3 (migrações) ← Serializada obrigatoriamente
    ↓
WAVE 1.4 (db.py, dependencies.py, conftest.py) ← Testes e services dependem disto
    ↓
┌──────────────────────┬──────────────────────┐
│ FASES 2-4 (Pipeline) │ FASE 5 (Search)      │
│ (podem paralelizar   │ (depende de FASE 4   │
│  entre si)           │  para teste E2E)     │
└──────────────────────┴──────────────────────┘
    ↓
FASE 6 (API) ← main.py é o ÚLTIMO arquivo da fase
    ↓
┌──────────────────────┬──────────────────────┐
│ FASE 7 (Celery)      │ FASE 8 (MCP)         │
│                      │                      │
│ FASE 9 (Crawler)     │ FASE 10 (Governance) │
└──────────────────────┴──────────────────────┘
    ↓
FASE 11 (Testes) ← Complementa testes existentes
    ↓
FASE 12 (Deploy)
```
