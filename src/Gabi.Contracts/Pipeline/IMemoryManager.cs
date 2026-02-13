namespace Gabi.Contracts.Pipeline;

// ═════════════════════════════════════════════════════════════════════════════
// ATENÇÃO: AMBIENTE SERVERLESS - SEM DISCO
// Este pipeline opera em memória apenas (1GB RAM no Fly.io).
// NUNCA faz spill para disco. Estratégia:
//   1. Streaming end-to-end (nunca acumular)
//   2. Backpressure (pausar quando sob pressão)
//   3. Descarte controlado se necessário
//   4. Concurrency = 1 (processamento sequencial)
// ═════════════════════════════════════════════════════════════════════════════

/// <summary>
/// Gerenciador de memória para pipeline de processamento serverless.
/// Opera EXCLUSIVAMENTE em memória - sem spill para disco.
/// </summary>
public interface IMemoryManager
{
    /// <summary>
    /// Memória total disponível (bytes).
    /// </summary>
    long TotalMemory { get; }
    
    /// <summary>
    /// Threshold de pressão (geralmente 75-80% da memória).
    /// </summary>
    long PressureThreshold { get; }
    
    /// <summary>
    /// Memória atualmente em uso estimada.
    /// </summary>
    long CurrentUsage { get; }
    
    /// <summary>
    /// Pico de memória registrado.
    /// </summary>
    long PeakUsage { get; }
    
    /// <summary>
    /// Verifica se há pressão de memória.
    /// </summary>
    bool IsUnderPressure { get; }

    /// <summary>
    /// Adquire lease de memória (auto-tracking via IDisposable).
    /// </summary>
    IMemoryLease Acquire(long bytes);
    
    /// <summary>
    /// Aguarda até que haja memória disponível.
    /// Aplica backpressure - PAUSA o pipeline, não descarta.
    /// </summary>
    Task WaitForAvailableAsync(long bytes, CancellationToken ct = default);
    
    /// <summary>
    /// Força coleta de lixo se necessário.
    /// </summary>
    void CollectIfUnderPressure();
}

/// <summary>
/// Lease de memória - libera automaticamente ao dispose.
/// </summary>
public interface IMemoryLease : IDisposable
{
    long Bytes { get; }
}

/// <summary>
/// Budget de memória para um stage específico do pipeline.
/// SEM SPILL PARA DISCO - opera puramente em memória.
/// </summary>
public record MemoryBudget
{
    /// <summary>
    /// Memória máxima permitida por batch (bytes).
    /// Quando atingido, aplica backpressure (pausa).
    /// </summary>
    public long MaxBatchMemory { get; init; } = 50 * 1024 * 1024; // 50MB default
    
    /// <summary>
    /// Número máximo de itens no buffer.
    /// Quando atingido, aplica backpressure.
    /// </summary>
    public int MaxBufferItems { get; init; } = 100; // items
    
    /// <summary>
    /// Delay de backpressure quando buffer cheio.
    /// </summary>
    public TimeSpan BackpressureDelay { get; init; } = TimeSpan.FromMilliseconds(100);
    
    /// <summary>
    /// Número máximo de retries antes de descartar item.
    /// </summary>
    public int MaxRetries { get; init; } = 3;
}

/// <summary>
/// Stage do pipeline com controle de memória.
/// </summary>
public interface IPipelineStage<TInput, TOutput>
{
    string Name { get; }
    MemoryBudget Budget { get; }
    
    /// <summary>
    /// Processa input e produz output com backpressure.
    /// NUNCA acumula tudo em memória - streaming only.
    /// </summary>
    IAsyncEnumerable<TOutput> ProcessAsync(
        IAsyncEnumerable<TInput> input, 
        IMemoryManager memoryManager,
        CancellationToken ct = default);
}

/// <summary>
/// Orquestrador de pipeline com controle de memória global.
/// </summary>
public interface IPipelineOrchestrator
{
    /// <summary>
    /// Executa o pipeline completo com backpressure.
    /// Concurrency = 1 (sequencial) para manter memória baixa.
    /// </summary>
    Task<PipelineResult> ExecuteAsync<TSource>(
        TSource sourceId,
        IAsyncEnumerable<Document> documents,
        PipelineOptions options,
        CancellationToken ct = default);
    
    /// <summary>
    /// Evento disparado quando há pressão de memória.
    /// </summary>
    event EventHandler<MemoryPressureEventArgs>? MemoryPressure;
    
    /// <summary>
    /// Evento disparado quando item é descartado (último recurso).
    /// </summary>
    event EventHandler<ItemDroppedEventArgs>? ItemDropped;
}

/// <summary>
/// Evento de pressão de memória.
/// </summary>
public class MemoryPressureEventArgs : EventArgs
{
    public long CurrentUsage { get; init; }
    public long Threshold { get; init; }
    public double PressureRatio { get; init; }
    public string? StageName { get; init; }
    public TimeSpan BackpressureApplied { get; init; }
}

/// <summary>
/// Evento de item descartado (quando backpressure falha).
/// </summary>
public class ItemDroppedEventArgs : EventArgs
{
    public string DocumentId { get; init; } = string.Empty;
    public string StageName { get; init; } = string.Empty;
    public string Reason { get; init; } = string.Empty;
}

/// <summary>
/// Opções de execução do pipeline.
/// </summary>
public record PipelineOptions
{
    /// <summary>
    /// Processa documentos em paralelo.
    /// ⚠️ EM 1GB RAM: SEMPRE = 1 (sequencial)
    /// </summary>
    public int MaxParallelism { get; init; } = 1;
    
    /// <summary>
    /// Tamanho do batch para operações bulk.
    /// Mantenha pequeno em memória limitada.
    /// </summary>
    public int BatchSize { get; init; } = 50;
    
    /// <summary>
    /// Delay entre batches quando sob pressão.
    /// </summary>
    public TimeSpan BackpressureDelay { get; init; } = TimeSpan.FromMilliseconds(100);
    
    /// <summary>
    /// Timeout total do pipeline.
    /// </summary>
    public TimeSpan Timeout { get; init; } = TimeSpan.FromHours(2);
    
    /// <summary>
    /// Se true, descarta items quando backpressure falha.
    /// Se false, falha o pipeline inteiro.
    /// </summary>
    public bool AllowDropOnPressure { get; init; } = false;
    
    /// <summary>
    /// Timeout máximo de espera por memória disponível.
    /// </summary>
    public TimeSpan MemoryWaitTimeout { get; init; } = TimeSpan.FromMinutes(2);
}

/// <summary>
/// Documento em processamento no pipeline.
/// </summary>
public record Document
{
    public string Id { get; init; } = Guid.NewGuid().ToString();
    public string SourceId { get; init; } = string.Empty;
    
    /// <summary>
    /// Conteúdo textual (já parseado).
    /// ⚠️ Para streaming de bytes, usar Stream diretamente no stage.
    /// </summary>
    public string? TextContent { get; init; }
    
    /// <summary>
    /// Chunks do documento.
    /// </summary>
    public IReadOnlyList<Chunk> Chunks { get; init; } = new List<Chunk>();
    
    /// <summary>
    /// Metadados do documento.
    /// </summary>
    public Dictionary<string, object> Metadata { get; init; } = new();
    
    public DateTime ReceivedAt { get; init; } = DateTime.UtcNow;
    
    /// <summary>
    /// Estimativa de memória usada por este documento.
    /// </summary>
    public long EstimatedMemory => 
        (TextContent?.Length * 2 ?? 0) + // UTF-16
        (Chunks.Count * 1024) + // overhead per chunk
        2048; // base overhead
}

/// <summary>
/// Chunk de documento para embedding.
/// </summary>
public record Chunk
{
    public int Index { get; init; }
    public string Text { get; init; } = string.Empty;
    public float[]? Embedding { get; init; }
    public int TokenCount { get; init; }
    
    /// <summary>
    /// Memória estimada do embedding (384 dims * 4 bytes = ~1.5KB).
    /// </summary>
    public long EmbeddingMemory => Embedding?.Length * sizeof(float) ?? 0;
}
