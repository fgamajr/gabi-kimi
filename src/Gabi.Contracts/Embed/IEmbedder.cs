using Gabi.Contracts.Chunk;

namespace Gabi.Contracts.Embed;

/// <summary>
/// Interface para geração de embeddings.
/// </summary>
public interface IEmbedder
{
    /// <summary>
    /// Gera embedding para texto único.
    /// </summary>
    Task<IReadOnlyList<float>> EmbedAsync(
        string text,
        CancellationToken ct = default);
    
    /// <summary>
    /// Gera embeddings em batch.
    /// </summary>
    Task<IReadOnlyList<IReadOnlyList<float>>> EmbedBatchAsync(
        IReadOnlyList<string> texts,
        CancellationToken ct = default);
    
    /// <summary>
    /// Embed chunks de um documento.
    /// </summary>
    Task<EmbeddingResult> EmbedChunksAsync(
        IReadOnlyList<Chunk.Chunk> chunks,
        string documentId,
        CancellationToken ct = default);
    
    /// <summary>
    /// Verifica saúde do serviço.
    /// </summary>
    Task<bool> HealthCheckAsync(CancellationToken ct = default);
}
