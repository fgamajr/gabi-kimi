namespace Gabi.Contracts.Embed;

public interface IDocumentEmbeddingRepository
{
    Task<int> UpsertChunkEmbeddingsAsync(Guid documentId, string sourceId,
        IReadOnlyList<ChunkEmbedding> chunks, CancellationToken ct = default);
    Task<bool> HasEmbeddingsAsync(Guid documentId, CancellationToken ct = default);
    Task<IReadOnlyList<VectorSearchResult>> SearchSimilarAsync(
        float[] queryVector, int topK, string? sourceId, CancellationToken ct = default);
}

public record ChunkEmbedding(int ChunkIndex, string ChunkText, float[] Embedding, string ModelName);

public record VectorSearchResult(Guid DocumentId, int ChunkIndex, string ChunkText, float Distance);
