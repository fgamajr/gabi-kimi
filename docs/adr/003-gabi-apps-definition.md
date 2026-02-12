# ADR 003: GABI Apps Definition & Responsibilities

**Status:** Proposed  
**Date:** 2026-02-12  
**Author:** GABI Team  
**Decision:** Define clear app boundaries with Gabi.Postgres as infrastructure app

---

## Context

Durante o design da arquitetura modular, surgiram dúvidas sobre:
1. Onde ficam as migrations (EF Core vs external tool)
2. Qual o escopo exato de cada app
3. Quem faz o CRUD na base (bypass, update, insert, delete)

## Decision

### App Definitions

```
GABI Ecosystem - Apps com responsabilidades claras

┌─────────────────────────────────────────────────────────────────┐
│                    INFRASTRUCTURE LAYER                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Gabi.Contracts          Layer 0-1                               │
│  ├── Records, Enums, Interfaces                                  │
│  └── Zero dependencies                                             │
│                                                                  │
│  Gabi.Postgres           Layer 2-3   ← INFRASTRUCTURE APP       │
│  ├── EF Core DbContext                                            │
│  ├── Migrations (code-based)                                      │
│  ├── Entity Configurations (Fluent API)                          │
│  ├── Repository Pattern                                            │
│  └── Connection/Transaction management                           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    DOMAIN LAYER                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Gabi.Discover           Layer 4a                                │
│  ├── DiscoveryEngine                                              │
│  ├── URL pattern resolution                                       │
│  ├── ChangeDetection (ETag, Last-Modified)                       │
│  └── Output: IEnumerable<DiscoveredSource>                       │
│                                                                  │
│  Gabi.Ingest             Layer 4b                                │
│  ├── Fetcher (HTTP, streaming, SSRF)                             │
│  ├── Parser (CSV, HTML, PDF, JSON)                               │
│  ├── Fingerprint (SHA256 content hash)                           │
│  ├── Deduplication (query existing fingerprints)                 │
│  ├── Chunker (semantic splitting)                                │
│  └── Output: IEnumerable<ParsedDocument> with chunks             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                 SYNCHRONIZATION LAYER                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Gabi.Sync               Layer 5                                 │
│  ├── SynchronizationEngine                                        │
│  ├── Diff/Compare (source vs database)                           │
│  ├── Merge strategies:                                           │
│  │   ├── Bypass: Documento não mudou, ignora                    │
│  │   ├── Insert: Novo documento                                 │
│  │   ├── Update: Documento existe, conteúdo mudou               │
│  │   └── Delete: Documento removido na fonte (soft delete)      │
│  ├── Transaction coordination                                     │
│  └── Change tracking (what changed, when)                        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  ORCHESTRATION LAYER                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Gabi.Worker             Entry Point                             │
│  ├── BackgroundService (IHostedService)                          │
│  ├── DI Container Setup                                          │
│  ├── Pipeline orchestration:                                     │
│  │   Discover → Ingest → Sync (via Gabi.Sync)                   │
│  ├── Scheduling (cron)                                           │
│  └── Graceful shutdown                                           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

#### 1. Migrations são código (EF Core Migrations)

**NÃO usar ferramentas externas** (Flyway, Liquibase). EF Core Migrations são:
- Versionadas no código (Git)
- Type-safe (compilador verifica)
- Testáveis (migrations rodam em testes de integração)
- C# nativo (consistência com stack)

```csharp
// Gabi.Postgres/Migrations/20240212000001_Initial.cs
public partial class Initial : Migration
{
    protected override void Up(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.CreateTable(
            name: "documents",
            columns: table => new
            {
                id = table.Column<Guid>(type: "uuid", nullable: false),
                source_id = table.Column<string>(type: "text", nullable: false),
                // ...
            },
            constraints: table =>
            {
                table.PrimaryKey("pk_documents", x => x.id);
            });
            
        // pgvector extension
        migrationBuilder.Sql("CREATE EXTENSION IF NOT EXISTS vector;");
    }
}
```

**Comandos:**
```bash
# Criar migration
dotnet ef migrations add AddDocumentChunks --project Gabi.Postgres

# Aplicar migrations (app startup ou CLI)
dotnet ef database update --project Gabi.Postgres
```

#### 2. Gabi.Postgres é um Infrastructure App

Responsabilidades:
- Definir schema (migrations)
- Configurar EF Core (DbContext, entities)
- Implementar Repository Pattern
- Gerenciar conexões e transações
- Extension methods para DI (`services.AddGabiPostgres()`)

**NÃO contém:**
- Lógica de negócio (fingerprint, dedup)
- Regras de sincronização (diff, merge)
- Orquestração

```csharp
// Gabi.Postgres/GabiDbContext.cs
public class GabiDbContext : DbContext
{
    public DbSet<SourceRegistry> Sources { get; set; }
    public DbSet<Document> Documents { get; set; }
    public DbSet<DocumentChunk> Chunks { get; set; }
    
    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.ApplyConfigurationsFromAssembly(typeof(GabiDbContext).Assembly);
    }
}

// Gabi.Postgres/Repositories/IDocumentRepository.cs
public interface IDocumentRepository
{
    Task<Document?> GetByFingerprintAsync(string fingerprint);
    Task UpsertAsync(Document document);  // Insert or Update
    Task SoftDeleteAsync(string documentId);
    Task<bool> ExistsAsync(string documentId);
}
```

#### 3. Gabi.Sync é o Especialista em Sincronização

Responsabilidade: Decidir **o que fazer** com cada documento (bypass, insert, update, delete).

**NÃO é orquestrador** - é especialista em lógica de sync.

```csharp
// Gabi.Sync/SyncEngine.cs
public class SyncEngine
{
    public async Task<SyncResult> SynchronizeAsync(
        ParsedDocument parsedDoc, 
        CancellationToken ct)
    {
        var existing = await _docRepo.GetByFingerprintAsync(parsedDoc.Fingerprint);
        
        if (existing == null)
        {
            // INSERT
            await _docRepo.AddAsync(parsedDoc.ToEntity());
            return SyncResult.Inserted;
        }
        
        if (existing.ContentHash == parsedDoc.ContentHash)
        {
            // BYPASS - nothing changed
            return SyncResult.Bypassed;
        }
        
        // UPDATE - content changed
        existing.UpdateFrom(parsedDoc);
        await _docRepo.UpdateAsync(existing);
        return SyncResult.Updated;
    }
}

public enum SyncResult
{
    Bypassed,   // No change detected
    Inserted,   // New document
    Updated,    // Existing document changed
    Deleted,    // Soft delete
    Failed      // Error
}
```

#### 4. Gabi.Worker é o Orquestrador

Responsabilidade: Coordenar o fluxo completo (pipeline).

```csharp
// Gabi.Worker/PipelineOrchestrator.cs
public class PipelineOrchestrator : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            // 1. DISCOVER
            var sources = await _discover.DiscoverAsync("tcu_normas");
            
            foreach (var source in sources)
            {
                // 2. INGEST (fetch + parse + chunk)
                var documents = await _ingest.ProcessAsync(source);
                
                foreach (var doc in documents)
                {
                    // 3. SYNC (diff + merge)
                    var result = await _sync.SynchronizeAsync(doc, ct);
                    _logger.LogInformation("Document {Id}: {Result}", doc.Id, result);
                }
            }
            
            await Task.Delay(TimeSpan.FromHours(24), ct);
        }
    }
}
```

### Data Flow Detail

```
┌─────────────────────────────────────────────────────────────────┐
│                     DATA FLOW                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Source (CSV)                                                    │
│      │                                                          │
│      ▼                                                          │
│  Gabi.Discover                                                   │
│      └── DiscoveredSource { Url, Metadata }                     │
│      │                                                          │
│      ▼                                                          │
│  Gabi.Ingest                                                     │
│      ├── Fetcher → FetchedContent (streaming bytes)             │
│      ├── Parser → ParsedDocument (structured data)              │
│      ├── Fingerprint → hash                                     │
│      ├── Deduplication → query Gabi.Postgres (exists?)          │
│      ├── Chunker → List<Chunk>                                  │
│      └── ParsedDocument with chunks                             │
│      │                                                          │
│      ▼                                                          │
│  Gabi.Sync                                                       │
│      ├── Compare with existing (via Gabi.Postgres repo)         │
│      ├── Decision: Bypass | Insert | Update | Delete            │
│      └── Execute via Gabi.Postgres repository                   │
│      │                                                          │
│      ▼                                                          │
│  Gabi.Postgres                                                   │
│      ├── EF Core tracking                                       │
│      ├── SQL generation                                         │
│      └── Transaction commit                                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Plugin Architecture (Futuro)

Apps futuros seguem mesmo padrão:

```
Gabi.TEI (Plugin)
├── ITeiClient interface
├── HttpClient implementation
├── Registrado no DI condicionalmente
└── Chamado por Gabi.Ingest quando enabled

Gabi.Elastic (Plugin)
├── IIndexer interface  
├── ElasticClient implementation
├── Registrado no DI condicionalmente
└── Chamado por Gabi.Worker após sync
```

### Project Dependencies (Clean Architecture)

```
Gabi.Contracts
    └── (no dependencies)

Gabi.Postgres
    ├── Gabi.Contracts
    └── EF Core, Npgsql

Gabi.Discover
    ├── Gabi.Contracts
    └── HttpClient

Gabi.Ingest
    ├── Gabi.Contracts
    ├── Gabi.Postgres (para dedup query)
    └── HttpClient, CsvHelper, etc

Gabi.Sync
    ├── Gabi.Contracts
    ├── Gabi.Postgres (para CRUD)
    └── (no direct ingest/discover deps)

Gabi.Worker
    ├── ALL above
    └── Microsoft.Extensions.Hosting
```

## Consequences

### Positive

1. **Gabi.Postgres isolado**: Pode trocar EF Core por Dapper futuramente sem afetar outros apps
2. **Gabi.Sync testável**: Lógica de diff/merge testável sem banco real (mock repository)
3. **Migrations versionadas**: Schema evolui com código
4. **Clear boundaries**: Cada app tem uma responsabilidade única

### Trade-offs

1. **Repository overhead**: Algumas operações simples precisam passar por repository
2. **Migrations acumulam**: Depois de 1 ano, teremos dezenas de arquivos de migration
   - Mitigação: Squash migrations em releases maiores

## Implementation Notes

### Startup Sequence

```csharp
// Gabi.Worker/Program.cs
var builder = Host.CreateApplicationBuilder(args);

// 1. Infrastructure (order matters)
builder.Services.AddGabiPostgres(builder.Configuration);

// 2. Domain
builder.Services.AddGabiDiscover();
builder.Services.AddGabiIngest();
builder.Services.AddGabiSync();

// 3. Worker
builder.Services.AddHostedService<PipelineOrchestrator>();

// 4. Plugins (conditional)
if (builder.Configuration.GetValue<bool>("Features:Embeddings:Enabled"))
{
    builder.Services.AddGabiTei();
}

var host = builder.Build();

// Ensure database is migrated (dev environment)
using (var scope = host.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
    await db.Database.MigrateAsync();
}

await host.RunAsync();
```

## References

- ADR 001: Modular Architecture
- ADR 002: Sources.yaml v2
- EF Core Migrations: https://docs.microsoft.com/ef/core/managing-schemas/migrations/
- Repository Pattern: https://docs.microsoft.com/dotnet/architecture/microservices/microservice-ddd-cqrs-patterns/infrastructure-persistence-layer-design
