namespace Gabi.Contracts.Chunk;

/// <summary>
/// Interface para chunking de documentos.
/// </summary>
public interface IChunker
{
    /// <summary>
    /// Divide texto em chunks.
    /// </summary>
    ChunkResult Chunk(
        string text,
        ChunkConfig config,
        IReadOnlyDictionary<string, object>? metadata = null);
}

/// <summary>
/// Configuração de chunking.
/// </summary>
public record ChunkConfig
{
    /// <summary>Estratégia: semantic, fixed, article.</summary>
    public string Strategy { get; init; } = "semantic";
    
    /// <summary>Tamanho máximo de chunk (tokens).</summary>
    public int MaxChunkSize { get; init; } = 512;
    
    /// <summary>Overlap entre chunks (tokens).</summary>
    public int Overlap { get; init; } = 0;
    
    /// <summary>Separadores para estratégia semantic.</summary>
    public IReadOnlyList<string> Separators { get; init; } = 
        new[] { "\n\n", "\n", ". ", " " };
}

/// <summary>
/// Resultado de chunking.
/// </summary>
public record ChunkResult
{
    /// <summary>Chunks gerados.</summary>
    public IReadOnlyList<Chunk> Chunks { get; init; } = new List<Chunk>();
    
    /// <summary>Total de tokens.</summary>
    public int TotalTokens { get; init; }
    
    /// <summary>Total de caracteres.</summary>
    public int TotalChars { get; init; }
    
    /// <summary>Duração em ms.</summary>
    public double DurationMs { get; init; }
}
