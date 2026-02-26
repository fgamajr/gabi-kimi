using FluentAssertions;
using Gabi.ZeroKelvinHarness;
using Gabi.ZeroKelvinHarness.Infrastructure;
using Gabi.ZeroKelvinHarness.Metrics;
using Gabi.ZeroKelvinHarness.Models;
using Xunit;

namespace Gabi.System.Tests;

[Trait("Category", "System")]
public sealed class ZeroKelvinTests
{
    [Fact]
    public async Task Harness_EnvironmentManager_StartsAndResets()
    {
        await using var env = new EnvironmentManager();
        await env.StartAsync();

        try
        {
            await env.ResetAsync();
            var counts = await StageTracker.GetStageCountsAsync(env.ConnectionString, null);
            counts.Should().NotBeNull();
            counts.GetValueOrDefault("sources_seeded", -1).Should().BeGreaterThanOrEqualTo(0);
        }
        finally
        {
            await env.StopAsync();
        }
    }

    [Theory]
    [InlineData(100)]
    [InlineData(1000)]
    public async Task Pipeline_ShouldRemainStable(int documentCount)
    {
        await using var env = new EnvironmentManager();
        await env.StartAsync();

        try
        {
            using var factory = new ZeroKelvinWebApplicationFactory(env.ConnectionString, env.RedisUrl);
            var client = factory.CreateOperatorClient();
            var config = new ZeroKelvinConfig
            {
                MaxDocs = documentCount,
                SourceId = "tcu_sumulas",
                PhaseTimeout = TimeSpan.FromMinutes(2),
                SampleSize = 30
            };

            async Task<int> GetPendingAsync(string sourceId, CancellationToken ct)
            {
                var counts = await StageTracker.GetStageCountsAsync(env.ConnectionString, sourceId, ct);
                return counts.GetValueOrDefault("documents_pending", 0);
            }

            var result = await ZeroKelvinRunner.RunAsync(env, client, config, GetPendingAsync);

            result.Crashed.Should().BeFalse(result.ErrorSummary ?? "no error");
            result.StageCounts.Should().NotBeNull();
            result.LossRate.Should().BeLessThan(0.01);
            result.SemanticPreservationScore.Should().BeGreaterThan(0.95);
            result.PeakMemoryMb.Should().BeLessThan(300);
        }
        finally
        {
            await env.StopAsync();
        }
    }
}
