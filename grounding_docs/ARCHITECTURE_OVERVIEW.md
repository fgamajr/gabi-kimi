# GABI-SYNC: Architecture Overview

**Status:** Design Complete  
**Date:** 2026-02-12  
**Version:** 2.0.0  

---

## TL;DR

GABI-KIMI está sendo refatorado para **GABI-SYNC** - uma arquitetura modular com 6 camadas estritas:

```
contracts/ → infra/ → models/ → discover/ + ingest/ → sync/
   (L1)      (L2)      (L3)          (L4)            (L5)
```

Cada camada só pode importar de camadas inferiores. Zero acoplamento circular.

---

## Problemas da Arquitetura Atual

### Codigo Legado (arquivo curado)

| Arquivo | Linhas | Problema |
|---------|--------|----------|
| `sync.py` | 1,585 | Orquestra TUDO em uma função |
| `fetcher.py` | 1,558 | HTTP + SSRF + Circuit Breaker + Streaming misturados |
| `parser.py` | 1,994 | CSV + HTML + PDF + JSON em um arquivo |

**Consequências:**
- ❌ Impossível testar sem Docker completo
- ❌ Mudanças em um lugar quebram outros
- ❌ Novos devs precisam de semanas para entender
- ❌ Não dá para rodar sem Elasticsearch/TEI

---

## Nova Arquitetura: 6 Camadas

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 5: ORCHESTRATION (gabi/sync/)                             │
│ PipelineRunner, Celery Tasks, Control                           │
│ Depende de: TODAS as camadas                                    │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │
┌─────────────────────────────────────────────────────────────────┐
│ Layer 4: DOMAIN APPS                                            │
│ ┌──────────────┐  ┌──────────────────────────────────────────┐  │
│ │ discover/    │  │ ingest/                                  │  │
│ │ Discovery    │  │ ┌─────────┐ ┌─────────────────────────┐  │  │
│ │ ChangeDetect │  │ │fetcher/ │ │ parser/                 │  │  │
│ └──────────────┘  │ │- HTTP   │ │ - CSV Parser            │  │  │
│                   │ │- Stream │ │ - HTML Parser           │  │  │
│                   │ │- SSRF   │ │ - PDF Parser            │  │  │
│                   │ └─────────┘ │ - JSON Parser           │  │  │
│                   │             └─────────────────────────┘  │  │
│                   └──────────────────────────────────────────┘  │
│ Depende de: Layers 0,1,2,3                                      │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │
┌─────────────────────────────────────────────────────────────────┐
│ Layer 3: MODELS (gabi/models/)                                  │
│ SourceRegistry, Document, DocumentChunk, ExecutionManifest     │
│ Depende de: Layers 0,1,2                                        │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │
┌─────────────────────────────────────────────────────────────────┐
│ Layer 2: INFRASTRUCTURE (gabi/infra/)                           │
│ Config (Pydantic), DB (SQLAlchemy), Celery, Logging            │
│ Depende de: Layers 0,1                                          │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │
┌─────────────────────────────────────────────────────────────────┐
│ Layer 1: CONTRACTS (gabi/contracts/)                            │
│ DiscoveredURL, FetchedContent, ParsedDocument, Chunk           │
│ Depende de: Layer 0                                             │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │
┌─────────────────────────────────────────────────────────────────┐
│ Layer 0: FOUNDATION                                             │
│ types.py (enums), exceptions.py                                 │
│ ZERO dependências                                               │
└─────────────────────────────────────────────────────────────────┘
```

### Regra de Ouro

```python
# ✅ PERMITIDO: Importar de camadas inferiores
# Em gabi/ingest/fetcher/http_client.py:
from gabi.contracts.fetch import FetchConfig      # L1 ← OK
from gabi.infra.config import settings           # L2 ← OK

# ❌ PROIBIDO: Importar de camadas superiores ou siblings
from gabi.sync.pipeline_runner import PipelineRunner  # L5 ← VIOLAÇÃO!
from gabi.ingest.parser import CSVParser              # Sibling ← VIOLAÇÃO!
```

---

## Apps Independentes

### 1. GABI-CONTRACTS (Layer 1)

**Responsabilidade:** Definir estruturas de dados puros

```python
# contracts/discovery.py
@dataclass(frozen=True)
class DiscoveredURL:
    url: str
    source_id: str
    metadata: Dict[str, Any]
```

**Teste:** Unit tests puros, sem infraestrutura

### 2. GABI-INFRA (Layer 2)

**Responsabilidade:** Configuração, banco, logging, filas

```python
# infra/db.py
async_session_factory: Optional[async_sessionmaker] = None

async def init_db():
    global async_session_factory
    async_session_factory = async_sessionmaker(engine, ...)
```

**Teste:** Requer PostgreSQL (testcontainers)

### 3. GABI-DISCOVER (Layer 4)

**Responsabilidade:** Descobrir URLs de fontes

```python
# discover/engine.py
class DiscoveryEngine:
    async def discover(self, source_id: str) -> List[DiscoveredURL]:
        # Só retorna URLs, não sabe de fetch/parse
```

**Teste:** Mock HTTP responses

### 4. GABI-INGEST (Layer 4)

**Responsabilidade:** Fetch + Parse + Fingerprint + Dedup + Chunk

```python
ingest/
├── fetcher/           # HTTP, streaming, SSRF
│   ├── http_client.py
│   ├── streaming.py   # Queue-based streaming
│   └── ssrf.py        # Security
├── parser/            # Multi-format
│   ├── csv_parser.py
│   ├── html_parser.py
│   └── registry.py    # Plugin system
├── fingerprint.py
├── deduplication.py
└── chunker.py
```

**Teste:** Cada parser isoladamente

### 5. GABI-SYNC (Layer 5)

**Responsabilidade:** Orquestrar todo o pipeline

```python
# sync/pipeline_components.py (Dependency Injection)
@dataclass
class PipelineComponents:
    discovery_engine: DiscoveryEngine
    fetcher: ContentFetcher
    parser: ContentParser
    fingerprinter: Fingerprinter
    deduplicator: Deduplicator
    chunker: Chunker
    embedder: Optional[Embedder] = None   # Optional!
    indexer: Optional[Indexer] = None      # Optional!
```

**Teste:** Mock ALL dependencies

---

## Docker Compose Profiles

A infraestrutura é modular - ligue só o que precisa:

```bash
# Profile "core" - mínimo viável (PG + Redis apenas)
docker compose --profile core up

# Profile "embed" - adiciona TEI para embeddings
docker compose --profile core --profile embed up

# Profile "index" - adiciona Elasticsearch
docker compose --profile core --profile index up

# Profile "full" - tudo (PG + Redis + TEI + ES)
docker compose --profile full up
```

Isso permite:
- ✅ Rodar discovery + ingest + PG **sem** ES/TEI
- ✅ Adicionar ES/TEI **somente quando necessário**
- ✅ Testar com infraestrutura mínima

---

## Novo sources.yaml (v2)

Alinhado com a arquitetura modular:

```yaml
tcu_normas:
  identity: { ... }      # Quem é essa fonte
  discovery: { ... }     # Camada 4a: Onde encontrar
  fetch: { ... }         # Camada 4b: Como buscar
  parse: { ... }         # Camada 4b: Como parsear
  transform: { ... }     # Camada 4b: Pós-processamento
  pipeline:              # Camada 5: Orquestração
    optional:
      embed: { ... }     # Claramente opcional
      index: { ... }     # Claramente opcional
```

### Melhorias

1. **Separação clara de fases**: discovery, fetch, parse, transform
2. **Configuração por campo**: Cada campo declara transforms, storage, index
3. **Registro de transforms**: Reutilizáveis e compostas
4. **Streaming explícito**: Configuração de chunks, queue size
5. **Validação declarativa**: Regras de validação no YAML

---

## Fluxo de Dados

```
sources.yaml
     │
     ▼
discover/  → DiscoveredURL[]
     │
     ▼
ingest/fetcher/  → FetchedContent (streaming)
     │
     ▼
ingest/parser/   → ParsedDocument[]
     │
     ▼
ingest/fingerprint/  → DocumentFingerprint
     │
     ▼
ingest/deduplication/  → (filter duplicates)
     │
     ▼
ingest/chunker/  → Chunk[]
     │
     ▼
models/  → PostgreSQL (source of truth)
     │
     ▼
optional: embed/  → TEI → embeddings
     │
     ▼
optional: index/  → Elasticsearch
```

---

## Plano de Implementação (5 semanas)

| Semana | Foco | Entregável |
|--------|------|-----------|
| 1 | Foundation | contracts/, infra/, models/ testados |
| 2 | Discovery | discover/ funcional, descobre URLs |
| 3 | Ingestion | ingest/fetcher/, ingest/parser/ funcionando |
| 4 | Orchestration | sync/ com DI, pipeline end-to-end |
| 5 | Integration | Docker profiles, scripts, E2E tests |

**Estimativa:** ~56 horas de trabalho focado

---

## Documentação

- **ADR 001**: Decisão arquitetural modular ([docs/adr/001-gabi-sync-modular-architecture.md](docs/adr/001-gabi-sync-modular-architecture.md))
- **ADR 002**: Novo sources.yaml v2 ([docs/adr/002-sources-yaml-v2.md](docs/adr/002-sources-yaml-v2.md))
- **sources_v2.yaml**: Estrutura de configuração ([sources_v2.yaml](sources_v2.yaml))

---

## Checklist Pre-Implementação

Antes de começar:

- [ ] Criar branch git: `git checkout -b refactor/gabi-sync-modular`
- [x] Confirmar backup: referencias legadas curadas em `grounding_docs/archive/legacy-python/`
- [ ] Setup ambiente: Docker, Python 3.11+, VSCode/PyCharm
- [ ] Review deste documento
- [ ] Definir prioridade: Fase 1 (Foundation) pronta para iniciar?

---

## Contato

Para dúvidas sobre arquitetura, consulte:
1. Este documento
2. ADRs em `docs/adr/`
3. Codigo legado em `grounding_docs/archive/legacy-python/` (referencia)

---

**Próximo passo:** Aprovar este design e começar **Fase 1: Foundation**
