using Xunit;

namespace Gabi.Api.Tests;

/// <summary>
/// Serializes all API integration test classes that share CustomWebApplicationFactory or
/// the static FakeJobQueueRepository.LastEnqueuedJob field, preventing race conditions.
/// </summary>
[CollectionDefinition("Api")]
public sealed class ApiTestCollection
{
}
