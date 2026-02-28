using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using Gabi.Contracts.Chunk;
using Gabi.Contracts.Embed;

namespace Gabi.Ingest;

/// <summary>
/// Deterministic local embedder used as default in development and tests.
/// Produces stable vectors without external services.
/// </summary>
public sealed class HashEmbedder : IEmbedder
{
    private const string ModelName = "hash-embedder-v1";
    private const int VectorDimensions = 384;

    public Task<IReadOnlyList<float>> EmbedAsync(string text, CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();
        return Task.FromResult<IReadOnlyList<float>>(CreateVector(text));
    }

    public Task<IReadOnlyList<IReadOnlyList<float>>> EmbedBatchAsync(IReadOnlyList<string> texts, CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();

        var vectors = new List<IReadOnlyList<float>>(texts.Count);
        foreach (var text in texts)
        {
            ct.ThrowIfCancellationRequested();
            vectors.Add(CreateVector(text));
        }

        return Task.FromResult<IReadOnlyList<IReadOnlyList<float>>>(vectors);
    }

    public Task<EmbeddingResult> EmbedChunksAsync(IReadOnlyList<Chunk> chunks, string documentId, CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();

        var stopwatch = Stopwatch.StartNew();
        var embeddedChunks = new List<EmbeddedChunk>(chunks.Count);
        var tokens = 0;

        foreach (var chunk in chunks)
        {
            ct.ThrowIfCancellationRequested();

            var vector = CreateVector(chunk.Text);
            embeddedChunks.Add(new EmbeddedChunk
            {
                Text = chunk.Text,
                Index = chunk.Index,
                TokenCount = chunk.TokenCount,
                CharCount = chunk.CharCount,
                SectionType = chunk.SectionType ?? "content",
                Embedding = vector,
                Model = ModelName,
                Dimensions = VectorDimensions,
                Metadata = chunk.Metadata
            });

            tokens += chunk.TokenCount;
        }

        var result = new EmbeddingResult
        {
            DocumentId = documentId,
            Chunks = embeddedChunks,
            Model = ModelName,
            TotalEmbeddings = embeddedChunks.Count,
            TokensProcessed = tokens,
            DurationSeconds = stopwatch.Elapsed.TotalSeconds
        };

        return Task.FromResult(result);
    }

    public Task<bool> HealthCheckAsync(CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();
        return Task.FromResult(true);
    }

    private static IReadOnlyList<float> CreateVector(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return new float[VectorDimensions];

        var input = Encoding.UTF8.GetBytes(text.Trim());
        var hash = SHA256.HashData(input);
        var vector = new float[VectorDimensions];

        for (var i = 0; i < VectorDimensions; i++)
        {
            var value = hash[i % hash.Length];
            vector[i] = (value / 127.5f) - 1f;
        }

        return vector;
    }
}
