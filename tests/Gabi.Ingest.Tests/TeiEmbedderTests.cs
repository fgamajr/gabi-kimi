using System.Net;
using System.Text;
using System.Text.Json;
using Gabi.Contracts.Chunk;
using Microsoft.Extensions.Logging;
using Moq;
using Xunit;

namespace Gabi.Ingest.Tests;

/// <summary>
/// DEF-01: TeiEmbedder tests with mock HTTP (TEI /embed returns 384-dim vectors).
/// </summary>
public class TeiEmbedderTests
{
    private static HttpClient CreateMockHttpClient(int dimensions = 384, HttpStatusCode status = HttpStatusCode.OK)
    {
        return new HttpClient(new MockTeiHandler(dimensions, status))
        {
            BaseAddress = new Uri("http://tei-mock/")
        };
    }

    [Fact]
    public async Task EmbedAsync_ReturnsVector_WhenMockReturns384Dims()
    {
        var client = CreateMockHttpClient(384);
        var logger = new Mock<ILogger<TeiEmbedder>>().Object;
        var embedder = new TeiEmbedder(client, logger);

        var result = await embedder.EmbedAsync("test text");

        Assert.NotNull(result);
        Assert.Equal(384, result.Count);
    }

    [Fact]
    public async Task EmbedBatchAsync_SplitsIntoBatchesOf32()
    {
        var client = CreateMockHttpClient(384);
        var logger = new Mock<ILogger<TeiEmbedder>>().Object;
        var embedder = new TeiEmbedder(client, logger);
        var texts = Enumerable.Range(0, 40).Select(i => $"text {i}").ToList();

        var result = await embedder.EmbedBatchAsync(texts);

        Assert.Equal(40, result.Count);
        foreach (var vec in result)
            Assert.Equal(384, vec.Count);
    }

    [Fact]
    public async Task EmbedChunksAsync_ReturnsEmbeddingResult_WithCorrectDimensions()
    {
        var client = CreateMockHttpClient(384);
        var logger = new Mock<ILogger<TeiEmbedder>>().Object;
        var embedder = new TeiEmbedder(client, logger);
        var chunks = new List<Chunk>
        {
            new(0, "first chunk", 2, ChunkType.Content, "content"),
            new(1, "second chunk", 2, ChunkType.Content, "content")
        };

        var result = await embedder.EmbedChunksAsync(chunks, "doc-1");

        Assert.Equal("doc-1", result.DocumentId);
        Assert.Equal(2, result.Chunks.Count);
        Assert.Equal(2, result.TotalEmbeddings);
        foreach (var c in result.Chunks)
        {
            Assert.Equal(384, c.Dimensions);
            Assert.Equal(384, c.Embedding.Count);
        }
    }

    [Fact]
    public async Task HealthCheckAsync_ReturnsFalse_WhenMockReturnsNonSuccess()
    {
        var client = new HttpClient(new MockTeiHandler(384, HttpStatusCode.ServiceUnavailable))
        {
            BaseAddress = new Uri("http://tei-mock/")
        };
        var logger = new Mock<ILogger<TeiEmbedder>>().Object;
        var embedder = new TeiEmbedder(client, logger);

        var ok = await embedder.HealthCheckAsync();

        Assert.False(ok);
    }

    /// <summary>
    /// Mock handler: GET health → status; POST embed → JSON array of float[dimensions] per input.
    /// </summary>
    private sealed class MockTeiHandler : HttpMessageHandler
    {
        private readonly int _dimensions;
        private readonly HttpStatusCode _status;

        public MockTeiHandler(int dimensions, HttpStatusCode status)
        {
            _dimensions = dimensions;
            _status = status;
        }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            if (request.Method == HttpMethod.Get && request.RequestUri?.AbsolutePath.Contains("health", StringComparison.OrdinalIgnoreCase) == true)
            {
                return Task.FromResult(new HttpResponseMessage(_status));
            }

            if (request.Method == HttpMethod.Post && request.RequestUri?.AbsolutePath.Contains("embed", StringComparison.OrdinalIgnoreCase) == true)
            {
                if ((int)_status < 200 || (int)_status > 299)
                    return Task.FromResult(new HttpResponseMessage(_status));
                var body = request.Content?.ReadAsStringAsync(cancellationToken).GetAwaiter().GetResult();
                int count = 1;
                if (!string.IsNullOrEmpty(body))
                {
                    try
                    {
                        using var doc = JsonDocument.Parse(body);
                        if (doc.RootElement.TryGetProperty("inputs", out var inputs))
                            count = inputs.ValueKind == JsonValueKind.Array ? inputs.GetArrayLength() : 1;
                    }
                    catch { /* default 1 */ }
                }
                var vectors = new float[count][];
                for (var i = 0; i < count; i++)
                {
                    vectors[i] = new float[_dimensions];
                    for (var j = 0; j < _dimensions; j++)
                        vectors[i][j] = (float)(i * 0.01 + j * 0.001);
                }
                var json = JsonSerializer.Serialize(vectors);
                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(json, Encoding.UTF8, "application/json")
                });
            }

            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound));
        }
    }
}
