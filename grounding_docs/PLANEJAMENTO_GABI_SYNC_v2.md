# Planejamento GABI-SYNC v2.0

**Data:** 2026-02-12  
**Stack:** C# .NET 8 + PostgreSQL 16 + pgvector  
**Arquitetura:** Modular Monolith com 6 Apps independentes  

---

## Resumo Executivo

Migração de Python (GABI-KIMI) para C# (GABI-SYNC) com arquitetura limpa, separando responsabilidades em 6 apps independentes com Docker profiles para infraestrutura plugável.

---

## Stack Definido

| Componente | Tecnologia | Justificativa |
|------------|------------|---------------|
| **Linguagem** | C# 12 / .NET 8 | Background nativo, DI, IAsyncEnumerable superior |
| **Banco** | PostgreSQL 16 + pgvector | ACID, joins, vetorial open source, eco .NET maduro |
| **Migrations** | EF Core 8 Migrations | Type-safe, versionado no Git, testável |
| **Cache/Fila** | System.Threading.Channels | Lock-free, sem broker (futuro: Redis opcional) |
| **HTTP** | HttpClient nativo | Streaming com `ResponseHeadersRead` |
| **CSV** | CsvHelper | Streaming via `IAsyncEnumerable` |
| **Config** | IOptions<T> + appsettings.json | Strong typing, validação nativa |

---

## Arquitetura de Apps

### Apps Core (Obrigatórios)

```
┌─────────────────────────────────────────────────────────────────┐
│  Gabi.Contracts                                                  │
│  ├── Records imutáveis (DiscoveredSource, ParsedDocument, etc)  │
│  ├── Interfaces (IDocumentRepository, IContentFetcher, etc)     │
│  ├── Enums (SyncResult, DocumentStatus, etc)                    │
│  └── Exceptions (GabiException, SyncFailedException, etc)       │
│                                                                  │
│  Deps: Nenhuma (Layer 0-1)                                       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Gabi.Postgres                                                   │
│  ├── EF Core DbContext + Entity Configurations (Fluent API)     │
│  ├── Migrations (code-based, versionadas)                       │
│  ├── Repository Pattern (DocumentRepository, etc)               │
│  └── Extension: AddGabiPostgres() para DI                       │
│                                                                  │
│  Deps: Gabi.Contracts, EF Core, Npgsql, pgvector                │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Gabi.Discover                                                   │
│  ├── DiscoveryEngine (resolve URL patterns, static URLs)        │
│  ├── ChangeDetection (ETag, Last-Modified comparison)           │
│  └── Output: IAsyncEnumerable<DiscoveredSource>                 │
│                                                                  │
│  Deps: Gabi.Contracts, HttpClient                               │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Gabi.Ingest                                                     │
│  ├── Fetcher/ (HttpContentFetcher, StreamingFetcher, SSRF)      │
│  ├── Parser/ (CsvParser, HtmlParser, PdfParser, JsonParser)     │
│  ├── Fingerprint (SHA256 hashing)                               │
│  ├── Deduplication (query existing via Gabi.Postgres)           │
│  └── Chunker (semantic splitting)                               │
│                                                                  │
│  Deps: Gabi.Contracts, Gabi.Postgres, CsvHelper, AngleSharp     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Gabi.Sync                                                       │
│  ├── SynchronizationEngine (decide: bypass, insert, update, del)│
│  ├── Diff/Compare (source vs database)                          │
│  ├── Merge strategies (Upsert, SoftDelete)                      │
│  └── Change tracking (what changed, audit log)                  │
│                                                                  │
│  Deps: Gabi.Contracts, Gabi.Postgres                            │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Gabi.Worker (Entry Point)                                       │
│  ├── BackgroundService (IHostedService)                         │
│  ├── PipelineOrchestrator (coordena Discover→Ingest→Sync)       │
│  ├── DI Container Setup                                         │
│  └── Graceful shutdown                                          │
│                                                                  │
│  Deps: Todos os apps acima                                      │
└─────────────────────────────────────────────────────────────────┘
```

### Apps Plugin (Opcionais - Futuro)

```
Gabi.TEI           # Embeddings via TEI container
Gabi.Elastic       # Full-text search via Elasticsearch  
Gabi.Redis         # Cache/distributed locking
Gabi.WebApi        # REST API ASP.NET Core
Gabi.MCP           # Claude Desktop integration
Gabi.Graph         # Neo4j GraphRAG
```

---

## Fluxo de Dados

```
┌─────────────────────────────────────────────────────────────────┐
│                     PIPELINE FLOW                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  sources.yaml ──► Gabi.Discover                                  │
│                      └── DiscoveredSource[]                     │
│                           │                                     │
│                           ▼                                     │
│                    Gabi.Ingest                                   │
│                      ├── Fetch (streaming HTTP)                 │
│                      ├── Parse (CSV → objects)                  │
│                      ├── Fingerprint (SHA256)                   │
│                      ├── Deduplication (query PG)               │
│                      └── Chunk (semantic split)                 │
│                           │                                     │
│                           ▼                                     │
│                    Gabi.Sync                                     │
│                      ├── Compare (fingerprint exists?)          │
│                      ├── Decision:                              │
│                      │   ├── BYPASS (no change)                 │
│                      │   ├── INSERT (new doc)                   │
│                      │   ├── UPDATE (content changed)           │
│                      │   └── DELETE (removed from source)       │
│                      └── Execute via Repository                 │
│                           │                                     │
│                           ▼                                     │
│                    Gabi.Postgres                                 │
│                      ├── EF Core tracking                       │
│                      ├── Transaction                            │
│                      └── Commit                                 │
│                                                                  │
│  Optional (future):                                              │
│  ├── Gabi.TEI → Generate embeddings → Update chunks             │
│  └── Gabi.Elastic → Index document → Searchable                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Estrutura de Diretórios

```
gabi-sync/
├── src/
│   ├── Gabi.Contracts/
│   │   ├── Discovery/
│   │   ├── Fetch/
│   │   ├── Parse/
│   │   ├── Fingerprint/
│   │   ├── Chunk/
│   │   ├── Embed/
│   │   ├── Index/
│   │   ├── Enums/
│   │   └── Exceptions/
│   │
│   ├── Gabi.Postgres/
│   │   ├── Migrations/
│   │   ├── EntityConfigurations/
│   │   ├── Repositories/
│   │   ├── GabiDbContext.cs
│   │   └── ServiceExtensions.cs
│   │
│   ├── Gabi.Discover/
│   │   ├── DiscoveryEngine.cs
│   │   ├── ChangeDetector.cs
│   │   └── ServiceExtensions.cs
│   │
│   ├── Gabi.Ingest/
│   │   ├── Fetcher/
│   │   │   ├── IContentFetcher.cs
│   │   │   ├── HttpContentFetcher.cs
│   │   │   ├── StreamingFetcher.cs
│   │   │   └── SsrfValidator.cs
│   │   ├── Parser/
│   │   │   ├── IDocumentParser.cs
│   │   │   ├── CsvParser.cs
│   │   │   ├── HtmlParser.cs
│   │   │   ├── PdfParser.cs
│   │   │   └── ParserRegistry.cs
│   │   ├── Fingerprinter.cs
│   │   ├── Deduplicator.cs
│   │   ├── Chunker.cs
│   │   └── ServiceExtensions.cs
│   │
│   ├── Gabi.Sync/
│   │   ├── SynchronizationEngine.cs
│   │   ├── SyncStrategies/
│   │   │   ├── BypassStrategy.cs
│   │   │   ├── InsertStrategy.cs
│   │   │   ├── UpdateStrategy.cs
│   │   │   └── DeleteStrategy.cs
│   │   └── ServiceExtensions.cs
│   │
│   └── Gabi.Worker/
│       ├── Program.cs
│       ├── PipelineOrchestrator.cs
│       ├── appsettings.json
│       └── appsettings.Development.json
│
├── tests/
│   ├── Gabi.Contracts.Tests/
│   ├── Gabi.Postgres.Tests/
│   ├── Gabi.Discover.Tests/
│   ├── Gabi.Ingest.Tests/
│   ├── Gabi.Sync.Tests/
│   └── Gabi.IntegrationTests/
│
├── docker/
│   └── Dockerfile
│
├── docker-compose.yml
├── sources.yaml
├── sources_v2.yaml
└── GabiSync.sln
```

---

## Docker Compose Profiles

```yaml
# docker-compose.yml
version: '3.8'

services:
  # CORE (always)
  postgres:
    image: pgvector/pgvector:pg16
    profiles: ["core", "full"]
    environment:
      POSTGRES_USER: gabi
      POSTGRES_PASSWORD: gabi_dev
      POSTGRES_DB: gabi
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  gabi-worker:
    build:
      context: .
      dockerfile: docker/Dockerfile
    profiles: ["core", "full"]
    depends_on:
      - postgres
    environment:
      - ASPNETCORE_ENVIRONMENT=Production
      - ConnectionStrings__Gabi=Host=postgres;Database=gabi;Username=gabi;Password=gabi_dev
    volumes:
      - ./sources.yaml:/app/sources.yaml:ro

  # PLUGINS (optional)
  gabi-tei:
    image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.2
    profiles: ["embed", "full"]
    environment:
      - MODEL_ID=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
    ports:
      - "8080:80"

  elasticsearch:
    image: elasticsearch:8.11.0
    profiles: ["search", "full"]
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
    ports:
      - "9200:9200"

volumes:
  pgdata:
```

**Uso:**
```bash
# Hoje: só core (Postgres + Worker)
docker compose --profile core up

# Futuro: core + embeddings
docker compose --profile core --profile embed up

# Futuro: tudo
docker compose --profile full up
```

---

## Migrations (EF Core)

### Comandos

```bash
# Criar migration (após mudar entities)
dotnet ef migrations add AddDocumentChunks \
  --project src/Gabi.Postgres \
  --startup-project src/Gabi.Worker

# Aplicar migrations (automático no startup ou manual)
dotnet ef database update \
  --project src/Gabi.Postgres \
  --startup-project src/Gabi.Worker

# Gerar script SQL (para review)
dotnet ef migrations script \
  --project src/Gabi.Postgres \
  --startup-project src/Gabi.Worker
```

### Estratégia

1. **Development**: Migrations aplicadas automaticamente no startup
2. **Production**: Migrations aplicadas via CI/CD antes do deploy
3. **Squash**: A cada release maior, squash migrations para manter histórico limpo

---

## Contratos Principais (Gabi.Contracts)

```csharp
// Discovery
public record DiscoveredSource(
    string Url,
    string SourceId,
    IReadOnlyDictionary<string, object> Metadata,
    DateTime DiscoveredAt
);

// Ingest
public record ParsedDocument(
    string DocumentId,
    string SourceId,
    string Title,
    string Content,
    string Fingerprint,
    IReadOnlyList<Chunk> Chunks,
    IReadOnlyDictionary<string, object> Metadata
);

public record Chunk(
    int Index,
    string Text,
    int TokenCount,
    ChunkType Type
);

// Sync
public enum SyncResult
{
    Bypassed,
    Inserted,
    Updated,
    Deleted,
    Failed
}

// Repository Interface
public interface IDocumentRepository
{
    Task<Document?> GetByFingerprintAsync(string fingerprint, CancellationToken ct = default);
    Task<bool> ExistsAsync(string documentId, CancellationToken ct = default);
    Task AddAsync(Document document, CancellationToken ct = default);
    Task UpdateAsync(Document document, CancellationToken ct = default);
    Task SoftDeleteAsync(string documentId, CancellationToken ct = default);
}
```

---

## Cronograma de Implementação

### Semana 1: Foundation
- [ ] Criar solution e 6 projetos
- [ ] Gabi.Contracts (records, interfaces, enums)
- [ ] Gabi.Postgres (DbContext, migrations iniciais)
- [ ] Configurar DI básica
- **Entregável:** `dotnet build` passa, migrations criam tabelas

### Semana 2: Discover + Ingest (Fetcher)
- [ ] Gabi.Discover (URL patterns, static URLs)
- [ ] Gabi.Ingest.Fetcher (HTTP, streaming, SSRF)
- [ ] Testes unitários
- **Entregável:** Descobre URLs, faz download streaming

### Semana 3: Ingest (Parser + Process)
- [ ] Gabi.Ingest.Parser (CSV, HTML, PDF, JSON)
- [ ] Gabi.Ingest.Fingerprint
- [ ] Gabi.Ingest.Deduplication
- [ ] Gabi.Ingest.Chunker
- **Entregável:** Parse completo, gera chunks

### Semana 4: Sync + Worker
- [ ] Gabi.Sync (bypass, insert, update, delete)
- [ ] Gabi.Worker (orchestração, DI)
- [ ] Docker compose
- **Entregável:** Pipeline end-to-end funciona

### Semana 5: Polish + Testes
- [ ] Testes de integração
- [ ] Configuração de profiles
- [ ] Scripts de deploy
- [ ] Documentação
- **Entregável:** Produção-ready

**Total estimado:** 5 semanas (~40-50 horas de trabalho focado)

---

## Decisões Arquiteturais Registradas

| ADR | Tópico | Decisão |
|-----|--------|---------|
| 001 | Modular Architecture | 6 camadas estritas, import só de baixo |
| 002 | Sources.yaml v2 | Estrutura alinhada com apps |
| 003 | Apps Definition | Gabi.Postgres = infra, Gabi.Sync = lógica de sync, Gabi.Worker = orquestrador |
| 004 | Banco de Dados | PostgreSQL 16 + pgvector (justificado) |
| 005 | Migrations | EF Core code-based (não Flyway/Liquibase) |

---

## Próximos Passos Imediatos

1. **Aprovar este planejamento**
2. **Criar branch:** `git checkout -b refactor/gabi-sync-csharp`
3. **Iniciar Semana 1:** Solution + projetos vazios
4. **Review após Semana 1:** Validar contratos antes de prosseguir

---

## Referências

- `docs/adr/001-gabi-sync-modular-architecture.md`
- `docs/adr/002-sources-yaml-v2.md`
- `docs/adr/003-gabi-apps-definition.md`
- `grounding_docs/archive/legacy-python/` (codigo legado curado para referencia)
