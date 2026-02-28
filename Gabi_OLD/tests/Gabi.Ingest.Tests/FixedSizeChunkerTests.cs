using Gabi.Contracts.Chunk;
using Xunit;

namespace Gabi.Ingest.Tests;

public class FixedSizeChunkerTests
{
    [Fact]
    public void Chunk_EmptyText_ReturnsEmptyChunks()
    {
        var chunker = new FixedSizeChunker();
        var config = new ChunkConfig { Strategy = "fixed", MaxChunkSize = 64, Overlap = 0 };

        var result = chunker.Chunk("", config);

        Assert.NotNull(result.Chunks);
        Assert.Empty(result.Chunks);
        Assert.Equal(0, result.TotalTokens);
    }

    [Fact]
    public void Chunk_ShortText_ReturnsOneChunk()
    {
        var chunker = new FixedSizeChunker();
        var config = new ChunkConfig { Strategy = "fixed", MaxChunkSize = 64, Overlap = 0 };
        var text = "Um texto curto para um único chunk.";

        var result = chunker.Chunk(text, config);

        Assert.Single(result.Chunks);
        Assert.Equal("Um texto curto para um único chunk.", result.Chunks[0].Text);
        Assert.True(result.TotalTokens > 0);
        Assert.Equal(text.Length, result.TotalChars);
    }

    [Fact]
    public void Chunk_LongText_RespectsMaxChunkSize()
    {
        var chunker = new FixedSizeChunker();
        // Chunker enforces minimum MaxChunkSize 32 (see FixedSizeChunker.cs)
        var config = new ChunkConfig { Strategy = "fixed", MaxChunkSize = 32, Overlap = 0 };
        var words = Enumerable.Range(0, 50).Select(i => $"word{i}").ToArray();
        var text = string.Join(" ", words);

        var result = chunker.Chunk(text, config);

        Assert.NotEmpty(result.Chunks);
        Assert.Equal(50, result.TotalTokens);
        foreach (var c in result.Chunks)
            Assert.InRange(c.TokenCount, 1, 32);
    }

    [Fact]
    public void Chunk_PassesMetadataToChunks()
    {
        var chunker = new FixedSizeChunker();
        var config = new ChunkConfig { Strategy = "fixed", MaxChunkSize = 64, Overlap = 0 };
        var metadata = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase)
        {
            ["source_id"] = "test_source",
            ["normative_force"] = "binding"
        };

        var result = chunker.Chunk("Texto com metadado.", config, metadata);

        Assert.NotEmpty(result.Chunks);
        var chunk = result.Chunks[0];
        Assert.NotNull(chunk.Metadata);
        Assert.True(chunk.Metadata.ContainsKey("source_id"));
        Assert.Equal("test_source", chunk.Metadata["source_id"]);
        Assert.Equal("binding", chunk.Metadata["normative_force"]);
    }
}
