using Gabi.Contracts.Jobs;

namespace Gabi.Api.Jobs;

/// <summary>
/// Stub implementation of IGabiJobRunner for Hangfire job serialization in the API.
/// The actual implementation is in Gabi.Worker.Jobs.GabiJobRunner.
/// This stub is only needed for Hangfire to serialize the lambda expression when enqueueing jobs.
/// The Worker will resolve and execute the real implementation.
/// </summary>
public class StubGabiJobRunner : IGabiJobRunner
{
    public Task RunAsync(Guid jobId, string jobType, string sourceId, string payloadJson, CancellationToken ct)
    {
        throw new NotImplementedException(
            "This is a stub implementation. Jobs should be executed by the Worker, not the API.");
    }
}
