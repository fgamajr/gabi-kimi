using FluentAssertions;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Moq;

namespace Gabi.Postgres.Tests;

[Collection("Postgres")]
public class DocumentRepositoryTests : IDisposable
{
    private readonly string _testSourceId = "docs_" + Guid.NewGuid().ToString("N")[..12];
    private readonly GabiDbContext _context;
    private readonly DocumentRepository _repository;

    public DocumentRepositoryTests(PostgresFixture fixture)
    {
        var options = new DbContextOptionsBuilder<GabiDbContext>()
            .UseNpgsql(fixture.ConnectionString)
            .Options;

        _context = new GabiDbContext(options);
        var loggerMock = new Mock<ILogger<DocumentRepository>>();
        _repository = new DocumentRepository(_context, loggerMock.Object);
    }

    public void Dispose()
    {
        _context.Dispose();
    }

    [Fact]
    public async Task AddAsync_DocumentWithExternalId_ShouldSaveSuccessfully()
    {
        // Arrange
        var source = new SourceRegistryEntity
        {
            Id = _testSourceId,
            Name = "Test Source Docs",
            Provider = "TEST",
            DiscoveryStrategy = "WebScraper",
            DiscoveryConfig = "{}"
        };
        _context.SourceRegistries.Add(source);

        var link = new DiscoveredLinkEntity
        {
            SourceId = _testSourceId,
            Url = "https://pesquisa.apps.tcu.gov.br/#/acordao-completo/1",
            UrlHash = "abc123hash"
        };
        _context.DiscoveredLinks.Add(link);
        await _context.SaveChangesAsync();

        var document = new DocumentEntity
        {
            LinkId = link.Id,
            SourceId = _testSourceId,
            ExternalId = "ACORDAO-2024-12345",  // New field
            SourceContentHash = "sha256:abcdef123456",  // New field
            Title = "Test Document",
            Content = "Test content"
        };

        // Act
        await _repository.AddAsync(document);
        await _context.SaveChangesAsync();

        // Assert
        var savedDoc = await _context.Documents.FirstOrDefaultAsync(d => d.ExternalId == "ACORDAO-2024-12345");
        savedDoc.Should().NotBeNull();
        savedDoc!.ExternalId.Should().Be("ACORDAO-2024-12345");
        savedDoc.SourceContentHash.Should().Be("sha256:abcdef123456");
    }

    [Fact]
    public async Task GetByExternalIdAsync_ExistingDocument_ShouldReturnCorrectDocument()
    {
        // Arrange
        var source = new SourceRegistryEntity
        {
            Id = _testSourceId,
            Name = "Test Source Docs",
            Provider = "TEST",
            DiscoveryStrategy = "WebScraper",
            DiscoveryConfig = "{}"
        };
        _context.SourceRegistries.Add(source);

        var link = new DiscoveredLinkEntity
        {
            SourceId = _testSourceId,
            Url = "https://pesquisa.apps.tcu.gov.br/#/acordao-completo/1",
            UrlHash = "abc123hash"
        };
        _context.DiscoveredLinks.Add(link);
        await _context.SaveChangesAsync();

        var document = new DocumentEntity
        {
            LinkId = link.Id,
            SourceId = _testSourceId,
            ExternalId = "ACORDAO-2024-99999",
            SourceContentHash = "sha256:uniquehash",
            Title = "Unique Document"
        };
        _context.Documents.Add(document);
        await _context.SaveChangesAsync();

        // Act
        var result = await _repository.GetByExternalIdAsync(_testSourceId, "ACORDAO-2024-99999");

        // Assert
        result.Should().NotBeNull();
        result!.ExternalId.Should().Be("ACORDAO-2024-99999");
        result.SourceId.Should().Be(_testSourceId);
    }

    [Fact]
    public async Task GetByExternalIdAsync_NonExistingDocument_ShouldReturnNull()
    {
        // Act
        var result = await _repository.GetByExternalIdAsync("non-existent", "NON-EXISTENT-123");

        // Assert
        result.Should().BeNull();
    }

    [Fact]
    public async Task MarkAsRemovedAsync_ExistingDocument_ShouldSetRemovedFromSourceAt()
    {
        // Arrange
        var source = new SourceRegistryEntity
        {
            Id = _testSourceId,
            Name = "Test Source Docs",
            Provider = "TEST",
            DiscoveryStrategy = "WebScraper",
            DiscoveryConfig = "{}"
        };
        _context.SourceRegistries.Add(source);

        var link = new DiscoveredLinkEntity
        {
            SourceId = _testSourceId,
            Url = "https://pesquisa.apps.tcu.gov.br/#/acordao-completo/1",
            UrlHash = "abc123hash"
        };
        _context.DiscoveredLinks.Add(link);
        await _context.SaveChangesAsync();

        var document = new DocumentEntity
        {
            LinkId = link.Id,
            SourceId = _testSourceId,
            ExternalId = "ACORDAO-TO-REMOVE",
            SourceContentHash = "sha256:removeme",
            Title = "Document to Remove"
        };
        _context.Documents.Add(document);
        await _context.SaveChangesAsync();

        // Act
        await _repository.MarkAsRemovedAsync(_testSourceId, "ACORDAO-TO-REMOVE", "Document removed from source");
        await _context.SaveChangesAsync();

        // Assert
        var updatedDoc = await _context.Documents.FirstOrDefaultAsync(d => d.ExternalId == "ACORDAO-TO-REMOVE");
        updatedDoc.Should().NotBeNull();
        updatedDoc!.RemovedFromSourceAt.Should().NotBeNull();
        updatedDoc.RemovedReason.Should().Be("Document removed from source");
    }

    [Fact]
    public async Task GetActiveBySourceAsync_WithMixedDocuments_ShouldExcludeRemoved()
    {
        // Arrange
        var source = new SourceRegistryEntity
        {
            Id = _testSourceId,
            Name = "Test Source Docs",
            Provider = "TEST",
            DiscoveryStrategy = "WebScraper",
            DiscoveryConfig = "{}"
        };
        _context.SourceRegistries.Add(source);

        var link = new DiscoveredLinkEntity
        {
            SourceId = _testSourceId,
            Url = "https://pesquisa.apps.tcu.gov.br/#/acordao-completo/1",
            UrlHash = "abc123hash"
        };
        _context.DiscoveredLinks.Add(link);
        await _context.SaveChangesAsync();

        // Add active document
        var activeDoc = new DocumentEntity
        {
            LinkId = link.Id,
            SourceId = _testSourceId,
            ExternalId = "ACTIVE-1",
            SourceContentHash = "hash1",
            Title = "Active Document"
        };
        _context.Documents.Add(activeDoc);

        // Add another active document
        var activeDoc2 = new DocumentEntity
        {
            LinkId = link.Id,
            SourceId = _testSourceId,
            ExternalId = "ACTIVE-2",
            SourceContentHash = "hash2",
            Title = "Another Active Document"
        };
        _context.Documents.Add(activeDoc2);

        // Add removed document
        var removedDoc = new DocumentEntity
        {
            LinkId = link.Id,
            SourceId = _testSourceId,
            ExternalId = "REMOVED-1",
            SourceContentHash = "hash3",
            Title = "Removed Document",
            RemovedFromSourceAt = DateTime.UtcNow.AddDays(-1),
            RemovedReason = "Source deletion"
        };
        _context.Documents.Add(removedDoc);

        await _context.SaveChangesAsync();

        // Act
        var activeDocs = await _repository.GetActiveBySourceAsync(_testSourceId);

        // Assert
        activeDocs.Should().HaveCount(2);
        activeDocs.Should().OnlyContain(d => d.RemovedFromSourceAt == null);
        activeDocs.Should().Contain(d => d.ExternalId == "ACTIVE-1");
        activeDocs.Should().Contain(d => d.ExternalId == "ACTIVE-2");
        activeDocs.Should().NotContain(d => d.ExternalId == "REMOVED-1");
    }

    [Fact]
    public async Task GetActiveBySourceAsync_DifferentSource_ShouldReturnOnlyMatchingSource()
    {
        var s1 = _testSourceId + "_s1";
        var s2 = _testSourceId + "_s2";
        // Arrange
        var source1 = new SourceRegistryEntity
        {
            Id = s1,
            Name = "Source 1",
            Provider = "Provider1",
            DiscoveryStrategy = "WebScraper",
            DiscoveryConfig = "{}"
        };
        var source2 = new SourceRegistryEntity
        {
            Id = s2,
            Name = "Source 2",
            Provider = "Provider2",
            DiscoveryStrategy = "WebScraper",
            DiscoveryConfig = "{}"
        };
        _context.SourceRegistries.AddRange(source1, source2);

        var link1 = new DiscoveredLinkEntity
        {
            SourceId = s1,
            Url = "https://example.com/1",
            UrlHash = "hash1"
        };
        var link2 = new DiscoveredLinkEntity
        {
            SourceId = s2,
            Url = "https://example.com/2",
            UrlHash = "hash2"
        };
        _context.DiscoveredLinks.AddRange(link1, link2);
        await _context.SaveChangesAsync();

        var doc1 = new DocumentEntity
        {
            LinkId = link1.Id,
            SourceId = s1,
            ExternalId = "DOC-SOURCE1",
            SourceContentHash = "hash1",
            Title = "Doc from Source 1"
        };
        var doc2 = new DocumentEntity
        {
            LinkId = link2.Id,
            SourceId = s2,
            ExternalId = "DOC-SOURCE2",
            SourceContentHash = "hash2",
            Title = "Doc from Source 2"
        };
        _context.Documents.AddRange(doc1, doc2);
        await _context.SaveChangesAsync();

        // Act
        var source1Docs = await _repository.GetActiveBySourceAsync(s1);

        // Assert
        source1Docs.Should().HaveCount(1);
        source1Docs.First().ExternalId.Should().Be("DOC-SOURCE1");
    }
}
