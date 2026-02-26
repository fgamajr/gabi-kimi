using System.Diagnostics;
using Elastic.Clients.Elasticsearch;
using Gabi.Contracts.Index;
using Microsoft.Extensions.Logging;

namespace Gabi.Ingest;

/// <summary>
/// Indexador que persiste documentos e chunks no Elasticsearch.
/// Usa índice único com campo source_id para GetActiveDocumentCountAsync (CODEX-D).
/// Circuit breaker: 5 consecutive failures → open 30s (GAP-04).
/// BulkIndexAsync uses _bulk API to reduce HTTP round-trips (GAP-05).
/// </summary>
public sealed class ElasticsearchDocumentIndexer : IDocumentIndexer
{
    private const string DefaultIndexName = "gabi-docs";
    private const int CircuitBreakerFailureThreshold = 5;
    private static readonly TimeSpan CircuitBreakerOpenDuration = TimeSpan.FromSeconds(30);

    private readonly ElasticsearchClient _client;
    private readonly string _indexName;
    private readonly ILogger<ElasticsearchDocumentIndexer> _logger;

    private int _consecutiveFailures;
    private DateTime _circuitOpenedAt = DateTime.MinValue;
    private readonly object _circuitLock = new();

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

        if (!TryEnterCircuit(document.DocumentId, stopwatch, out var circuitError))
            return circuitError!;

        try
        {
            var doc = BuildEsDocument(document, chunks);

            var response = await _client.IndexAsync(doc, idx => idx
                .Index(_indexName)
                .Id(document.DocumentId),
                ct);

            if (!response.IsValidResponse)
            {
                var errors = response.ElasticsearchServerError?.Error?.Reason ?? response.DebugInformation ?? "Unknown";
                _logger.LogWarning("ES index failed for {DocumentId}: {Error}", document.DocumentId, errors);
                RecordFailure();
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

            RecordSuccess();
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
            RecordFailure();
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

    public async Task<IReadOnlyList<IndexingResult>> BulkIndexAsync(
        IReadOnlyList<(IndexDocument Document, IReadOnlyList<IndexChunk> Chunks)> batch,
        CancellationToken ct = default)
    {
        if (batch.Count == 0)
            return Array.Empty<IndexingResult>();

        if (batch.Count == 1)
            return new[] { await IndexAsync(batch[0].Document, batch[0].Chunks, ct) };

        var stopwatch = Stopwatch.StartNew();
        ct.ThrowIfCancellationRequested();

        if (!TryEnterCircuit(null, stopwatch, out _))
        {
            // Circuit open — return failure results for all docs in batch
            return batch.Select(b => new IndexingResult
            {
                DocumentId = b.Document.DocumentId,
                Status = IndexingStatus.Failed,
                ChunksIndexed = 0,
                PgSuccess = false,
                EsSuccess = false,
                Errors = new[] { "ES circuit breaker open" },
                DurationMs = stopwatch.Elapsed.TotalMilliseconds
            }).ToList();
        }

        try
        {
            // Build a list of (document_id, esDoc) for the bulk call; skip blank IDs
            var validItems = batch
                .Where(b => !string.IsNullOrWhiteSpace(b.Document.DocumentId))
                .Select(b => (b.Document.DocumentId, b.Document, b.Chunks, EsDoc: BuildEsDocument(b.Document, b.Chunks)))
                .ToList();

            if (validItems.Count == 0)
                return Array.Empty<IndexingResult>();

            // Use the BulkRequestDescriptor fluent API (Elastic.Clients.Elasticsearch 8.x)
            var response = await _client.BulkAsync(b =>
            {
                b.Index(_indexName);
                foreach (var item in validItems)
                    b.Index<EsDocument>(item.EsDoc, op => op.Id(item.DocumentId));
            }, ct);

            var elapsed = stopwatch.Elapsed.TotalMilliseconds;
            if (!response.IsValidResponse)
            {
                var error = response.ElasticsearchServerError?.Error?.Reason ?? response.DebugInformation ?? "Bulk failed";
                _logger.LogWarning("ES bulk index failed: {Error}", error);
                RecordFailure();
                return batch.Select(b => new IndexingResult
                {
                    DocumentId = b.Document.DocumentId,
                    Status = IndexingStatus.Failed,
                    ChunksIndexed = 0,
                    PgSuccess = false,
                    EsSuccess = false,
                    Errors = new[] { error },
                    DurationMs = elapsed
                }).ToList();
            }

            RecordSuccess();

            // Map bulk response items back to per-document results (indexed in same order as validItems)
            var results = new List<IndexingResult>(batch.Count);
            var responseItems = response.Items;
            var responseCount = responseItems.Count;

            // First emit results for valid items, matched by position
            for (var i = 0; i < validItems.Count; i++)
            {
                var (docId, _, chunks, _) = validItems[i];
                var item = i < responseCount ? responseItems[i] : null;
                var ok = item?.IsValid ?? false;
                results.Add(new IndexingResult
                {
                    DocumentId = docId,
                    Status = ok ? IndexingStatus.Success : IndexingStatus.Failed,
                    ChunksIndexed = ok ? chunks.Count : 0,
                    PgSuccess = ok,
                    EsSuccess = ok,
                    Errors = ok ? Array.Empty<string>() : new[] { item?.Error?.Reason ?? "Unknown bulk item error" },
                    DurationMs = elapsed
                });
            }

            // Emit failure results for any blank-ID docs that were skipped
            foreach (var (document, _) in batch.Where(b => string.IsNullOrWhiteSpace(b.Document.DocumentId)))
            {
                results.Add(new IndexingResult
                {
                    DocumentId = string.Empty,
                    Status = IndexingStatus.Failed,
                    ChunksIndexed = 0,
                    PgSuccess = false,
                    EsSuccess = false,
                    Errors = new[] { "document_id is required" },
                    DurationMs = elapsed
                });
            }

            _logger.LogDebug("ES bulk indexed {Count}/{Total} docs in {Ms:F0}ms",
                results.Count(r => r.EsSuccess), batch.Count, elapsed);
            return results;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "ES bulk index exception for {Count} docs", batch.Count);
            RecordFailure();
            var elapsed = stopwatch.Elapsed.TotalMilliseconds;
            return batch.Select(b => new IndexingResult
            {
                DocumentId = b.Document.DocumentId,
                Status = IndexingStatus.Failed,
                ChunksIndexed = 0,
                PgSuccess = false,
                EsSuccess = false,
                Errors = new[] { ex.Message },
                DurationMs = elapsed
            }).ToList();
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

    // ── Circuit breaker helpers ──────────────────────────────────────────────

    private bool TryEnterCircuit(string? documentId, Stopwatch stopwatch, out IndexingResult? failResult)
    {
        lock (_circuitLock)
        {
            if (_consecutiveFailures >= CircuitBreakerFailureThreshold)
            {
                if (DateTime.UtcNow - _circuitOpenedAt < CircuitBreakerOpenDuration)
                {
                    _logger.LogWarning("ES circuit breaker open; rejecting index call for {DocumentId}", documentId ?? "batch");
                    failResult = new IndexingResult
                    {
                        DocumentId = documentId ?? string.Empty,
                        Status = IndexingStatus.Failed,
                        ChunksIndexed = 0,
                        PgSuccess = false,
                        EsSuccess = false,
                        Errors = new[] { "ES circuit breaker open. Too many consecutive failures." },
                        DurationMs = stopwatch.Elapsed.TotalMilliseconds
                    };
                    return false;
                }
                // Half-open: allow one attempt through
                _logger.LogInformation("ES circuit breaker half-open; attempting recovery");
                _consecutiveFailures = 0;
            }
        }
        failResult = null;
        return true;
    }

    private void RecordSuccess()
    {
        lock (_circuitLock)
        {
            if (_consecutiveFailures > 0)
                _logger.LogInformation("ES circuit breaker recovered after {Failures} failures", _consecutiveFailures);
            _consecutiveFailures = 0;
        }
    }

    private void RecordFailure()
    {
        lock (_circuitLock)
        {
            _consecutiveFailures++;
            if (_consecutiveFailures == CircuitBreakerFailureThreshold)
            {
                _circuitOpenedAt = DateTime.UtcNow;
                _logger.LogWarning(
                    "ES circuit breaker opened after {Threshold} consecutive failures. Will retry after {Duration}s",
                    CircuitBreakerFailureThreshold, CircuitBreakerOpenDuration.TotalSeconds);
            }
        }
    }

    // ── Document builder (shared between IndexAsync and BulkIndexAsync) ──────

    private static EsDocument BuildEsDocument(IndexDocument document, IReadOnlyList<IndexChunk> chunks)
    {
        var esChunks = chunks.Select(c => new EsChunk
        {
            ChunkId = c.ChunkId,
            ChunkIndex = c.ChunkIndex,
            Text = c.Text,
            Embedding = c.Embedding?.ToArray(),
            Metadata = c.Metadata
        }).ToList();

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
                        for (var i = 0; i < dims && i < c.Embedding!.Count; i++)
                            docEmbedding[i] += c.Embedding![i];
                    for (var i = 0; i < dims; i++)
                        docEmbedding[i] /= withEmbedding.Count;
                }
            }
        }

        return new EsDocument
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
