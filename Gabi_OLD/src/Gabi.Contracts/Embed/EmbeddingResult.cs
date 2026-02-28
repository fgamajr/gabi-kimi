namespace Gabi.Contracts.Embed;

/// <summary>
/// Um chunk com embedding vetorial.
/// </summary>
public record EmbeddedChunk
{
    /// <summary>Texto do chunk.</summary>
    public string Text { get; init; } = string.Empty;
    
    /// <summary>Índice do chunk.</summary>
    public int Index { get; init; }
    
    /// <summary>Número de tokens.</summary>
    public int TokenCount { get; init; }
    
    /// <summary>Número de caracteres.</summary>
    public int CharCount { get; init; }
    
    /// <summary>Tipo/seção.</summary>
    public string SectionType { get; init; } = "content";
    
    /// <summary>Vetor de embedding.</summary>
    public IReadOnlyList<float> Embedding { get; init; } = Array.Empty<float>();
    
    /// <summary>Modelo usado.</summary>
    public string Model { get; init; } = string.Empty;
    
    /// <summary>Dimensões do vetor.</summary>
    public int Dimensions { get; init; }
    
    /// <summary>Data/hora do embedding.</summary>
    public DateTime EmbeddedAt { get; init; } = DateTime.UtcNow;
    
    /// <summary>Metadata adicional.</summary>
    public IReadOnlyDictionary<string, object>? Metadata { get; init; }
}

/// <summary>
/// Resultado do embedding de um documento.
/// </summary>
public record EmbeddingResult
{
    /// <summary>ID do documento.</summary>
    public string DocumentId { get; init; } = string.Empty;
    
    /// <summary>Chunks embeddados.</summary>
    public IReadOnlyList<EmbeddedChunk> Chunks { get; init; } = Array.Empty<EmbeddedChunk>();
    
    /// <summary>Modelo usado.</summary>
    public string Model { get; init; } = string.Empty;
    
    /// <summary>Total de embeddings.</summary>
    public int TotalEmbeddings { get; init; }
    
    /// <summary>Tokens processados.</summary>
    public int TokensProcessed { get; init; }
    
    /// <summary>Duração em segundos.</summary>
    public double DurationSeconds { get; init; }
}

/// <summary>
/// Configuração de embedding.
/// </summary>
public record EmbeddingConfig
{
    /// <summary>URL do serviço TEI.</summary>
    public string TeiUrl { get; init; } = "http://localhost:8080";
    
    /// <summary>Modelo de embedding.</summary>
    public string Model { get; init; } = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2";
    
    /// <summary>Tamanho do batch.</summary>
    public int BatchSize { get; init; } = 32;
    
    /// <summary>Timeout.</summary>
    public string Timeout { get; init; } = "30s";
    
    /// <summary>Dimensões do vetor.</summary>
    public int Dimensions { get; init; } = 384;
}
