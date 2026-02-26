# Pipeline State Machine Design

> **Status:** Design Document  
> **Context:** GABI Ingest Pipeline - 1GB RAM constraint (Fly.io)  
> **Date:** 2026-02-12

---

## Overview

This document defines a robust state machine for the GABI document ingestion pipeline. The design addresses:

- **Reliability:** Resume from interruptions without data loss
- **Consistency:** Multi-stage transactions with compensation
- **Observability:** Full traceability of document lifecycle
- **Efficiency:** Memory-conscious processing for 1GB RAM environments

---

## 1. Document State Machine

### 1.1 States Enum

```csharp
namespace Gabi.Contracts.StateMachine;

/// <summary>
/// Estados do pipeline de ingestão de documentos.
/// Designado para PostgreSQL (string conversion).
/// </summary>
public enum IngestState
{
    // ═══════════════════════════════════════════════════════════════
    // Estados Iniciais
    // ═══════════════════════════════════════════════════════════════
    
    /// <summary>Documento descoberto, aguardando processamento.</summary>
    Discovered,
    
    /// <summary>Documento em fila para fetch.</summary>
    FetchQueued,
    
    // ═══════════════════════════════════════════════════════════════
    // Estados de Processamento (Fetch → Parse)
    // ═══════════════════════════════════════════════════════════════
    
    /// <summary>Baixando conteúdo da fonte.</summary>
    Fetching,
    
    /// <summary>Fetch completo, aguardando parse.</summary>
    Fetched,
    
    /// <summary>Extraindo texto estruturado.</summary>
    Parsing,
    
    /// <summary>Parse completo, documento canônico pronto.</summary>
    Parsed,
    
    // ═══════════════════════════════════════════════════════════════
    // Estados de Validação (Fingerprint → Deduplication)
    // ═══════════════════════════════════════════════════════════════
    
    /// <summary>Calculando fingerprint SHA-256.</summary>
    Fingerprinting,
    
    /// <summary>Verificando duplicatas no banco.</summary>
    Deduplicating,
    
    /// <summary>Documento duplicado (skip).</summary>
    DuplicateDetected,
    
    // ═══════════════════════════════════════════════════════════════
    // Estados de Transformação (Normalize → Chunk)
    // ═══════════════════════════════════════════════════════════════
    
    /// <summary>Aplicando transforms declarativos.</summary>
    Normalizing,
    
    /// <summary>Dividindo em chunks.</summary>
    Chunking,
    
    /// <summary>Chunks gerados, pronto para embedding.</summary>
    Chunked,
    
    // ═══════════════════════════════════════════════════════════════
    // Estados de Vetorização (Embed)
    // ═══════════════════════════════════════════════════════════════
    
    /// <summary>Gerando embeddings (batched).</summary>
    Embedding,
    
    /// <summary>Embeddings gerados.</summary>
    Embedded,
    
    // ═══════════════════════════════════════════════════════════════
    // Estados de Persistência (Index)
    // ═══════════════════════════════════════════════════════════════
    
    /// <summary>Persistindo no PostgreSQL (canônico).</summary>
    IndexingPostgres,
    
    /// <summary>Persistindo no Elasticsearch (derivado).</summary>
    IndexingElasticsearch,
    
    /// <summary>Persistindo no Neo4j (grafo).</summary>
    IndexingGraph,
    
    // ═══════════════════════════════════════════════════════════════
    // Estados Finais
    // ═══════════════════════════════════════════════════════════════
    
    /// <summary>Documento completamente processado.</summary>
    Completed,
    
    /// <summary>Documento marcado como deletado (soft delete).</summary>
    Deleted,
    
    // ═══════════════════════════════════════════════════════════════
    // Estados de Erro (DLQ - Dead Letter Queue)
    // ═══════════════════════════════════════════════════════════════
    
    /// <summary>Falha no fetch (retryable).</summary>
    FetchFailed,
    
    /// <summary>Falha no parse (não retryable).</summary>
    ParseFailed,
    
    /// <summary>Falha no embedding (retryable).</summary>
    EmbedFailed,
    
    /// <summary>Falha na indexação (retryable).</summary>
    IndexFailed,
    
    /// <summary>Máximo de tentativas excedido (DLQ).</summary>
    DeadLettered,
    
    /// <summary>Cancelado por intervenção humana.</summary>
    Cancelled
}
```

### 1.2 State Transitions Graph

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         PIPELINE STATE MACHINE                                   │
└─────────────────────────────────────────────────────────────────────────────────┘

                         ┌─────────────┐
                    ┌───▶│  Discovered │◀─── DiscoveryEngine
                    │    └──────┬──────┘
                    │           │
                    │           ▼
                    │    ┌─────────────┐
                    │    │ FetchQueued │──── Enfileirado para download
                    │    └──────┬──────┘
                    │           │
         Retryable  │           ▼
         Failures   │    ┌─────────────┐
           │        └─── │  Fetching   │──── HTTP Download (streaming)
           │              └──────┬──────┘
           │                     │
           │         ┌───────────┴───────────┐
           │         │                       │
           │         ▼                       ▼
           │  ┌─────────────┐         ┌─────────────┐
           │  │   Fetched   │         │ FetchFailed │──── max_retries? ───┐
           │  └──────┬──────┘         └──────┬──────┘                    │
           │         │                       │                            │
           │         ▼                       │                            │
           │  ┌─────────────┐                │                            │
           │  │   Parsing   │                │                            │
           │  └──────┬──────┘                │                            │
           │         │                       │                            │
           │         ▼                       ▼                            │
           │  ┌─────────────┐         ┌─────────────┐                     │
           │  │   Parsed    │         │ ParseFailed │──── (não retry)     │
           │  └──────┬──────┘         └──────┬──────┘                     │
           │         │                       │                            │
           │         ▼                       ▼                            │
           │  ┌─────────────┐         ┌─────────────┐                     │
           └───┤ Fingerprint │         │DeadLettered │◀───────────────────┘
               └──────┬──────┘         └─────────────┘
                      │                        ▲
                      ▼                        │
               ┌─────────────┐                 │
               │Deduplicating│─────────────────┘
               └──────┬──────┘     max_retries exceeded
                      │
         ┌────────────┴────────────┐
         │                         │
         ▼                         ▼
  ┌─────────────┐          ┌─────────────┐
  │DuplicateDet │          │ Normalizing │──── Transforms aplicados
  │  (skip)     │          └──────┬──────┘
  └─────────────┘                 │
                                  ▼
                           ┌─────────────┐
                           │   Chunking  │──── Split em chunks
                           └──────┬──────┘
                                  │
                                  ▼
                           ┌─────────────┐
                           │   Chunked   │
                           └──────┬──────┘
                                  │
              ┌───────────────────┼───────────────────┐
              │                   │                   │
              ▼                   ▼                   ▼
       ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
       │  Embedding  │     │EmbedSkipped │     │ EmbedFailed │──── retry?
       └──────┬──────┘     │(optional)   │     └──────┬──────┘
              │            └─────────────┘            │
              ▼                                       │
       ┌─────────────┐                                │
       │   Embedded  │◀───────────────────────────────┘
       └──────┬──────┘
              │
    ┌─────────┴─────────┬─────────────────┐
    │                   │                 │
    ▼                   ▼                 ▼
┌──────────┐     ┌──────────┐     ┌──────────┐
│ IndexPG  │     │ IndexES  │     │ IndexGraph│── (paralelo seguro)
│(canônico)│     │(derivado)│     │(opcional) │
└────┬─────┘     └────┬─────┘     └─────┬────┘
     │                │                 │
     └────────────────┼─────────────────┘
                      │
                      ▼
               ┌─────────────┐
               │  Completed  │──── ✅ Sucesso!
               └─────────────┘
                      │
           Soft Delete│
                      ▼
               ┌─────────────┐
               │   Deleted   │──── Soft delete
               └─────────────┘
```

### 1.3 State Entity (PostgreSQL)

```csharp
namespace Gabi.Postgres.StateMachine;

/// <summary>
/// Entidade de estado do pipeline (tabela: pipeline_states).
/// Uma linha por documento, atualizada atomicamente.
/// </summary>
public class PipelineStateEntity
{
    // Identificação
    public Guid Id { get; set; }
    public string DocumentId { get; set; } = string.Empty;
    public string SourceId { get; set; } = string.Empty;
    public string Url { get; set; } = string.Empty;
    
    // Estado atual
    public IngestState CurrentState { get; set; } = IngestState.Discovered;
    public IngestState? PreviousState { get; set; }
    
    // Checkpoint (para resume)
    public string? CheckpointData { get; set; }  // JSON: offset, batch_id, etc.
    public long? StreamOffset { get; set; }      // Para streams interrompidos
    public int? BatchIndex { get; set; }         // Índice no batch atual
    
    // Retry logic
    public int RetryCount { get; set; }
    public DateTime? LastRetryAt { get; set; }
    public DateTime? NextRetryAt { get; set; }
    public string? LastError { get; set; }
    public string? ErrorCategory { get; set; }   // network, parse, embed, etc.
    
    // Saga tracking
    public Guid? SagaId { get; set; }            // ID da saga atual
    public int SagaStepIndex { get; set; }       // Passo atual na saga
    
    // Performance tracking
    public DateTime? StateChangedAt { get; set; }
    public DateTime? StartedAt { get; set; }
    public DateTime? CompletedAt { get; set; }
    public Dictionary<string, TimeSpan> StageDurations { get; set; } = new();
    
    // Metadata
    public long ContentSizeBytes { get; set; }
    public int ChunkCount { get; set; }
    public int EmbeddingCount { get; set; }
    public string? Fingerprint { get; set; }
    
    // Controle de concorrência (optimistic locking)
    public uint RowVersion { get; set; }
    
    // Soft delete
    public bool IsDeleted { get; set; }
    public DateTime? DeletedAt { get; set; }
}
```

---

## 2. Saga Pattern for Multi-Stage Transactions

### 2.1 Saga Definition

```csharp
namespace Gabi.Contracts.StateMachine;

/// <summary>
/// Define uma saga de processamento com compensações.
/// </summary>
public interface IIngestSaga
{
    Guid SagaId { get; }
    string DocumentId { get; }
    IReadOnlyList<SagaStep> Steps { get; }
    int CurrentStepIndex { get; }
    SagaStatus Status { get; }
    
    /// <summary>Executa o próximo passo da saga.</summary>
    Task<SagaResult> ExecuteNextAsync(CancellationToken ct = default);
    
    /// <summary>Compensa (rollback) a partir do passo atual.</summary>
    Task<SagaResult> CompensateAsync(CancellationToken ct = default);
}

public enum SagaStatus
{
    Pending,
    Running,
    Completed,
    Compensating,
    Compensated,
    Failed
}

/// <summary>
/// Passo individual da saga.
/// </summary>
public class SagaStep
{
    public required string Name { get; init; }
    public required int Order { get; init; }
    public required IngestState TargetState { get; init; }
    public required IngestState? PreviousState { get; init; }
    
    /// <summary>Ação principal (avanço).</summary>
    public required Func<CancellationToken, Task<StepResult>> Action { get; init; }
    
    /// <summary>Ação de compensação (rollback).</summary>
    public required Func<CancellationToken, Task<StepResult>> Compensation { get; init; }
    
    /// <summary>Se true, falha aqui dispara compensação de todos os passos anteriores.</summary>
    public bool RequireCompensationOnFailure { get; init; } = true;
    
    /// <summary>Se true, passo é idempotente (pode ser repetido).</summary>
    public bool IsIdempotent { get; init; } = true;
}

public record StepResult
{
    public bool Success { get; init; }
    public string? ErrorMessage { get; init; }
    public IngestState? NewState { get; init; }
    public Dictionary<string, object>? Output { get; init; }
}

public record SagaResult
{
    public bool Success { get; init; }
    public SagaStatus FinalStatus { get; init; }
    public string? ErrorMessage { get; init; }
    public int StepsCompleted { get; init; }
    public int StepsCompensated { get; init; }
}
```

### 2.2 Standard Ingest Saga

```csharp
namespace Gabi.Sync.StateMachine;

/// <summary>
/// Saga padrão de ingestão de documento.
/// 7 estágios principais com compensações.
/// </summary>
public class StandardIngestSaga : IIngestSaga
{
    private readonly ILogger<StandardIngestSaga> _logger;
    private readonly IPipelineStateRepository _stateRepo;
    private readonly IServiceProvider _services;
    
    public Guid SagaId { get; }
    public string DocumentId { get; }
    public IReadOnlyList<SagaStep> Steps { get; private set; } = Array.Empty<SagaStep>();
    public int CurrentStepIndex { get; private set; }
    public SagaStatus Status { get; private set; }

    public StandardIngestSaga(
        string documentId,
        IPipelineStateRepository stateRepo,
        IServiceProvider services,
        ILogger<StandardIngestSaga> logger)
    {
        SagaId = Guid.NewGuid();
        DocumentId = documentId;
        _stateRepo = stateRepo;
        _services = services;
        _logger = logger;
        
        BuildSteps();
    }

    private void BuildSteps()
    {
        var steps = new List<SagaStep>
        {
            // ═══════════════════════════════════════════════════════════
            // STEP 1: FETCH
            // ═══════════════════════════════════════════════════════════
            new()
            {
                Name = "Fetch",
                Order = 1,
                TargetState = IngestState.Fetched,
                PreviousState = IngestState.FetchQueued,
                IsIdempotent = true,  // HTTP GET é idempotente
                RequireCompensationOnFailure = false,  // Nada para compensar ainda
                Action = async ct => await ExecuteFetchAsync(ct),
                Compensation = async ct => await CompensateFetchAsync(ct)  // No-op
            },
            
            // ═══════════════════════════════════════════════════════════
            // STEP 2: PARSE
            // ═══════════════════════════════════════════════════════════
            new()
            {
                Name = "Parse",
                Order = 2,
                TargetState = IngestState.Parsed,
                PreviousState = IngestState.Fetched,
                IsIdempotent = true,
                RequireCompensationOnFailure = true,
                Action = async ct => await ExecuteParseAsync(ct),
                Compensation = async ct => await CompensateParseAsync(ct)  // Libera memória
            },
            
            // ═══════════════════════════════════════════════════════════
            // STEP 3: FINGERPRINT + DEDUPLICATE
            // ═══════════════════════════════════════════════════════════
            new()
            {
                Name = "Deduplicate",
                Order = 3,
                TargetState = IngestState.Deduplicating,
                PreviousState = IngestState.Parsed,
                IsIdempotent = true,
                RequireCompensationOnFailure = false,  // Read-only operation
                Action = async ct => await ExecuteDeduplicateAsync(ct),
                Compensation = async ct => StepResult.NoOp()
            },
            
            // ═══════════════════════════════════════════════════════════
            // STEP 4: NORMALIZE + CHUNK
            // ═══════════════════════════════════════════════════════════
            new()
            {
                Name = "Chunk",
                Order = 4,
                TargetState = IngestState.Chunked,
                PreviousState = IngestState.Deduplicating,
                IsIdempotent = true,
                RequireCompensationOnFailure = true,
                Action = async ct => await ExecuteChunkAsync(ct),
                Compensation = async ct => await CompensateChunkAsync(ct)
            },
            
            // ═══════════════════════════════════════════════════════════
            // STEP 5: EMBED
            // ═══════════════════════════════════════════════════════════
            new()
            {
                Name = "Embed",
                Order = 5,
                TargetState = IngestState.Embedded,
                PreviousState = IngestState.Chunked,
                IsIdempotent = false,  // API calls custosas
                RequireCompensationOnFailure = true,
                Action = async ct => await ExecuteEmbedAsync(ct),
                Compensation = async ct => await CompensateEmbedAsync(ct)
            },
            
            // ═══════════════════════════════════════════════════════════
            // STEP 6: INDEX (PostgreSQL + Elasticsearch + Graph)
            // ═══════════════════════════════════════════════════════════
            new()
            {
                Name = "Index",
                Order = 6,
                TargetState = IngestState.Completed,
                PreviousState = IngestState.Embedded,
                IsIdempotent = false,  // Writes são parciais
                RequireCompensationOnFailure = true,
                Action = async ct => await ExecuteIndexAsync(ct),
                Compensation = async ct => await CompensateIndexAsync(ct)  // Critical!
            }
        };
        
        Steps = steps.AsReadOnly();
    }

    public async Task<SagaResult> ExecuteNextAsync(CancellationToken ct = default)
    {
        if (CurrentStepIndex >= Steps.Count)
            return SagaResult.Completed();

        var step = Steps[CurrentStepIndex];
        Status = SagaStatus.Running;

        _logger.LogInformation(
            "Saga {SagaId} - Executing step {Step}/{Total}: {StepName}",
            SagaId, step.Order, Steps.Count, step.Name);

        try
        {
            // Pre-step: Atualiza estado
            await _stateRepo.TransitionAsync(DocumentId, step.TargetState, ct);
            
            // Execute action
            var result = await step.Action(ct);
            
            if (result.Success)
            {
                CurrentStepIndex++;
                
                if (CurrentStepIndex >= Steps.Count)
                {
                    Status = SagaStatus.Completed;
                    await _stateRepo.MarkCompletedAsync(DocumentId, ct);
                }
                
                return new SagaResult
                {
                    Success = true,
                    FinalStatus = Status,
                    StepsCompleted = CurrentStepIndex
                };
            }
            else
            {
                // Falha no passo
                if (step.RequireCompensationOnFailure && CurrentStepIndex > 0)
                {
                    _logger.LogError(
                        "Step {StepName} failed, triggering compensation",
                        step.Name);
                    return await CompensateAsync(ct);
                }
                else
                {
                    Status = SagaStatus.Failed;
                    await _stateRepo.MarkFailedAsync(DocumentId, result.ErrorMessage, ct);
                    
                    return new SagaResult
                    {
                        Success = false,
                        FinalStatus = Status,
                        ErrorMessage = result.ErrorMessage,
                        StepsCompleted = CurrentStepIndex
                    };
                }
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Exception in step {StepName}", step.Name);
            
            if (step.RequireCompensationOnFailure)
            {
                return await CompensateAsync(ct);
            }
            
            throw;
        }
    }

    public async Task<SagaResult> CompensateAsync(CancellationToken ct = default)
    {
        Status = SagaStatus.Compensating;
        var compensated = 0;
        
        _logger.LogWarning(
            "Saga {SagaId} - Starting compensation from step {Step}",
            SagaId, CurrentStepIndex);

        // Compensa em ordem reversa
        for (int i = CurrentStepIndex - 1; i >= 0; i--)
        {
            var step = Steps[i];
            
            try
            {
                _logger.LogInformation(
                    "Compensating step: {StepName}", step.Name);
                
                await step.Compensation(ct);
                await _stateRepo.TransitionAsync(DocumentId, step.PreviousState ?? IngestState.FetchQueued, ct);
                compensated++;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, 
                    "Compensation failed for step {StepName}! Manual intervention required.",
                    step.Name);
                
                // Não propagamos - log e continua
                // Alerta deve ser gerado para intervenção manual
            }
        }

        Status = SagaStatus.Compensated;
        await _stateRepo.MarkFailedAsync(DocumentId, "Compensated after failure", ct);

        return new SagaResult
        {
            Success = false,
            FinalStatus = Status,
            StepsCompensated = compensated,
            ErrorMessage = "Transaction compensated"
        };
    }
}
```

---

## 3. Compensation Actions

### 3.1 Compensation Logic

```csharp
namespace Gabi.Sync.StateMachine.Compensations;

/// <summary>
/// Registry de ações de compensação por estado.
/// </summary>
public class CompensationRegistry
{
    private readonly Dictionary<IngestState, Func<string, CancellationToken, Task>> _compensations;
    
    public CompensationRegistry(
        ILogger<CompensationRegistry> logger,
        IPipelineStateRepository stateRepo,
        IDocumentRepository docRepo,
        IElasticClient elasticClient,
        INeo4jClient neo4jClient)
    {
        _compensations = new()
        {
            // FETCH: Nada para compensar (dados ainda em memória)
            [IngestState.Fetched] = async (docId, ct) =>
            {
                logger.LogDebug("Fetch compensation: no-op for {DocumentId}", docId);
                // Libera referências para GC
                await Task.CompletedTask;
            },
            
            // PARSE: Libera documento parseado da memória
            [IngestState.Parsed] = async (docId, ct) =>
            {
                logger.LogDebug("Parse compensation: releasing memory for {DocumentId}", docId);
                // O documento em memória será liberado pelo GC
                // Nada persistente foi criado ainda
                await Task.CompletedTask;
            },
            
            // CHUNK: Remove chunks temporários se houver
            [IngestState.Chunked] = async (docId, ct) =>
            {
                logger.LogInformation("Chunk compensation for {DocumentId}", docId);
                // Chunks ainda em memória - nada no banco
                await Task.CompletedTask;
            },
            
            // EMBED: Marca embeddings como inválidos (se existirem)
            [IngestState.Embedded] = async (docId, ct) =>
            {
                logger.LogInformation("Embed compensation for {DocumentId}", docId);
                // Se embeddings foram salvos parcialmente, marcar como stale
                await stateRepo.UpdateCheckpointAsync(docId, new { embeddings_stale = true }, ct);
            },
            
            // INDEX: REMOÇÃO CRÍTICA de todos os stores
            [IngestState.IndexingPostgres] = async (docId, ct) =>
            {
                logger.LogWarning("Index compensation (Postgres) for {DocumentId}", docId);
                await docRepo.SoftDeleteAsync(docId, ct);
            },
            
            [IngestState.IndexingElasticsearch] = async (docId, ct) =>
            {
                logger.LogWarning("Index compensation (ES) for {DocumentId}", docId);
                await elasticClient.DeleteAsync<Document>(docId, ct);
            },
            
            [IngestState.IndexingGraph] = async (docId, ct) =>
            {
                logger.LogWarning("Index compensation (Graph) for {DocumentId}", docId);
                await neo4jClient.Cypher
                    .Match("(d:Document {id: $docId})")
                    .OptionalMatch("(d)-[r]-()")
                    .Delete("r, d")
                    .WithParam("docId", docId)
                    .ExecuteWithoutResultsAsync();
            }
        };
    }
    
    public async Task CompensateAsync(IngestState state, string documentId, CancellationToken ct)
    {
        if (_compensations.TryGetValue(state, out var action))
        {
            await action(documentId, ct);
        }
    }
}
```

### 3.2 Compensation Order (Critical)

```
Quando uma falha ocorre no INDEX, a compensação deve acontecer
em ORDEM ESPECÍFICA para manter consistência:

Falha detectada no INDEX → Inicia compensação

1. Compensar INDEX (último passo bem-sucedido)
   ├── Remover do Neo4j (se aplicável)
   ├── Remover do Elasticsearch
   └── Soft delete no PostgreSQL

2. Compensar EMBED
   └── Marcar embeddings como stale (serão regenerados)

3. Compensar CHUNK
   └── Liberar chunks da memória

4. Compensar PARSE
   └── Liberar documento parseado da memória

5. Compensar FETCH
   └── No-op (dados já foram liberados)

Resultado: Estado volta para FetchQueued, documento pode ser reprocessado
```

---

## 4. Checkpointing & Resume

### 4.1 Checkpoint Strategy

```csharp
namespace Gabi.Contracts.StateMachine;

/// <summary>
/// Serviço de checkpoint para resume de operações longas.
/// </summary>
public interface ICheckpointService
{
    /// <summary>Salva checkpoint para documento.</summary>
    Task SaveCheckpointAsync(
        string documentId, 
        CheckpointData checkpoint, 
        CancellationToken ct = default);
    
    /// <summary>Recupera checkpoint mais recente.</summary>
    Task<CheckpointData?> GetCheckpointAsync(
        string documentId, 
        CancellationToken ct = default);
    
    /// <summary>Limpa checkpoint após conclusão.</summary>
    Task ClearCheckpointAsync(
        string documentId, 
        CancellationToken ct = default);
}

/// <summary>
/// Dados de checkpoint para resume.
/// </summary>
public record CheckpointData
{
    /// <summary>Versão do schema de checkpoint.</summary>
    public int Version { get; init; } = 1;
    
    /// <summary>Estado atual quando checkpoint foi salvo.</summary>
    public IngestState State { get; init; }
    
    /// <summary>Offset em stream (bytes lidos).</summary>
    public long? StreamOffset { get; init; }
    
    /// <summary>Índice de linha/record (para CSV).</summary>
    public int? RecordIndex { get; init; }
    
    /// <summary>Índice de batch (para embeddings).</summary>
    public int? BatchIndex { get; init; }
    
    /// <summary>IDs de chunks já processados.</summary>
    public List<int>? CompletedChunkIds { get; init; }
    
    /// <summary>Tempo decorrido no estado atual.</summary>
    public TimeSpan ElapsedInState { get; init; }
    
    /// <summary>Tentativas no estado atual.</summary>
    public int AttemptsInState { get; init; }
    
    /// <summary>Metadados adicionais específicos do estado.</summary>
    public Dictionary<string, object>? Metadata { get; init; }
    
    /// <summary>Timestamp do checkpoint.</summary>
    public DateTime SavedAt { get; init; }
}
```

### 4.2 Per-State Checkpointing

```csharp
namespace Gabi.Sync.StateMachine.Checkpointing;

/// <summary>
/// Checkpointing específico por estado do pipeline.
/// </summary>
public class StateCheckpointStrategies
{
    /// <summary>
    /// CHECKPOINT para FETCH:
    /// - Stream offset (bytes baixados)
    /// - ETag/Last-Modified (para resume de download parcial se servidor suportar)
    /// </summary>
    public static CheckpointData CreateFetchCheckpoint(
        long bytesDownloaded,
        string? etag,
        TimeSpan elapsed)
    {
        return new CheckpointData
        {
            State = IngestState.Fetching,
            StreamOffset = bytesDownloaded,
            ElapsedInState = elapsed,
            Metadata = new Dictionary<string, object>
            {
                ["etag"] = etag ?? "",
                ["supports_range"] = !string.IsNullOrEmpty(etag)
            }
        };
    }

    /// <summary>
    /// CHECKPOINT para PARSE:
    /// - Record index (linha atual do CSV)
    /// - Parser state (para parsers complexos)
    /// </summary>
    public static CheckpointData CreateParseCheckpoint(
        int recordIndex,
        string? partialDocumentId,
        TimeSpan elapsed)
    {
        return new CheckpointData
        {
            State = IngestState.Parsing,
            RecordIndex = recordIndex,
            ElapsedInState = elapsed,
            Metadata = new Dictionary<string, object>
            {
                ["partial_doc_id"] = partialDocumentId ?? ""
            }
        };
    }

    /// <summary>
    /// CHECKPOINT para CHUNK:
    /// - Lista de chunks já gerados
    /// - Offset no texto original
    /// </summary>
    public static CheckpointData CreateChunkCheckpoint(
        List<int> completedChunkIds,
        int charOffset,
        TimeSpan elapsed)
    {
        return new CheckpointData
        {
            State = IngestState.Chunking,
            CompletedChunkIds = completedChunkIds,
            ElapsedInState = elapsed,
            Metadata = new Dictionary<string, object>
            {
                ["char_offset"] = charOffset
            }
        };
    }

    /// <summary>
    /// CHECKPOINT para EMBED:
    /// - Índice de batch atual
    /// - Chunks já embeddados
    /// - Retry count por chunk
    /// </summary>
    public static CheckpointData CreateEmbedCheckpoint(
        int batchIndex,
        List<int> completedChunkIds,
        Dictionary<int, int> retryCounts,
        TimeSpan elapsed)
    {
        return new CheckpointData
        {
            State = IngestState.Embedding,
            BatchIndex = batchIndex,
            CompletedChunkIds = completedChunkIds,
            ElapsedInState = elapsed,
            Metadata = new Dictionary<string, object>
            {
                ["retry_counts"] = retryCounts,
                ["total_batches"] = (completedChunkIds.Count + 31) / 32  // Assume batch 32
            }
        };
    }

    /// <summary>
    /// CHECKPOINT para INDEX:
    /// - Stores já indexados (PG, ES, Graph)
    /// - Documentos pendentes no bulk
    /// </summary>
    public static CheckpointData CreateIndexCheckpoint(
        List<string> completedStores,
        List<string> pendingDocumentIds,
        TimeSpan elapsed)
    {
        return new CheckpointData
        {
            State = IngestState.IndexingPostgres,
            ElapsedInState = elapsed,
            Metadata = new Dictionary<string, object>
            {
                ["completed_stores"] = completedStores,
                ["pending_ids"] = pendingDocumentIds
            }
        };
    }
}
```

### 4.3 Resume Logic

```csharp
namespace Gabi.Sync.StateMachine;

/// <summary>
/// Orquestrador de resume a partir de checkpoints.
/// </summary>
public class PipelineResumeOrchestrator
{
    private readonly ICheckpointService _checkpointService;
    private readonly IPipelineStateRepository _stateRepo;
    private readonly ILogger<PipelineResumeOrchestrator> _logger;
    private readonly IServiceProvider _services;

    public async Task<ResumeResult> TryResumeAsync(
        string documentId, 
        CancellationToken ct = default)
    {
        // 1. Busca checkpoint
        var checkpoint = await _checkpointService.GetCheckpointAsync(documentId, ct);
        if (checkpoint == null)
        {
            return ResumeResult.NoCheckpoint();
        }

        // 2. Valida idade do checkpoint (stale?)
        var checkpointAge = DateTime.UtcNow - checkpoint.SavedAt;
        if (checkpointAge > TimeSpan.FromHours(24))
        {
            _logger.LogWarning(
                "Checkpoint for {DocumentId} is stale ({Age}h), restarting from beginning",
                documentId, checkpointAge.TotalHours);
            
            await _checkpointService.ClearCheckpointAsync(documentId, ct);
            return ResumeResult.Stale();
        }

        // 3. Determina estratégia de resume baseada no estado
        var strategy = GetResumeStrategy(checkpoint.State);
        
        _logger.LogInformation(
            "Resuming {DocumentId} from state {State} at offset {Offset}",
            documentId, checkpoint.State, checkpoint.StreamOffset ?? checkpoint.RecordIndex);

        // 4. Executa resume específico
        var result = await strategy.ResumeAsync(documentId, checkpoint, ct);
        
        return result;
    }

    private IResumeStrategy GetResumeStrategy(IngestState state)
    {
        return state switch
        {
            IngestState.Fetching => new FetchResumeStrategy(_services),
            IngestState.Parsing => new ParseResumeStrategy(_services),
            IngestState.Chunking => new ChunkResumeStrategy(_services),
            IngestState.Embedding => new EmbedResumeStrategy(_services),
            IngestState.IndexingPostgres or 
            IngestState.IndexingElasticsearch or 
            IngestState.IndexingGraph => new IndexResumeStrategy(_services),
            _ => new RestartStrategy(_services)  // Default: restart from beginning
        };
    }
}

/// <summary>
/// Exemplo: Resume strategy para FETCH.
/// </summary>
public class FetchResumeStrategy : IResumeStrategy
{
    private readonly IContentFetcher _fetcher;
    private readonly ILogger<FetchResumeStrategy> _logger;

    public async Task<ResumeResult> ResumeAsync(
        string documentId, 
        CheckpointData checkpoint, 
        CancellationToken ct)
    {
        // Se suporta Range header, resume do offset
        var supportsRange = checkpoint.Metadata?.GetValueOrDefault("supports_range") as bool? ?? false;
        var offset = checkpoint.StreamOffset ?? 0;

        if (supportsRange && offset > 0)
        {
            _logger.LogInformation(
                "Resuming fetch with Range: bytes={Offset}-", offset);
            
            // Configura HTTP Range header
            var options = new FetchOptions
            {
                ResumeFromOffset = offset,
                RangeHeader = $"bytes={offset}-"
            };

            return ResumeResult.Resumed(options);
        }
        else
        {
            // Não suporta resume - restart do zero
            _logger.LogWarning(
                "Server doesn't support Range, restarting fetch from beginning");
            return ResumeResult.Restart();
        }
    }
}

public record ResumeResult
{
    public bool CanResume { get; init; }
    public bool RestartRequired { get; init; }
    public object? ResumeOptions { get; init; }
    public string? Reason { get; init; }

    public static ResumeResult NoCheckpoint() => 
        new() { CanResume = false, RestartRequired = true, Reason = "No checkpoint found" };
    
    public static ResumeResult Stale() => 
        new() { CanResume = false, RestartRequired = true, Reason = "Checkpoint stale" };
    
    public static ResumeResult Resumed(object options) => 
        new() { CanResume = true, ResumeOptions = options };
    
    public static ResumeResult Restart() => 
        new() { CanResume = false, RestartRequired = true };
}
```

---

## 5. Parallel vs Sequential Execution

### 5.1 Execution Strategy Matrix

```
┌─────────────────┬─────────────┬──────────────┬─────────────────────────────────────┐
│ Stage           │ Execution   │ Max Parallel │ Reason                              │
├─────────────────┼─────────────┼──────────────┼─────────────────────────────────────┤
│ Discovery       │ Parallel    │ 4            │ I/O bound, baixa memória            │
│ Fetch           │ Sequential  │ 1            │ Memory streaming (1GB constraint)   │
│ Parse           │ Sequential  │ 1            │ CPU+Memory, streaming required      │
│ Fingerprint     │ Sequential  │ 1            │ CPU rápido, memória variável        │
│ Deduplicate     │ Sequential  │ 1            │ DB lookup, rápido                   │
│ Normalize       │ Sequential  │ 1            │ In-memory transforms                │
│ Chunk           │ Sequential  │ 1            │ Memory: texto + chunks              │
│ Embed           │ Batched     │ 1            │ API calls, rate limited             │
│ Index PG        │ Sequential  │ 1            │ Transactional integrity             │
│ Index ES        │ Sequential  │ 1            │ Após PG commit                      │
│ Index Graph     │ Async       │ 2            │ Pode rodar em paralelo com ES       │
└─────────────────┴─────────────┴──────────────┴─────────────────────────────────────┘
```

### 5.2 Memory-Conscious Orchestrator

```csharp
namespace Gabi.Sync.Pipeline;

/// <summary>
/// Orquestrador que garante execução sequencial por documento
/// e respeita limites de memória.
/// </summary>
public class MemoryConsciousPipeline : IPipelineOrchestrator
{
    private readonly IMemoryManager _memory;
    private readonly IIngestSagaFactory _sagaFactory;
    private readonly ICheckpointService _checkpointService;
    private readonly ILogger<MemoryConsciousPipeline> _logger;
    
    // Configurações para 1GB RAM
    private const long MAX_DOCUMENT_SIZE = 100 * 1024 * 1024;      // 100MB
    private const int EMBED_BATCH_SIZE = 32;                        // chunks
    private const int INDEX_BULK_SIZE = 50;                         // documentos
    private const long MEMORY_HEADROOM = 200 * 1024 * 1024;         // 200MB safety

    public async Task<PipelineResult> ProcessDocumentAsync(
        PipelineContext context,
        CancellationToken ct = default)
    {
        var docId = context.DocumentId;
        _logger.LogInformation("Starting pipeline for {DocumentId}", docId);

        // 1. Verifica se existe checkpoint para resume
        var checkpoint = await _checkpointService.GetCheckpointAsync(docId, ct);
        var startState = checkpoint?.State ?? IngestState.Discovered;

        // 2. Cria saga a partir do estado inicial
        using var saga = _sagaFactory.Create(docId, startState);

        try
        {
            // 3. Executa saga até completar ou falhar
            while (saga.Status == SagaStatus.Pending || saga.Status == SagaStatus.Running)
            {
                // Verifica memória antes de cada passo
                await _memory.WaitForAvailableAsync(MEMORY_HEADROOM, ct);

                // Executa próximo passo
                var stepResult = await saga.ExecuteNextAsync(ct);

                if (!stepResult.Success)
                {
                    return PipelineResult.Failed(stepResult.ErrorMessage);
                }

                // Checkpoint após passos críticos
                if (RequiresCheckpoint(saga.CurrentStepIndex))
                {
                    await SaveCheckpointAsync(docId, saga, ct);
                }
            }

            // 4. Limpa checkpoint em caso de sucesso
            await _checkpointService.ClearCheckpointAsync(docId, ct);

            return PipelineResult.Success();
        }
        catch (InsufficientMemoryException ex)
        {
            _logger.LogError(ex, "Out of memory processing {DocumentId}", docId);
            
            // Salva checkpoint para retry
            await SaveCheckpointAsync(docId, saga, ct);
            
            return PipelineResult.Failed("Out of memory - checkpoint saved");
        }
        catch (OperationCanceledException)
        {
            _logger.LogWarning("Pipeline cancelled for {DocumentId}", docId);
            
            // Salva checkpoint para resume
            await SaveCheckpointAsync(docId, saga, ct);
            
            throw;  // Re-throw para o caller
        }
    }

    private bool RequiresCheckpoint(int stepIndex)
    {
        // Checkpoint após: Fetch(0), Parse(1), Chunk(3), Embed(4)
        return stepIndex is 0 or 1 or 3 or 4;
    }

    private async Task SaveCheckpointAsync(
        string documentId, 
        IIngestSaga saga, 
        CancellationToken ct)
    {
        var checkpoint = CreateCheckpointFromSaga(saga);
        await _checkpointService.SaveCheckpointAsync(documentId, checkpoint, ct);
        
        _logger.LogDebug(
            "Checkpoint saved for {DocumentId} at step {Step}",
            documentId, saga.CurrentStepIndex);
    }
}
```

### 5.3 Resource Budget per Stage

```
Budget de Memória por Estágio (1GB total, ~600MB disponível):

Discovery:    10MB  (URLs, metadados)
Fetch:        50MB  (streaming buffer 64KB, headers)
Parse:        100MB (documento parseado máximo)
Fingerprint:  10MB  (hash calculation)
Deduplicate:  5MB   (query result)
Normalize:    20MB  (transforms em memória)
Chunk:        150MB (texto original + chunks)
Embed:        100MB (batch de 32 chunks + vetores)
Index PG:     50MB  (transaction buffer)
Index ES:     50MB  (bulk buffer)
Index Graph:  30MB  (Cypher batch)
────────────────────────────────────────
PEAK:         ~300MB (com safety margin)
```

---

## 6. Dead Letter Queue (DLQ)

### 6.1 DLQ Entity

```csharp
namespace Gabi.Postgres.StateMachine;

/// <summary>
/// Dead Letter Queue para documentos que falharam permanentemente.
/// </summary>
public class DeadLetterEntry
{
    public Guid Id { get; set; }
    public string DocumentId { get; set; } = string.Empty;
    public string SourceId { get; set; } = string.Empty;
    public string Url { get; set; } = string.Empty;
    
    // Falha
    public IngestState FailedState { get; set; }
    public string ErrorMessage { get; set; } = string.Empty;
    public string ErrorCategory { get; set; } = string.Empty;
    public string StackTrace { get; set; } = string.Empty;
    public int RetryCount { get; set; }
    
    // Contexto
    public string? LastCheckpoint { get; set; }  // JSON
    public DateTime FailedAt { get; set; }
    
    // Resolução
    public DlqStatus Status { get; set; } = DlqStatus.Pending;
    public string? Resolution { get; set; }
    public DateTime? ResolvedAt { get; set; }
    public string? ResolvedBy { get; set; }
}

public enum DlqStatus
{
    Pending,      // Aguardando análise
    Reviewing,    // Em análise
    RetryScheduled,  // Reprocessamento agendado
    Discarded,    // Ignorado permanentemente
    Resolved      // Reprocessado com sucesso
}
```

### 6.2 DLQ Handler

```csharp
namespace Gabi.Sync.StateMachine;

/// <summary>
/// Gerenciador de Dead Letter Queue.
/// </summary>
public class DlqManager
{
    private readonly GabiDbContext _db;
    private readonly ILogger<DlqManager> _logger;
    
    // Limiares para DLQ
    private const int MAX_RETRIES = 3;
    private readonly TimeSpan[] RETRY_DELAYS = {
        TimeSpan.FromMinutes(5),
        TimeSpan.FromMinutes(15),
        TimeSpan.FromHours(1)
    };

    public async Task<RetryDecision> HandleFailureAsync(
        string documentId,
        IngestState failedState,
        Exception exception,
        CancellationToken ct)
    {
        var state = await _db.PipelineStates
            .FirstAsync(s => s.DocumentId == documentId, ct);

        // Categoriza erro
        var category = CategorizeError(exception);
        
        // Verifica se é retryable
        if (!IsRetryable(category) || state.RetryCount >= MAX_RETRIES)
        {
            // Move para DLQ
            await MoveToDlqAsync(documentId, failedState, exception, category, ct);
            
            await _stateRepo.TransitionAsync(documentId, IngestState.DeadLettered, ct);
            
            return RetryDecision.DeadLettered();
        }

        // Agenda retry
        var delay = RETRY_DELAYS[Math.Min(state.RetryCount, RETRY_DELAYS.Length - 1)];
        var nextRetry = DateTime.UtcNow.Add(delay);
        
        state.RetryCount++;
        state.LastRetryAt = DateTime.UtcNow;
        state.NextRetryAt = nextRetry;
        state.LastError = exception.Message;
        state.ErrorCategory = category;
        
        await _db.SaveChangesAsync(ct);
        
        _logger.LogWarning(
            "Document {DocumentId} failed at {State}, retry {Retry}/{Max} scheduled for {NextRetry}",
            documentId, failedState, state.RetryCount, MAX_RETRIES, nextRetry);

        return RetryDecision.Scheduled(nextRetry);
    }

    private string CategorizeError(Exception ex)
    {
        return ex switch
        {
            HttpRequestException => "network",
            TimeoutException => "timeout",
            InsufficientMemoryException => "memory",
            InvalidDataException => "parse",
            _ when ex.Message.Contains("embedding") => "embed",
            _ when ex.Message.Contains("index") => "index",
            _ => "unknown"
        };
    }

    private bool IsRetryable(string category)
    {
        return category switch
        {
            "network" => true,
            "timeout" => true,
            "memory" => true,    // Pode ter mais memória disponível depois
            "embed" => true,     // API pode voltar
            "index" => true,
            "parse" => false,    // Dados corrompidos
            _ => true
        };
    }
}
```

---

## 7. Implementation Roadmap

### Phase 1: Core State Machine
- [ ] `IngestState` enum
- [ ] `PipelineStateEntity` + migration
- [ ] `IIngestSaga` interface
- [ ] `StandardIngestSaga` implementation
- [ ] State transition validation

### Phase 2: Checkpointing
- [ ] `ICheckpointService` + PostgreSQL implementation
- [ ] Per-state checkpoint strategies
- [ ] `PipelineResumeOrchestrator`
- [ ] Resume tests

### Phase 3: Compensation
- [ ] `CompensationRegistry`
- [ ] Per-state compensation actions
- [ ] Saga compensation flow
- [ ] Compensation tests

### Phase 4: DLQ & Observability
- [ ] `DeadLetterEntry` + migration
- [ ] `DlqManager`
- [ ] Retry scheduling
- [ ] DLQ admin API

### Phase 5: Integration
- [ ] Integrate with existing `PipelineOrchestrator`
- [ ] Memory budget enforcement
- [ ] End-to-end tests
- [ ] Performance benchmarks

---

## 8. Appendix: State Transition Table

| From State | To State | Trigger | Validation |
|------------|----------|---------|------------|
| Discovered | FetchQueued | Enqueue | URL válido |
| FetchQueued | Fetching | StartFetch | - |
| FetchQueued | FetchFailed | Timeout | retry < max |
| Fetching | Fetched | Complete | bytes > 0 |
| Fetching | FetchFailed | Error | retry < max |
| FetchFailed | Fetching | Retry | next_retry <= now |
| FetchFailed | DeadLettered | MaxRetries | retry >= max |
| Fetched | Parsing | StartParse | content disponível |
| Parsing | Parsed | Complete | documento válido |
| Parsing | ParseFailed | Error | - |
| ParseFailed | DeadLettered | - | (não retryable) |
| Parsed | Fingerprinting | StartFingerprint | - |
| Fingerprinting | Deduplicating | Complete | hash válido |
| Deduplicating | DuplicateDetected | IsDuplicate | - |
| Deduplicating | Normalizing | NotDuplicate | - |
| Normalizing | Chunking | Complete | - |
| Chunking | Chunked | Complete | chunks.Count > 0 |
| Chunked | Embedding | StartEmbed | - |
| Embedding | Embedded | Complete | embeddings.Count == chunks.Count |
| Embedding | EmbedFailed | Error | retry < max |
| EmbedFailed | Embedding | Retry | next_retry <= now |
| EmbedFailed | DeadLettered | MaxRetries | retry >= max |
| Embedded | IndexingPostgres | StartIndex | - |
| IndexingPostgres | IndexingElasticsearch | PGCommit | transaction ok |
| IndexingPostgres | IndexFailed | Error | rollback PG |
| IndexingElasticsearch | IndexingGraph | ESCommit | - |
| IndexingElasticsearch | Completed | SkipGraph | !graphEnabled |
| IndexingGraph | Completed | Complete | - |
| IndexFailed | Compensating | Trigger | saga compensates |
| Compensating | FetchQueued | Complete | ready for retry |
| Any | Cancelled | AdminAction | - |

---

## 9. Summary

Este design fornece:

1. **State Machine completo** com 22 estados cobrindo todo o pipeline
2. **Sagas** para transações multi-estágio com compensação automática
3. **Checkpointing** para resume de operações interrompidas
4. **DLQ** para falhas permanentes com retry scheduling
5. **Memory-conscious execution** otimizado para 1GB RAM

A arquitetura garante que nenhum documento seja perdido e que falhas parciais sejam recuperáveis sem duplicação de dados.
