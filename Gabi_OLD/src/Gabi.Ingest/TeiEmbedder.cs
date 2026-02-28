using System.Diagnostics;
using System.Net.Http.Json;
using System.Text.Json;
using Gabi.Contracts.Chunk;
using Gabi.Contracts.Embed;
using Microsoft.Extensions.Logging;

namespace Gabi.Ingest;

/// <summary>
/// TEI (Text Embeddings Inference) embedder. POST to GABI_EMBEDDINGS_URL/embed, batch up to 32, 384 dimensions.
/// Circuit breaker: 5 consecutive failures → open 30s.
/// </summary>
public sealed class TeiEmbedder : IEmbedder
{
    private const string ModelName = "tei-embedder";
    private const int MaxBatchSize = 32;
    private const int ExpectedDimensions = 384;
    private const int CircuitBreakerFailureThreshold = 5;
    private static readonly TimeSpan CircuitBreakerOpenDuration = TimeSpan.FromSeconds(30);

    private readonly HttpClient _httpClient;
    private readonly ILogger<TeiEmbedder> _logger;
    private int _consecutiveFailures;
    private DateTime _circuitOpenedAt = DateTime.MinValue;
    private readonly object _circuitLock = new();

    public TeiEmbedder(HttpClient httpClient, ILogger<TeiEmbedder> logger)
    {
        _httpClient = httpClient;
        _logger = logger;
    }

    public async Task<IReadOnlyList<float>> EmbedAsync(string text, CancellationToken ct = default)
    {
        var batch = await EmbedBatchAsync(new[] { text }, ct);
        return batch.Count > 0 ? batch[0] : Array.Empty<float>();
    }

    public async Task<IReadOnlyList<IReadOnlyList<float>>> EmbedBatchAsync(IReadOnlyList<string> texts, CancellationToken ct = default)
    {
        if (texts.Count == 0)
            return Array.Empty<IReadOnlyList<float>>();

        var results = new List<IReadOnlyList<float>>();
        for (var i = 0; i < texts.Count; i += MaxBatchSize)
        {
            ct.ThrowIfCancellationRequested();
            var batch = texts.Skip(i).Take(MaxBatchSize).ToList();
            var vectors = await CallEmbedAsync(batch, ct);
            foreach (var v in vectors)
                results.Add(v);
        }

        return results;
    }

    public async Task<EmbeddingResult> EmbedChunksAsync(IReadOnlyList<Chunk> chunks, string documentId, CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();
        var stopwatch = Stopwatch.StartNew();
        var texts = chunks.Select(c => c.Text).ToList();
        var allVectors = new List<IReadOnlyList<float>>();

        for (var i = 0; i < texts.Count; i += MaxBatchSize)
        {
            ct.ThrowIfCancellationRequested();
            var batch = texts.Skip(i).Take(MaxBatchSize).ToList();
            var vectors = await CallEmbedAsync(batch, ct);
            allVectors.AddRange(vectors);
        }

        var embeddedChunks = new List<EmbeddedChunk>(chunks.Count);
        var tokens = 0;
        for (var i = 0; i < chunks.Count; i++)
        {
            var chunk = chunks[i];
            var vector = i < allVectors.Count ? allVectors[i] : Array.Empty<float>();
            embeddedChunks.Add(new EmbeddedChunk
            {
                Text = chunk.Text,
                Index = chunk.Index,
                TokenCount = chunk.TokenCount,
                CharCount = chunk.CharCount,
                SectionType = chunk.SectionType ?? "content",
                Embedding = vector,
                Model = ModelName,
                Dimensions = vector.Count,
                Metadata = chunk.Metadata
            });
            tokens += chunk.TokenCount;
        }

        return new EmbeddingResult
        {
            DocumentId = documentId,
            Chunks = embeddedChunks,
            Model = ModelName,
            TotalEmbeddings = embeddedChunks.Count,
            TokensProcessed = tokens,
            DurationSeconds = stopwatch.Elapsed.TotalSeconds
        };
    }

    public async Task<bool> HealthCheckAsync(CancellationToken ct = default)
    {
        try
        {
            var response = await _httpClient.GetAsync("health", ct);
            return response.IsSuccessStatusCode;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "TEI health check failed");
            return false;
        }
    }

    private async Task<IReadOnlyList<IReadOnlyList<float>>> CallEmbedAsync(IReadOnlyList<string> inputs, CancellationToken ct)
    {
        if (inputs.Count == 0)
            return Array.Empty<IReadOnlyList<float>>();

        lock (_circuitLock)
        {
            if (_consecutiveFailures >= CircuitBreakerFailureThreshold)
            {
                if (DateTime.UtcNow - _circuitOpenedAt < CircuitBreakerOpenDuration)
                {
                    _logger.LogWarning("TEI circuit breaker open; rejecting call");
                    throw new InvalidOperationException("TEI embedder circuit breaker is open. Too many consecutive failures.");
                }
                _consecutiveFailures = 0;
            }
        }

        try
        {
            object payload = inputs.Count == 1
                ? new { inputs = inputs[0] }
                : new { inputs };
            using var response = await _httpClient.PostAsJsonAsync("embed", payload, ct);

            // Read Retry-After before EnsureSuccessStatusCode disposes the response (GAP-06).
            // The header is logged for operational observability; the actual retry delay is
            // controlled by IntelligentRetryPlanner (15 min for Throttled) which is conservative
            // and safe without requiring the header value to propagate through the exception chain.
            if (response.StatusCode == System.Net.HttpStatusCode.TooManyRequests)
            {
                var retryAfterDelta = response.Headers.RetryAfter?.Delta;
                _logger.LogWarning(
                    "TEI rate limit (429). Retry-After={RetryAfterSeconds}s. Batch size={BatchSize}.",
                    retryAfterDelta.HasValue ? (int)retryAfterDelta.Value.TotalSeconds : (int?)null,
                    inputs.Count);
            }

            response.EnsureSuccessStatusCode();
            var json = await response.Content.ReadAsStringAsync(ct);
            var embeddings = JsonSerializer.Deserialize<float[][]>(json);
            if (embeddings == null || embeddings.Length == 0)
                return Array.Empty<IReadOnlyList<float>>();

            lock (_circuitLock)
            {
                _consecutiveFailures = 0;
            }

            return embeddings.Select(e => (IReadOnlyList<float>)e).ToList();
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "TEI embed request failed");
            lock (_circuitLock)
            {
                _consecutiveFailures++;
                if (_consecutiveFailures >= CircuitBreakerFailureThreshold)
                    _circuitOpenedAt = DateTime.UtcNow;
            }
            throw;
        }
    }
}
