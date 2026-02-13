using Gabi.Contracts.Discovery;
using Gabi.Contracts.Jobs;

namespace Gabi.Jobs;

/// <summary>
/// Factory for creating ingestion jobs.
/// </summary>
public class JobFactory : IJobFactory
{
    public Task<IngestJob> CreateSourceJobAsync(string sourceId, DiscoveryResult result, CancellationToken ct)
    {
        var job = new IngestJob
        {
            Id = Guid.NewGuid(),
            SourceId = sourceId,
            JobType = "discover",
            Status = JobStatus.Pending,
            Priority = JobPriority.Normal,
            CreatedAt = DateTime.UtcNow,
            ScheduledAt = DateTime.UtcNow,
            MaxRetries = 3,
            Payload = new Dictionary<string, object>
            {
                ["totalLinks"] = result.Urls.Count,
                ["discoveryStrategy"] = result.Urls.FirstOrDefault()?.Metadata.GetValueOrDefault("strategy", "unknown") ?? "unknown"
            }
        };

        return Task.FromResult(job);
    }

    public Task<IReadOnlyList<IngestJob>> CreateDocumentJobsAsync(
        Guid parentJobId, 
        IEnumerable<DocumentInfo> docs, 
        CancellationToken ct)
    {
        var jobs = new List<IngestJob>();

        foreach (var doc in docs)
        {
            var job = new IngestJob
            {
                Id = Guid.NewGuid(),
                ParentJobId = parentJobId,
                SourceId = doc.SourceId,
                DocumentId = doc.Id,
                JobType = "fetch",
                Status = JobStatus.Pending,
                Priority = JobPriority.Normal,
                CreatedAt = DateTime.UtcNow,
                ScheduledAt = DateTime.UtcNow,
                MaxRetries = 3,
                Payload = new Dictionary<string, object>
                {
                    ["url"] = doc.Url,
                    ["title"] = doc.Title,
                    ["documentId"] = doc.Id
                }
            };

            jobs.Add(job);
        }

        return Task.FromResult<IReadOnlyList<IngestJob>>(jobs);
    }

    public Task<IngestJob> CreateJobAsync(string jobType, string sourceId, JobPayload payload, CancellationToken ct)
    {
        var job = new IngestJob
        {
            Id = Guid.NewGuid(),
            SourceId = sourceId,
            JobType = jobType,
            Status = JobStatus.Pending,
            Priority = JobPriority.Normal,
            CreatedAt = DateTime.UtcNow,
            ScheduledAt = DateTime.UtcNow,
            MaxRetries = 3,
            Payload = payload.Data
        };

        return Task.FromResult(job);
    }
}
