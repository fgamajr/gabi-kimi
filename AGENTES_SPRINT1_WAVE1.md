# 🚀 SPRINT 1 - WAVE 1: Agentes Prontos para Lançamento

**Data**: 2026-02-12  
**Agentes**: C1 + C6 (2 agentes)  
**Próxima Wave**: C2 + C4 (assim que C1 entregar interfaces)

---

## 👤 AGENTE C1: Gabi.Jobs Setup

### 🎯 Objetivo
Criar o projeto Gabi.Jobs com as interfaces fundamentais para o sistema de jobs hierárquicos.

### 📋 Entregáveis

#### 1. Projeto
```bash
src/Gabi.Jobs/
├── Gabi.Jobs.csproj
├── README.md
├── Interfaces/
│   ├── IJobFactory.cs
│   ├── IJobCreator.cs
│   ├── IJobStateMachine.cs
│   └── IJobWorker.cs
├── Models/
│   ├── JobHierarchy.cs
│   └── JobContext.cs
└── DependencyInjection.cs
```

#### 2. Interfaces a Definir

**IJobFactory.cs**
```csharp
public interface IJobFactory
{
    /// <summary>Cria job pai para uma source</summary>
    Task<IngestJob> CreateSourceJobAsync(string sourceId, DiscoveryResult result, CancellationToken ct);
    
    /// <summary>Cria jobs filhos para documentos (batch)</summary>
    Task<IReadOnlyList<IngestJob>> CreateDocumentJobsAsync(Guid parentJobId, IEnumerable<DocumentInfo> docs, CancellationToken ct);
    
    /// <summary>Cria job individual genérico</summary>
    Task<IngestJob> CreateJobAsync(string jobType, string sourceId, JobPayload payload, CancellationToken ct);
}
```

**IJobCreator.cs**
```csharp
public interface IJobCreator
{
    string JobType { get; }
    bool CanCreate(JobContext context);
    Task<IngestJob> CreateAsync(JobContext context, CancellationToken ct);
}

// Implementações específicas:
// - ISourceJobCreator : IJobCreator
// - IDocumentJobCreator : IJobCreator
```

**IJobStateMachine.cs**
```csharp
public interface IJobStateMachine
{
    // Estados possíveis
    IReadOnlyList<JobStatus> GetValidTransitions(JobStatus current);
    
    // Transições
    Task<IngestJob> TransitionAsync(IngestJob job, JobStatus toStatus, CancellationToken ct);
    Task<IngestJob> StartAsync(IngestJob job, string workerId, CancellationToken ct);
    Task<IngestJob> CompleteAsync(IngestJob job, JobResult result, CancellationToken ct);
    Task<IngestJob> FailAsync(IngestJob job, string error, CancellationToken ct);
    Task<IngestJob> RetryAsync(IngestJob job, CancellationToken ct);
    
    // Eventos
    event EventHandler<JobTransitionEvent>? OnTransition;
    event EventHandler<JobCompletedEvent>? OnCompleted;
    event EventHandler<JobFailedEvent>? OnFailed;
}
```

**IJobWorker.cs**
```csharp
public interface IJobWorker
{
    string JobType { get; }
    Task<JobResult> ExecuteAsync(IngestJob job, CancellationToken ct);
}
```

#### 3. Models

**JobHierarchy.cs**
```csharp
public record JobHierarchy
{
    public Guid ParentJobId { get; init; }
    public IReadOnlyList<Guid> ChildJobIds { get; init; } = Array.Empty<Guid>();
    public int TotalChildren { get; init; }
    public int CompletedChildren { get; init; }
    public int FailedChildren { get; init; }
}
```

**JobContext.cs**
```csharp
public record JobContext
{
    public string SourceId { get; init; } = null!;
    public string? DocumentId { get; init; }
    public long? LinkId { get; init; }
    public Guid? ParentJobId { get; init; }
    public JobPriority Priority { get; init; } = JobPriority.Normal;
    public Dictionary<string, object> Metadata { get; init; } = new();
}
```

#### 4. DependencyInjection
```csharp
public static IServiceCollection AddGabiJobs(this IServiceCollection services)
{
    services.AddSingleton<IJobFactory, JobFactory>();
    services.AddSingleton<IJobStateMachine, JobStateMachine>();
    // Workers serão registrados posteriormente
    return services;
}
```

### ✅ Critérios de Aceitação

1. **Build**: `dotnet build src/Gabi.Jobs/Gabi.Jobs.csproj` passa
2. **Testes**: Interfaces têm mocks que compilam
3. **Referência**: Projeto adicionado à solution
4. **Documentação**: XML docs em todas as interfaces públicas

### ⚠️ Notas
- NÃO implementar as classes concretas ainda (só interfaces)
- C2 e C3 irão implementar IJobCreator concreto
- C4 irá implementar IJobStateMachine concreto
- C5 irá implementar IJobWorker concretos

---

## 👤 AGENTE C6: PipelineOrchestrator + Schema

### 🎯 Objetivo
Extrair o PipelineOrchestrator existente de Gabi.Sync e criar a migration para soft delete + natural key.

### 📋 Entregáveis

#### 1. Extração do PipelineOrchestrator

**Arquivo existente**: `src/Gabi.Sync/Pipeline/PipelineOrchestrator.cs`

**Tarefas**:
- [ ] Mover para `src/Gabi.Pipeline/PipelineOrchestrator.cs`
- [ ] Atualizar namespace: `Gabi.Sync` → `Gabi.Pipeline`
- [ ] Extrair interface `IPipelineOrchestrator`
- [ ] Adicionar fase de Reconcile ao fluxo:
  ```csharp
  public enum PipelinePhase
  {
      Discovery,
      Fetch,
      Reconcile,  // NOVO
      Hash,
      Parse,
      Chunk,
      Embed,
      Index
  }
  ```

#### 2. Novo Projeto Gabi.Pipeline

```bash
src/Gabi.Pipeline/
├── Gabi.Pipeline.csproj
├── IPipelineOrchestrator.cs
├── PipelineOrchestrator.cs  # (extraído de Gabi.Sync)
├── PhaseCoordinator.cs
├── CircuitBreaker.cs
└── DependencyInjection.cs
```

#### 3. Migration: AddSoftDeleteAndNaturalKey

**Arquivo**: `src/Gabi.Postgres/Migrations/20260213000000_AddSoftDeleteAndNaturalKey.cs`

**Schema Changes**:

```csharp
// IngestJobEntity - adicionar:
public string? ParentJobId { get; set; }
public string? DocumentId { get; set; }
public string? ContentHash { get; set; }
public bool? IsDuplicate { get; set; }

// DocumentEntity - adicionar:
public string ExternalId { get; set; } = null!;  // Natural Key
public string SourceId { get; set; } = null!;
public string ContentHash { get; set; } = null!;
public string HashAlgorithm { get; set; } = "sha256";
public long ContentSize { get; set; }
public DateTime? RemovedFromSourceAt { get; set; }  // Soft delete
public string? RemovedReason { get; set; }  // "source_deleted", "manual", "expired"
public bool IsDuplicate { get; set; }
public string? OriginalDocumentId { get; set; }

// Índices:
// - IX_Documents_SourceId_ExternalId (unique)
// - IX_Documents_ContentHash_SourceId
// - IX_Documents_RemovedFromSourceAt
// - IX_Jobs_ParentJobId
// - IX_Jobs_DocumentId
```

#### 4. ReconcileService (stub inicial)

```csharp
public interface IReconcileService
{
    Task<ReconcileResult> ReconcileAsync(string sourceId, Snapshot snapshot, CancellationToken ct);
}

public class ReconcileResult
{
    public int Added { get; init; }
    public int Updated { get; init; }
    public int Removed { get; init; }  // Soft delete
    public int Unchanged { get; init; }
    public IReadOnlyList<string> Errors { get; init; } = Array.Empty<string>();
}

public record Snapshot
{
    public string SourceId { get; init; } = null!;
    public DateTime CapturedAt { get; init; }
    public IReadOnlyList<SnapshotItem> Items { get; init; } = Array.Empty<SnapshotItem>();
}

public record SnapshotItem
{
    public string ExternalId { get; init; } = null!;
    public string Url { get; init; } = null!;
    public string? Title { get; init; }
    public DateTime? DocumentDate { get; init; }
    public string? ContentHash { get; init; }
}
```

### ✅ Critérios de Aceitação

1. **Build**: `dotnet build` passa após mover PipelineOrchestrator
2. **Migration**: `dotnet ef migrations add` cria migration válida
3. **Schema**: Campos novos aparecem no `GabiDbContextModelSnapshot`
4. **Referências**: Gabi.Pipeline referenciado corretamente
5. **Teste Zero Kelvin**: `./scripts/setup.sh` aplica migration sem erros

### ⚠️ Notas Importantes

- O PipelineOrchestrator **JÁ EXISTE** em `src/Gabi.Sync/Pipeline/PipelineOrchestrator.cs`
- É uma EXTRAÇÃO/MIGRAÇÃO, não criação do zero
- Manter histórico git (git mv se possível)
- A migration pode ser grande - focar nos campos essenciais primeiro

---

## 📊 Plano de Execução

```
Hora 0: Lançar C1 + C6
   ↓
Hora 1-4: C1 define interfaces, C6 extrai Pipeline + cria migration
   ↓
Gate: C1 interfaces revisadas? C6 migration aplica?
   ↓
SIM → Lançar WAVE 2 (C2 + C4)
```

---

## 🔗 Coordenação entre C1 e C6

**Ponto de Contato**: `IngestJob` entity

- C1 define como jobs serão criados (interfaces)
- C6 adiciona campos ao banco (ParentJobId, DocumentId, etc.)
- Ambos precisam estar alinhados sobre o modelo de dados

**Recomendação**: C1 e C6 devem se comunicar sobre:
1. Estrutura de `IngestJob` (campos mínimos necessários)
2. Relação pai-filho (ParentJobId)
3. Identificação de documento (DocumentId)

---

## 🎯 Sucesso da Wave 1

✅ **C1 entregue**: Interfaces definidas, próximos agentes (C2, C3, C4, C5) podem começar  
✅ **C6 entregue**: PipelineOrchestrator extraído, schema atualizado com soft delete  
✅ **Próximo passo**: Lançar Wave 2 (C2 + C4)
