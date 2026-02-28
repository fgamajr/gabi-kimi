using Gabi.Contracts.Index;
using Microsoft.Extensions.Logging;
using Moq;
using Xunit;

namespace Gabi.Ingest.Tests;

/// <summary>
/// Ensures document and chunk metadata are part of the indexer contract and that
/// the local indexer accepts them. ElasticsearchDocumentIndexer metadata persistence
/// is implemented (EsDocument.Metadata) and should be validated in integration
/// tests (e.g. Testcontainers) when indexing to a real cluster.
/// </summary>
public class ElasticsearchDocumentIndexerMetadataTests
{
    [Fact]
    public void IndexDocument_Contract_IncludesMetadata()
    {
        var doc = new IndexDocument
        {
            DocumentId = "doc-1",
            SourceId = "source-1",
            Title = "Title",
            ContentPreview = "Preview",
            Fingerprint = "fp",
            Metadata = new Dictionary<string, object> { ["normative_force"] = "binding" },
            Status = "active",
            ChunksCount = 1,
            IngestedAt = DateTime.UtcNow
        };

        Assert.NotNull(doc.Metadata);
        Assert.Equal("binding", doc.Metadata["normative_force"]);
    }

    [Fact]
    public void IndexChunk_Contract_IncludesMetadata()
    {
        var chunk = new IndexChunk
        {
            ChunkId = "chunk-1",
            ChunkIndex = 0,
            Text = "Text",
            Metadata = new Dictionary<string, object> { ["start_token"] = 0 }
        };

        Assert.NotNull(chunk.Metadata);
        Assert.Equal(0, chunk.Metadata["start_token"]);
    }

    [Fact]
    public async Task LocalDocumentIndexer_AcceptsDocumentWithMetadata_ReturnsSuccess()
    {
        var indexer = new LocalDocumentIndexer();
        var document = new IndexDocument
        {
            DocumentId = "doc-meta",
            SourceId = "s",
            Title = "T",
            ContentPreview = "P",
            Fingerprint = "f",
            Metadata = new Dictionary<string, object> { ["key"] = "value" },
            Status = "active",
            ChunksCount = 1,
            IngestedAt = DateTime.UtcNow
        };
        var chunks = new List<IndexChunk>
        {
            new() { ChunkId = "c1", ChunkIndex = 0, Text = "chunk", Metadata = new Dictionary<string, object> { ["k"] = "v" } }
        };

        var result = await indexer.IndexAsync(document, chunks);

        Assert.Equal(IndexingStatus.Success, result.Status);
        Assert.Equal(1, result.ChunksIndexed);
    }
}
