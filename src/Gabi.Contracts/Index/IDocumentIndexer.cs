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

    /// <summary>
    /// Returns active document count for the source in the index (for reconciliation). When not supported, returns null.
    /// </summary>
    Task<int?> GetActiveDocumentCountAsync(string sourceId, CancellationToken ct = default) => Task.FromResult<int?>(null);

    /// <summary>
    /// Bulk-indexes multiple documents in a single operation. Default implementation falls back to sequential IndexAsync calls.
    /// Implementations should override with a real bulk API for efficiency (GAP-05).
    /// </summary>
    async Task<IReadOnlyList<IndexingResult>> BulkIndexAsync(
        IReadOnlyList<(IndexDocument Document, IReadOnlyList<IndexChunk> Chunks)> batch,
        CancellationToken ct = default)
    {
        var results = new List<IndexingResult>(batch.Count);
        foreach (var (document, chunks) in batch)
            results.Add(await IndexAsync(document, chunks, ct));
        return results;
    }
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
