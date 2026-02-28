using Gabi.Contracts.Discovery;
using Gabi.Contracts.Jobs;

namespace Gabi.Jobs;

/// <summary>
/// Factory for creating ingestion jobs.
/// </summary>
public interface IJobFactory
{
    /// <summary>
    /// Creates a parent job for a source discovery.
    /// </summary>
    Task<IngestJob> CreateSourceJobAsync(string sourceId, DiscoveryResult result, CancellationToken ct);

    /// <summary>
    /// Creates child jobs for documents (batch creation).
    /// </summary>
    Task<IReadOnlyList<IngestJob>> CreateDocumentJobsAsync(Guid parentJobId, IEnumerable<DocumentInfo> docs, CancellationToken ct);

    /// <summary>
    /// Creates a generic job with specified type and payload.
    /// </summary>
    Task<IngestJob> CreateJobAsync(string jobType, string sourceId, JobPayload payload, CancellationToken ct);
}

/// <summary>
/// Information about a document for job creation.
/// </summary>
public record DocumentInfo(string Id, string Url, string Title, string SourceId);

/// <summary>
/// Payload for job creation.
/// </summary>
public record JobPayload(Dictionary<string, object> Data);
