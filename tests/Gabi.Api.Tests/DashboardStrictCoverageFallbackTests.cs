using System.Net;
using System.Text;
using System.Text.Json;
using Gabi.Api.Tests.Security;
using Xunit;

namespace Gabi.Api.Tests;

/// <summary>
/// Verifies that when triggering discovery (or fetch) without sending strict_coverage in the request,
/// the Dashboard uses PipelineConfig from DB (coverage.strict) and enqueues the job with strict_coverage=true.
/// </summary>
public class DashboardStrictCoverageFallbackTests : IClassFixture<CustomWebApplicationFactory>
{
    private readonly CustomWebApplicationFactory _factory;

    public DashboardStrictCoverageFallbackTests(CustomWebApplicationFactory factory)
    {
        _factory = factory;
    }

    [Fact]
    public async Task TriggerDiscovery_WhenSourceHasPipelineConfigStrictTrue_EnqueuesJobWithStrictCoverageTrue()
    {
        var sourceId = "strict_fallback_test_source";
        await _factory.EnsureSourceWithStrictPipelineConfigAsync(sourceId);

        FakeJobQueueRepository.ClearLastEnqueuedJob();

        var client = await _factory.CreateAuthenticatedClientAsync("operator", "operator123");
        var body = new { force = true };
        var content = new StringContent(JsonSerializer.Serialize(body), Encoding.UTF8, "application/json");
        var response = await client.PostAsync(
            $"/api/v1/dashboard/sources/{sourceId}/phases/discovery",
            content);

        Assert.True(response.IsSuccessStatusCode, $"Expected success but got {response.StatusCode}: {await response.Content.ReadAsStringAsync()}");

        var lastJob = FakeJobQueueRepository.LastEnqueuedJob;
        Assert.NotNull(lastJob);
        Assert.True(lastJob.Payload.TryGetValue("strict_coverage", out var raw) && raw is true,
            $"Expected Payload to contain strict_coverage=true when source has pipeline.coverage.strict, got: {JsonSerializer.Serialize(lastJob.Payload)}");
    }

    [Fact]
    public async Task TriggerFetch_WhenSourceHasPipelineConfigStrictTrue_EnqueuesJobWithStrictCoverageTrue()
    {
        var sourceId = "strict_fallback_fetch_test_source";
        await _factory.EnsureSourceWithStrictPipelineConfigAsync(sourceId);

        FakeJobQueueRepository.ClearLastEnqueuedJob();

        var client = await _factory.CreateAuthenticatedClientAsync("operator", "operator123");
        var body = new { };
        var content = new StringContent(JsonSerializer.Serialize(body), Encoding.UTF8, "application/json");
        var response = await client.PostAsync(
            $"/api/v1/dashboard/sources/{sourceId}/phases/fetch",
            content);

        Assert.True(response.IsSuccessStatusCode, $"Expected success but got {response.StatusCode}: {await response.Content.ReadAsStringAsync()}");

        var lastJob = FakeJobQueueRepository.LastEnqueuedJob;
        Assert.NotNull(lastJob);
        Assert.True(lastJob.Payload.TryGetValue("strict_coverage", out var raw) && raw is true,
            $"Expected Payload to contain strict_coverage=true when source has pipeline.coverage.strict, got: {JsonSerializer.Serialize(lastJob.Payload)}");
    }
}
