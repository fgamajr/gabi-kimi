namespace Gabi.Contracts.Index;

/// <summary>
/// Status da indexação.
/// </summary>
public enum IndexingStatus
{
    /// <summary>Sucesso.</summary>
    Success,
    
    /// <summary>Parcial (alguns chunks falharam).</summary>
    Partial,
    
    /// <summary>Falha total.</summary>
    Failed,
    
    /// <summary>Ignorado (duplicata).</summary>
    Ignored,
    
    /// <summary>Rollback executado.</summary>
    RolledBack,

    /// <summary>ES rejected the write because stored version is newer (stale write from WAL projection).</summary>
    VersionConflict
}

/// <summary>
/// Chunk indexado.
/// </summary>
public record IndexChunk
{
    /// <summary>ID do chunk.</summary>
    public string ChunkId { get; init; } = string.Empty;
    
    /// <summary>Índice.</summary>
    public int ChunkIndex { get; init; }
    
    /// <summary>Texto.</summary>
    public string Text { get; init; } = string.Empty;
    
    /// <summary>Embedding.</summary>
    public IReadOnlyList<float>? Embedding { get; init; }
    
    /// <summary>Metadata.</summary>
    public IReadOnlyDictionary<string, object>? Metadata { get; init; }
}

/// <summary>
/// Documento para indexação.
/// </summary>
public record IndexDocument
{
    /// <summary>ID do documento.</summary>
    public string DocumentId { get; init; } = string.Empty;
    
    /// <summary>ID da fonte.</summary>
    public string SourceId { get; init; } = string.Empty;
    
    /// <summary>Título.</summary>
    public string Title { get; init; } = string.Empty;
    
    /// <summary>Preview do conteúdo.</summary>
    public string ContentPreview { get; init; } = string.Empty;
    
    /// <summary>Fingerprint.</summary>
    public string Fingerprint { get; init; } = string.Empty;
    
    /// <summary>Metadata.</summary>
    public IReadOnlyDictionary<string, object> Metadata { get; init; } = 
        new Dictionary<string, object>();
    
    /// <summary>Status.</summary>
    public string Status { get; init; } = "active";
    
    /// <summary>Quantidade de chunks.</summary>
    public int ChunksCount { get; init; }
    
    /// <summary>Data de ingestão.</summary>
    public DateTime IngestedAt { get; init; }

    /// <summary>Application-managed timestamp used as ES external version (UpdatedAt.Ticks).</summary>
    public DateTime UpdatedAt { get; init; }

    /// <summary>
    /// When non-null, ES write uses version_type=external with this value.
    /// Only set by WAL projection path; null means normal (non-versioned) ES write.
    /// </summary>
    public long? ExternalVersion { get; init; }
}

/// <summary>
/// Resultado da indexação.
/// </summary>
public record IndexingResult
{
    /// <summary>ID do documento.</summary>
    public string DocumentId { get; init; } = string.Empty;
    
    /// <summary>Status.</summary>
    public IndexingStatus Status { get; init; }
    
    /// <summary>Chunks indexados.</summary>
    public int ChunksIndexed { get; init; }
    
    /// <summary>Sucesso no PostgreSQL.</summary>
    public bool PgSuccess { get; init; }
    
    /// <summary>Sucesso no Elasticsearch.</summary>
    public bool EsSuccess { get; init; }
    
    /// <summary>Erros.</summary>
    public IReadOnlyList<string> Errors { get; init; } = Array.Empty<string>();
    
    /// <summary>Duração em ms.</summary>
    public double DurationMs { get; init; }
}
