namespace Gabi.Contracts.Pipeline;

// ═════════════════════════════════════════════════════════════════════════════
// ATENÇÃO: STAGES OPERAM EM MEMÓRIA APENAS
// Nenhum stage faz spill para disco. Estratégias:
//   - Fetch: Stream HTTP → processa chunk → descarta
//   - Parse: Stream parser (linha a linha)
//   - Chunk: Processa e libera imediatamente
//   - Embed: Batches pequenos (~50 chunks)
//   - Index: Bulk inserts frequentes (flush a cada N)
// ═════════════════════════════════════════════════════════════════════════════

/// <summary>
/// Stage de fetch com streaming e backpressure.
/// NUNCA carrega arquivo inteiro na memória.
/// </summary>
public interface IFetchStage : IPipelineStage<Uri, Document>
{
    /// <summary>
    /// Tamanho máximo do download (safety guard).
    /// Arquivos maiores são rejeitados.
    /// </summary>
    long MaxDownloadSize { get; init; }
    
    /// <summary>
    /// Tamanho do chunk para streaming.
    /// </summary>
    int StreamChunkSize { get; init; } // 64KB padrão
}

/// <summary>
/// Stage de parsing (CSV, PDF, etc).
/// Parser streaming - nunca carrega documento inteiro.
/// </summary>
public interface IParseStage : IPipelineStage<Document, Document>
{
    /// <summary>
    /// Parser em modo streaming (linha/record por vez).
    /// </summary>
    bool UseStreamingParser { get; init; }
    
    /// <summary>
    /// Tamanho máximo do documento em memória.
    /// </summary>
    long MaxDocumentSize { get; init; }
}

/// <summary>
/// Stage de chunking (dividir documentos).
/// Processa e libera chunks imediatamente.
/// </summary>
public interface IChunkStage : IPipelineStage<Document, Document>
{
    /// <summary>
    /// Máximo de tokens por chunk.
    /// </summary>
    int MaxTokensPerChunk { get; init; }
    
    /// <summary>
    /// Overlap entre chunks.
    /// </summary>
    int OverlapTokens { get; init; }
    
    /// <summary>
    /// Libera texto original após chunking (economia de memória).
    /// </summary>
    bool DiscardSourceText { get; init; }
}

/// <summary>
/// Stage de embedding (chamada ao TEI ou API).
/// Batches pequenos para caber em memória.
/// </summary>
public interface IEmbedStage : IPipelineStage<Document, Document>
{
    /// <summary>
    /// Tamanho do batch para API de embeddings.
    /// ⚠️ Manter pequeno: 32-64 chunks por batch.
    /// </summary>
    int BatchSize { get; init; }
    
    /// <summary>
    /// Delay entre batches (rate limiting + GC time).
    /// </summary>
    TimeSpan RateLimitDelay { get; init; }
    
    /// <summary>
    /// Libera chunks após embedding (economia de memória).
    /// </summary>
    bool DiscardChunksAfterEmbedding { get; init; }
}

/// <summary>
/// Stage de indexação (Elasticsearch).
/// Flush frequente para não acumular.
/// </summary>
public interface IIndexStage : IPipelineStage<Document, Document>
{
    /// <summary>
    /// Tamanho do bulk index (documentos).
    /// </summary>
    int BulkSize { get; init; }
    
    /// <summary>
    /// Flush a cada N documentos (não esperar acumular).
    /// </summary>
    int FlushInterval { get; init; }
    
    /// <summary>
    /// Libera documentos após indexação.
    /// </summary>
    bool DiscardAfterIndex { get; init; }
}

/// <summary>
/// Stage de GraphDB (Neo4j).
/// </summary>
public interface IGraphStage : IPipelineStage<Document, Document>
{
    /// <summary>
    /// Batch size para Cypher queries.
    /// </summary>
    int BatchSize { get; init; }
}

/// <summary>
/// Métricas de execução do pipeline (mutable para tracking).
/// </summary>
public class PipelineMetrics
{
    public string SourceId { get; set; } = string.Empty;
    public DateTime StartedAt { get; set; }
    public DateTime? CompletedAt { get; set; }
    
    public long DocumentsProcessed { get; set; }
    public long DocumentsFailed { get; set; }
    public long DocumentsDropped { get; set; }
    public long BytesDownloaded { get; set; }
    public long ChunksCreated { get; set; }
    public long EmbeddingsGenerated { get; set; }
    
    public TimeSpan FetchDuration { get; set; }
    public TimeSpan ParseDuration { get; set; }
    public TimeSpan ChunkDuration { get; set; }
    public TimeSpan EmbedDuration { get; set; }
    public TimeSpan IndexDuration { get; set; }
    public TimeSpan GraphDuration { get; set; }
    
    public long PeakMemoryBytes { get; set; }
    public int BackpressureEvents { get; set; }
    public TimeSpan TotalBackpressureTime { get; set; }
    
    public TimeSpan TotalDuration => CompletedAt.HasValue 
        ? CompletedAt.Value - StartedAt 
        : DateTime.UtcNow - StartedAt;
}

/// <summary>
/// Resultado da execução do pipeline.
/// </summary>
public record PipelineResult
{
    public bool Success { get; init; }
    public string? ErrorMessage { get; init; }
    public PipelineMetrics Metrics { get; init; } = new();
}
