using FluentAssertions;
using Gabi.Contracts.Chunk;
using Gabi.Contracts.Embed;
using Gabi.Contracts.Ingest;
using Gabi.Contracts.Index;
using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Worker.Jobs;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Moq;

namespace Gabi.Postgres.Tests;

/// <summary>
/// Verifies that EmbedAndIndexJobExecutor loads documents by IDs, runs normalize/chunk/embed/index, and marks them completed.
/// </summary>
public sealed class EmbedAndIndexJobExecutorTests : IDisposable
{
    private readonly GabiDbContext _context;
    private readonly Mock<IEmbedder> _embedderMock;
    private readonly Mock<IDocumentIndexer> _indexerMock;
    private readonly EmbedAndIndexJobExecutor _executor;

    public EmbedAndIndexJobExecutorTests()
    {
        var options = new DbContextOptionsBuilder<GabiDbContext>()
            .UseInMemoryDatabase(Guid.NewGuid().ToString())
            .Options;
        _context = new GabiDbContext(options);
        _context.Database.EnsureCreated();

        _embedderMock = new Mock<IEmbedder>();
        _embedderMock
            .Setup(x => x.EmbedChunksAsync(It.IsAny<IReadOnlyList<Chunk>>(), It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync((IReadOnlyList<Chunk> chunks, string docId, CancellationToken _) => new EmbeddingResult
            {
                DocumentId = docId,
                Model = "test",
                TotalEmbeddings = chunks.Count,
                Chunks = chunks.Select((c, i) => new EmbeddedChunk
                {
                    Index = i,
                    Text = c.Text,
                    Embedding = new List<float>(Enumerable.Range(0, 4).Select(_ => 0.1f)),
                    Model = "test",
                    Dimensions = 4
                }).ToList()
            });

        _indexerMock = new Mock<IDocumentIndexer>();
        _indexerMock
            .Setup(x => x.IndexAsync(It.IsAny<IndexDocument>(), It.IsAny<IReadOnlyList<IndexChunk>>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync((IndexDocument d, IReadOnlyList<IndexChunk> c, CancellationToken _) => new IndexingResult
            {
                DocumentId = d.DocumentId,
                Status = IndexingStatus.Success,
                ChunksIndexed = c.Count,
                PgSuccess = true,
                EsSuccess = true
            });
        _indexerMock
            .Setup(x => x.BulkIndexAsync(It.IsAny<IReadOnlyList<(IndexDocument, IReadOnlyList<IndexChunk>)>>(), It.IsAny<CancellationToken>()))
            .Returns(async (IReadOnlyList<(IndexDocument d, IReadOnlyList<IndexChunk> c)> batch, CancellationToken ct) =>
            {
                var results = new List<IndexingResult>();
                foreach (var (d, c) in batch)
                    results.Add(new IndexingResult { DocumentId = d.DocumentId, Status = IndexingStatus.Success, ChunksIndexed = c.Count, PgSuccess = true, EsSuccess = true });
                return (IReadOnlyList<IndexingResult>)results;
            });

        var normalizer = new Mock<ICanonicalDocumentNormalizer>();
        normalizer
            .Setup(x => x.Normalize(It.IsAny<CanonicalTextDocument>()))
            .Returns((CanonicalTextDocument d) => d);

        var chunker = new Mock<IChunker>();
        chunker
            .Setup(x => x.Chunk(It.IsAny<string>(), It.IsAny<ChunkConfig>(), It.IsAny<IReadOnlyDictionary<string, object>>()))
            .Returns((string content, ChunkConfig _, IReadOnlyDictionary<string, object> meta) => new ChunkResult
            {
                Chunks = new List<Chunk> { new Chunk(0, content, 1, ChunkType.Content) },
                TotalTokens = 1
            });

        var logger = new Mock<ILogger<EmbedAndIndexJobExecutor>>();

        _executor = new EmbedAndIndexJobExecutor(
            _context,
            normalizer.Object,
            chunker.Object,
            _embedderMock.Object,
            _indexerMock.Object,
            logger.Object);
    }

    [Fact]
    public async Task ExecuteAsync_MarksDocumentsCompleted_WhenPayloadHasValidDocumentIds()
    {
        const string sourceId = "embed_test_source";
        var linkId = await SeedLinkAsync(sourceId);
        var docId1 = Guid.NewGuid();
        var docId2 = Guid.NewGuid();
        _context.Documents.Add(new DocumentEntity
        {
            Id = docId1,
            SourceId = sourceId,
            LinkId = linkId,
            Status = "pending",
            Content = "Hello world one",
            Title = "Doc 1",
            ExternalId = "ext-1",
            CreatedAt = DateTime.UtcNow
        });
        _context.Documents.Add(new DocumentEntity
        {
            Id = docId2,
            SourceId = sourceId,
            LinkId = linkId,
            Status = "pending",
            Content = "Hello world two",
            Title = "Doc 2",
            ExternalId = "ext-2",
            CreatedAt = DateTime.UtcNow
        });
        await _context.SaveChangesAsync();

        var job = new IngestJob
        {
            Id = Guid.NewGuid(),
            SourceId = sourceId,
            JobType = "embed_and_index",
            Payload = new Dictionary<string, object>
            {
                ["document_ids"] = new List<object> { (object)docId1.ToString(), (object)docId2.ToString() }
            }
        };

        await _executor.ExecuteAsync(job, new Progress<JobProgress>(_ => { }), CancellationToken.None);

        var docs = await _context.Documents.Where(d => d.SourceId == sourceId).ToListAsync();
        docs.Should().HaveCount(2);
        docs.Should().OnlyContain(d => d.Status == "completed");
    }

    [Fact]
    public async Task ExecuteAsync_ReturnsSuccess_WhenNoPendingDocumentsMatchIds()
    {
        const string sourceId = "no_docs_source";
        var job = new IngestJob
        {
            Id = Guid.NewGuid(),
            SourceId = sourceId,
            JobType = "embed_and_index",
            Payload = new Dictionary<string, object>
            {
                ["document_ids"] = new List<string> { Guid.NewGuid().ToString() }
            }
        };

        var result = await _executor.ExecuteAsync(job, new Progress<JobProgress>(_ => { }), CancellationToken.None);

        result.Status.Should().Be(JobTerminalStatus.Success);
    }

    private async Task<long> SeedLinkAsync(string sourceId)
    {
        _context.SourceRegistries.Add(new SourceRegistryEntity
        {
            Id = sourceId,
            Name = "Test",
            Provider = "TEST",
            DiscoveryConfig = "{}"
        });
        _context.DiscoveredLinks.Add(new DiscoveredLinkEntity
        {
            SourceId = sourceId,
            Url = "https://example.com/1",
            UrlHash = "h1",
            Status = "completed",
            DiscoveryStatus = "completed",
            FetchStatus = "completed",
            IngestStatus = "pending",
            FirstSeenAt = DateTime.UtcNow,
            DiscoveredAt = DateTime.UtcNow,
            CreatedAt = DateTime.UtcNow,
            UpdatedAt = DateTime.UtcNow
        });
        await _context.SaveChangesAsync();
        var link = await _context.DiscoveredLinks.FirstAsync(l => l.SourceId == sourceId);
        return link.Id;
    }

    public void Dispose() => _context.Dispose();
}
