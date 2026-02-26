using System.Diagnostics;
using Elastic.Clients.Elasticsearch;
using Gabi.Contracts.Index;
using Microsoft.Extensions.Logging;

namespace Gabi.Ingest;

/// <summary>
/// Indexador que persiste documentos e chunks no Elasticsearch.
/// Usa índice único com campo source_id para GetActiveDocumentCountAsync (CODEX-D).
/// </summary>
public sealed class ElasticsearchDocumentIndexer : IDocumentIndexer
{
    private const string DefaultIndexName = "gabi-docs";
    private readonly ElasticsearchClient _client;
    private readonly string _indexName;
    private readonly ILogger<ElasticsearchDocumentIndexer> _logger;

    public ElasticsearchDocumentIndexer(
        ElasticsearchClient client,
        ILogger<ElasticsearchDocumentIndexer> logger,
        string? indexName = null)
    {
        _client = client;
        _logger = logger;
        _indexName = string.IsNullOrWhiteSpace(indexName) ? DefaultIndexName : indexName.Trim();
    }

    public async Task<IndexingResult> IndexAsync(
        IndexDocument document,
        IReadOnlyList<IndexChunk> chunks,
        CancellationToken ct = default)
    {
        var stopwatch = Stopwatch.StartNew();
        ct.ThrowIfCancellationRequested();

        if (string.IsNullOrWhiteSpace(document.DocumentId))
        {
            return new IndexingResult
            {
                DocumentId = string.Empty,
                Status = IndexingStatus.Failed,
                ChunksIndexed = 0,
                PgSuccess = false,
                EsSuccess = false,
                Errors = new[] { "document_id is required" },
                DurationMs = stopwatch.Elapsed.TotalMilliseconds
            };
        }

        try
        {
            var esChunks = chunks.Select(c => new EsChunk
            {
                ChunkId = c.ChunkId,
                ChunkIndex = c.ChunkIndex,
                Text = c.Text,
                Embedding = c.Embedding?.ToArray(),
                Metadata = c.Metadata
            }).ToList();

            // Embedding top-level para kNN/busca híbrida: primeiro chunk com embedding ou média dos chunks
            float[]? docEmbedding = null;
            if (chunks.Count > 0)
            {
                var withEmbedding = chunks.Where(c => c.Embedding is { Count: > 0 }).ToList();
                if (withEmbedding.Count > 0)
                {
                    var dims = withEmbedding[0].Embedding!.Count;
                    if (withEmbedding.Count == 1)
                        docEmbedding = withEmbedding[0].Embedding!.ToArray();
                    else
                    {
                        docEmbedding = new float[dims];
                        foreach (var c in withEmbedding)
                        {
                            for (var i = 0; i < dims && i < c.Embedding!.Count; i++)
                                docEmbedding[i] += c.Embedding![i];
                        }
                        for (var i = 0; i < dims; i++)
                            docEmbedding[i] /= withEmbedding.Count;
                    }
                }
            }

            var doc = new EsDocument
            {
                DocumentId = document.DocumentId,
                SourceId = document.SourceId,
                Title = document.Title,
                ContentPreview = document.ContentPreview,
                Fingerprint = document.Fingerprint,
                Status = document.Status,
                IngestedAt = document.IngestedAt,
                Embedding = docEmbedding,
                Chunks = esChunks,
                Metadata = document.Metadata
            };

            var response = await _client.IndexAsync(doc, idx => idx
                .Index(_indexName)
                .Id(document.DocumentId),
                ct);

            if (!response.IsValidResponse)
            {
                var errors = response.ElasticsearchServerError?.Error?.Reason ?? response.DebugInformation ?? "Unknown";
                _logger.LogWarning("ES index failed for {DocumentId}: {Error}", document.DocumentId, errors);
                return new IndexingResult
                {
                    DocumentId = document.DocumentId,
                    Status = IndexingStatus.Failed,
                    ChunksIndexed = 0,
                    PgSuccess = false,
                    EsSuccess = false,
                    Errors = new[] { errors },
                    DurationMs = stopwatch.Elapsed.TotalMilliseconds
                };
            }

            return new IndexingResult
            {
                DocumentId = document.DocumentId,
                Status = IndexingStatus.Success,
                ChunksIndexed = chunks.Count,
                PgSuccess = true,
                EsSuccess = true,
                DurationMs = stopwatch.Elapsed.TotalMilliseconds
            };
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "ES index exception for {DocumentId}", document.DocumentId);
            return new IndexingResult
            {
                DocumentId = document.DocumentId,
                Status = IndexingStatus.Failed,
                ChunksIndexed = 0,
                PgSuccess = false,
                EsSuccess = false,
                Errors = new[] { ex.Message },
                DurationMs = stopwatch.Elapsed.TotalMilliseconds
            };
        }
    }

    public async Task<bool> DeleteAsync(string documentId, CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();
        if (string.IsNullOrWhiteSpace(documentId))
            return false;

        var response = await _client.DeleteAsync(_indexName, documentId, ct);
        return response.IsValidResponse;
    }

    public async Task<bool> HealthCheckAsync(CancellationToken ct = default)
    {
        try
        {
            var response = await _client.PingAsync(ct);
            return response.IsValidResponse;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "ES health check failed");
            return false;
        }
    }

    public async Task<int?> GetActiveDocumentCountAsync(string sourceId, CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();
        try
        {
            var response = await _client.CountAsync(c => c
                .Index(_indexName)
                .Query(q => q
                    .Term(t => t.Field("sourceId").Value(sourceId))),
                ct);

            if (response.IsValidResponse)
                return (int)response.Count;
            return null;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "ES count failed for source {SourceId}", sourceId);
            return null;
        }
    }

    private sealed class EsDocument
    {
        public string DocumentId { get; init; } = string.Empty;
        public string SourceId { get; init; } = string.Empty;
        public string Title { get; init; } = string.Empty;
        public string ContentPreview { get; init; } = string.Empty;
        public string Fingerprint { get; init; } = string.Empty;
        public string Status { get; init; } = "active";
        public DateTime IngestedAt { get; init; }
        /// <summary>Vetor único por documento para kNN/busca híbrida (primeiro chunk ou média dos chunks).</summary>
        public float[]? Embedding { get; init; }
        public IReadOnlyList<EsChunk> Chunks { get; init; } = Array.Empty<EsChunk>();
        /// <summary>Metadados extraídos (normative_force, datas, categorias) para filtros facetados.</summary>
        public IReadOnlyDictionary<string, object>? Metadata { get; init; }
    }

    private sealed class EsChunk
    {
        public string ChunkId { get; init; } = string.Empty;
        public int ChunkIndex { get; init; }
        public string Text { get; init; } = string.Empty;
        public float[]? Embedding { get; init; }
        public IReadOnlyDictionary<string, object>? Metadata { get; init; }
    }
}
