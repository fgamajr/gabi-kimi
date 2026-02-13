namespace Gabi.Contracts.Index;

/// <summary>
/// Interface para indexação de documentos.
/// </summary>
public interface IDocumentIndexer
{
    /// <summary>
    /// Indexa um documento com seus chunks.
    /// </summary>
    Task<IndexingResult> IndexAsync(
        IndexDocument document,
        IReadOnlyList<IndexChunk> chunks,
        CancellationToken ct = default);
    
    /// <summary>
    /// Remove documento do índice.
    /// </summary>
    Task<bool> DeleteAsync(
        string documentId,
        CancellationToken ct = default);
    
    /// <summary>
    /// Verifica saúde do serviço de indexação.
    /// </summary>
    Task<bool> HealthCheckAsync(CancellationToken ct = default);
}

/// <summary>
/// Interface para indexação em PostgreSQL.
/// </summary>
public interface IPgIndexer : IDocumentIndexer
{
}

/// <summary>
/// Interface para indexação em Elasticsearch.
/// </summary>
public interface IElasticIndexer : IDocumentIndexer
{
}
