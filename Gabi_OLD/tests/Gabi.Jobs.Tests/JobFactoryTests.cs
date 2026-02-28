using Gabi.Contracts.Discovery;
using Gabi.Contracts.Jobs;
using Xunit;

namespace Gabi.Jobs.Tests;

/// <summary>
/// Tests for JobFactory following TDD principles.
/// </summary>
public class JobFactoryTests
{
    private const string TestSourceId = "test_source_jobs";
    private readonly JobFactory _factory;

    public JobFactoryTests()
    {
        _factory = new JobFactory();
    }

    [Fact]
    public void CreateSourceJobAsync_WithValidSource_CreatesJobWithCorrectProperties()
    {
        // Arrange
        var sourceId = TestSourceId;
        var discoveryResult = new DiscoveryResult
        {
            SourceId = sourceId,
            Urls = new List<DiscoveredSource>
            {
                new("https://example.com/1.csv", sourceId, new Dictionary<string, object>(), DateTime.UtcNow),
                new("https://example.com/2.csv", sourceId, new Dictionary<string, object>(), DateTime.UtcNow)
            }
        };

        // Act
        var job = _factory.CreateSourceJobAsync(sourceId, discoveryResult, CancellationToken.None).Result;

        // Assert
        Assert.NotEqual(Guid.Empty, job.Id);
        Assert.Equal(sourceId, job.SourceId);
        Assert.Equal("discover", job.JobType);
        Assert.Equal(JobStatus.Pending, job.Status);
        Assert.Equal(0, job.RetryCount);
        Assert.NotNull(job.Payload);
        Assert.True(job.CreatedAt <= DateTime.UtcNow);
    }

    [Fact]
    public void CreateSourceJobAsync_SetsTotalLinksInPayload()
    {
        // Arrange
        var sourceId = TestSourceId;
        var discoveryResult = new DiscoveryResult
        {
            SourceId = sourceId,
            Urls = new List<DiscoveredSource>
            {
                new("https://example.com/1.csv", sourceId, new Dictionary<string, object>(), DateTime.UtcNow),
                new("https://example.com/2.csv", sourceId, new Dictionary<string, object>(), DateTime.UtcNow),
                new("https://example.com/3.csv", sourceId, new Dictionary<string, object>(), DateTime.UtcNow)
            }
        };

        // Act
        var job = _factory.CreateSourceJobAsync(sourceId, discoveryResult, CancellationToken.None).Result;

        // Assert
        Assert.True(job.Payload.ContainsKey("totalLinks"));
        Assert.Equal(3, job.Payload["totalLinks"]);
    }

    [Fact]
    public void CreateDocumentJobsAsync_CreatesChildJobsWithParentReference()
    {
        // Arrange
        var parentJobId = Guid.NewGuid();
        var sourceId = TestSourceId;
        var docs = new List<DocumentInfo>
        {
            new("doc-001", "https://example.com/doc1.pdf", "Title 1", sourceId),
            new("doc-002", "https://example.com/doc2.pdf", "Title 2", sourceId)
        };

        // Act
        var jobs = _factory.CreateDocumentJobsAsync(parentJobId, docs, CancellationToken.None).Result;

        // Assert
        Assert.Equal(2, jobs.Count);
        Assert.All(jobs, job =>
        {
            Assert.Equal(parentJobId, job.ParentJobId);
            Assert.Equal("fetch", job.JobType);
            Assert.Equal(JobStatus.Pending, job.Status);
        });
    }

    [Fact]
    public void CreateDocumentJobsAsync_SetsDocumentIdInPayload()
    {
        // Arrange
        var parentJobId = Guid.NewGuid();
        var sourceId = TestSourceId;
        var docs = new List<DocumentInfo>
        {
            new("doc-001", "https://example.com/doc1.pdf", "Title 1", sourceId)
        };

        // Act
        var jobs = _factory.CreateDocumentJobsAsync(parentJobId, docs, CancellationToken.None).Result;

        // Assert
        Assert.Single(jobs);
        Assert.Equal("doc-001", jobs[0].DocumentId);
        Assert.True(jobs[0].Payload.ContainsKey("url"));
        Assert.Equal("https://example.com/doc1.pdf", jobs[0].Payload["url"]);
    }

    [Fact]
    public void CreateDocumentJobsAsync_WithEmptyList_ReturnsEmptyList()
    {
        // Arrange
        var parentJobId = Guid.NewGuid();
        var docs = new List<DocumentInfo>();

        // Act
        var jobs = _factory.CreateDocumentJobsAsync(parentJobId, docs, CancellationToken.None).Result;

        // Assert
        Assert.Empty(jobs);
    }

    [Fact]
    public void CreateJobAsync_WithCustomType_CreatesJobWithSpecifiedType()
    {
        // Arrange
        var jobType = "hash";
        var sourceId = TestSourceId;
        var payload = new JobPayload(new Dictionary<string, object> { ["documentId"] = "doc-001" });

        // Act
        var job = _factory.CreateJobAsync(jobType, sourceId, payload, CancellationToken.None).Result;

        // Assert
        Assert.Equal(jobType, job.JobType);
        Assert.Equal(sourceId, job.SourceId);
        Assert.Equal("doc-001", job.Payload["documentId"]);
    }

    [Fact]
    public void CreateDocumentJobsAsync_SetsSourceIdFromDocumentInfo()
    {
        // Arrange
        var parentJobId = Guid.NewGuid();
        var sourceId = TestSourceId;
        var docs = new List<DocumentInfo>
        {
            new("doc-001", "url", "Title", sourceId)
        };

        // Act
        var jobs = _factory.CreateDocumentJobsAsync(parentJobId, docs, CancellationToken.None).Result;

        // Assert
        Assert.All(jobs, job => Assert.Equal(sourceId, job.SourceId));
    }
}
