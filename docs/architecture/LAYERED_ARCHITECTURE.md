# Arquitetura em Camadas

## Visão Geral

O GabiSync segue uma arquitetura em 3 camadas com separação clara de responsabilidades:

```
┌─────────────────────────────────────────────────────────────────┐
│                    SERVING PLANE (Layer 4)                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │  Search API │  │  Feed API   │  │  MCP Tools / Chat / RAG │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│                     DATA PLANE (Layers 2-3)                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │   Fetch     │  │    Parse    │  │  Normalize / Deduplicate│  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │   Index     │  │Chunk + Embed│  │   PostgreSQL / ES / Vec │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│                   CONTROL PLANE (Layer 1)                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │  Scheduler  │  │  Execution  │  │  Retry / DLQ / Backoff  │  │
│  │             │  │  Manifest   │  │                         │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Princípio Fundamental

> **Nenhuma camada conhece detalhes internos da outra.**

Comunicação apenas via contratos (`Gabi.Contracts`).

---

## Camada 1: Control Plane

**Responsabilidade:** Orquestração, scheduling, retry, DLQ.

### Componentes

| Projeto | Função |
|---------|--------|
| `Gabi.Worker` | Background jobs (Hangfire/Quartz) |
| `Gabi.Sync` | Sync engine com retry e backoff |

### Contratos

```csharp
// ISyncEngine.cs
public interface ISyncEngine
{
    Task<SyncResult> ExecuteDeltaAsync(
        string sourceId, 
        SyncContext context,
        CancellationToken ct = default);
}

// ExecutionManifest (registro de execução)
public record ExecutionManifest
{
    public Guid Id { get; init; }
    public string SourceId { get; init; } = string.Empty;
    public ExecutionStatus Status { get; init; }
    public DateTime StartedAt { get; init; }
    public DateTime? CompletedAt { get; init; }
    public SyncStats Stats { get; init; } = new();
}
```

### Regras

- Mantém estado de execuções
- Gerencia retries exponenciais
- Envia para DLQ após exaustão
- **NÃO** processa dados

---

## Camada 2-3: Data Plane

**Responsabilidade:** Transformação e persistência de dados.

### Componentes

| Projeto | Função |
|---------|--------|
| `Gabi.Discover` | Discovery de URLs, change detection |
| `Gabi.Ingest` | Fetch, parse, normalize, chunk, embed |
| `Gabi.Postgres` | Models, DbContext, repositórios |

### Pipeline de Dados

```
sources.yaml
    ↓
DiscoveredSource[]
    ↓
FetchedContent (ou null se cache hit)
    ↓
ParsedDocument
    ↓
NormalizedDocument (transforms aplicados)
    ↓
FingerprintedDocument (SHA-256)
    ↓
DeduplicationVerdict (insert/update/skip)
    ↓
IndexedDocument (PostgreSQL)
    ↓
EmbeddedChunk[] (pgvector)
```

### Interfaces Principais

```csharp
// Discovery
public interface IDiscoveryEngine { ... }

// Fetch
public interface IContentFetcher { ... }

// Parse
public interface IDocumentParser { ... }

// Chunk
public interface IChunker { ... }

// Embed
public interface IEmbedder { ... }

// Index
public interface IDocumentIndexer { ... }
```

### Regras

- Stateless (estado no PostgreSQL)
- Idempotente (mesma entrada → mesma saída)
- Determinístico (mesmo documento → mesmo fingerprint)
- **NÃO** contém lógica de scheduling

---

## Camada 4: Serving Plane

**Responsabilidade:** APIs, busca, integração com sistemas externos.

### Componentes (Futuros)

| Projeto | Função |
|---------|--------|
| `Gabi.Api` | REST API (search, admin, health) |
| `Gabi.Mcp` | Model Context Protocol server |
| `Gabi.Search` | Serviço de busca híbrida |

### APIs

```csharp
// Search API
GET /api/v1/search?q={query}&type=hybrid&limit=10

// Document API
GET /api/v1/documents/{document_id}

// Source API
GET /api/v1/sources
GET /api/v1/sources/{source_id}/stats

// Admin API
POST /api/v1/admin/sync/{source_id}
GET /api/v1/admin/executions
```

### Regras

- Apenas leitura de stores derivados
- **NUNCA** escreve direto no PostgreSQL
- Rate limiting
- Autenticação/Autorização

---

## Grafo de Dependências

```
                    ┌─────────────┐
                    │ Gabi.Worker │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │Gabi.Sync │ │Gabi.Api* │ │Gabi.Mcp* │
        └────┬─────┘ └────┬─────┘ └────┬─────┘
             │            │            │
        ┌────┴────────────┴────────────┘
        │
        ▼
┌─────────────────┬─────────────────┐
│  Gabi.Discover  │   Gabi.Ingest   │
└────────┬────────┴────────┬────────┘
         │                 │
         └────────┬────────┘
                  │
                  ▼
           ┌─────────────┐
           │Gabi.Postgres│
           └──────┬──────┘
                  │
                  ▼
           ┌─────────────┐
           │Gabi.Contracts│  ← Layer 0-1 (Zero deps)
           └─────────────┘
```

*Futuros

---

## Fluxo de Dados Completo

```
┌────────────────────────────────────────────────────────────────┐
│  1. Scheduler (Gabi.Worker) dispara job                        │
│     - Baseado em cron do sources.yaml                          │
│     - Cria ExecutionManifest                                   │
└──────────────────────────┬─────────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────────┐
│  2. SyncEngine (Gabi.Sync) executa                             │
│     - Carrega SourceConfig                                     │
│     - Itera sobre cada fase do pipeline                        │
└──────────────────────────┬─────────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────────┐
│  3. Discovery (Gabi.Discover)                                  │
│     - Descobre URLs                                            │
│     - Verifica change_detection_cache                          │
│     - Retorna apenas URLs modificadas                          │
└──────────────────────────┬─────────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────────┐
│  4. Ingest (Gabi.Ingest) processa cada URL                     │
│     - Fetch → Parse → Normalize → Fingerprint → Deduplicate    │
│     - Index → Chunk → Embed                                    │
│     - Atualiza PostgreSQL                                      │
└──────────────────────────┬─────────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────────┐
│  5. API (Gabi.Api) serve requisições                           │
│     - Search: BM25 + Vector + RRF                              │
│     - Document: CRUD read-only                                 │
│     - Admin: trigger sync, view stats                          │
└────────────────────────────────────────────────────────────────┘
```

---

## Isolamento de Apps

Cada "App" (projeto) é isolado e pode ser implantado independentemente:

```yaml
# docker-compose.yml
services:
  # Core (obrigatório)
  worker:
    build: src/Gabi.Worker
    
  # Plugins (opcionais)
  api:
    build: src/Gabi.Api
    profiles: ["api"]
    
  mcp:
    build: src/Gabi.Mcp
    profiles: ["mcp"]
    
  search:
    build: src/Gabi.Search
    profiles: ["search"]
```

### Perfiles Docker

```bash
# Apenas core (ingestão)
docker compose --profile core up

# Core + API
docker compose --profile core --profile api up

# Full stack
docker compose --profile full up
```

---

## Benefícios da Arquitetura

| Aspecto | Benefício |
|---------|-----------|
| **Testabilidade** | Cada camada testável isoladamente |
| **Escalabilidade** | Scale apenas a camada necessária |
| **Manutenibilidade** | Mudanças isoladas, sem efeitos colaterais |
| **Deployabilidade** | Apps independentes, zero-downtime |
| **Resiliência** | Falha em uma camada não afeta outras |
