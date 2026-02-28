using System.Diagnostics;
using Gabi.Contracts.Index;

namespace Gabi.Ingest;

/// <summary>
/// Minimal in-process indexer used while external index providers are optional.
/// </summary>
public sealed class LocalDocumentIndexer : IDocumentIndexer
{
    public Task<IndexingResult> IndexAsync(IndexDocument document, IReadOnlyList<IndexChunk> chunks, CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();

        var stopwatch = Stopwatch.StartNew();
        if (string.IsNullOrWhiteSpace(document.DocumentId))
        {
            return Task.FromResult(new IndexingResult
            {
                DocumentId = string.Empty,
                Status = IndexingStatus.Failed,
                ChunksIndexed = 0,
                PgSuccess = false,
                EsSuccess = false,
                Errors = new[] { "document_id is required" },
                DurationMs = stopwatch.Elapsed.TotalMilliseconds
            });
        }

        return Task.FromResult(new IndexingResult
        {
            DocumentId = document.DocumentId,
            Status = IndexingStatus.Success,
            ChunksIndexed = chunks.Count,
            PgSuccess = true,
            EsSuccess = true,
            DurationMs = stopwatch.Elapsed.TotalMilliseconds
        });
    }

    public Task<bool> DeleteAsync(string documentId, CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();
        return Task.FromResult(!string.IsNullOrWhiteSpace(documentId));
    }

    public Task<bool> HealthCheckAsync(CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();
        return Task.FromResult(true);
    }
}
