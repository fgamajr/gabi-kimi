using System.Collections.Generic;
using FluentAssertions;
using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Repositories;
using Gabi.Worker.Jobs;
using Gabi.ZeroKelvinHarness;
using Gabi.ZeroKelvinHarness.Infrastructure;
using Gabi.ZeroKelvinHarness.Metrics;
using Gabi.ZeroKelvinHarness.Models;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Xunit;

namespace Gabi.System.Tests;

[Trait("Category", "System")]
public sealed class ZeroKelvinTests
{
    /// <summary>
    /// Runs catalog seed synchronously so source_registry is populated before pipeline phases.
    /// Zero Kelvin only runs the API (no Worker), so we must seed the DB directly.
    /// </summary>
    private static async Task SeedSourceRegistryFromYamlAsync(string connectionString, CancellationToken ct = default)
    {
        var sourcesPath = FindSourcesV2Path();
        if (string.IsNullOrEmpty(sourcesPath) || !File.Exists(sourcesPath))
            throw new InvalidOperationException($"sources_v2.yaml not found. Looked at: {sourcesPath ?? "(null)"}; CWD={Directory.GetCurrentDirectory()}");

        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?> { ["GABI_SOURCES_PATH"] = sourcesPath })
            .Build();

        var options = new DbContextOptionsBuilder<GabiDbContext>()
            .UseNpgsql(connectionString)
            .Options;

        await using var context = new GabiDbContext(options);
        var logger = LoggerFactory.Create(_ => { }).CreateLogger<CatalogSeedJobExecutor>();
        var sourceRepo = new SourceRegistryRepository(context, LoggerFactory.Create(_ => { }).CreateLogger<SourceRegistryRepository>());
        var executor = new CatalogSeedJobExecutor(sourceRepo, context, config, logger);

        var job = new IngestJob
        {
            Id = Guid.NewGuid(),
            JobType = "catalog_seed",
            SourceId = string.Empty,
            Payload = new Dictionary<string, object>(),
            Status = JobStatus.Pending
        };
        var result = await executor.ExecuteAsync(job, new Progress<JobProgress>(_ => { }), ct);
        if (!result.Success)
            throw new InvalidOperationException($"Seed failed: {result.ErrorMessage}");
    }

    private static string? FindSourcesV2Path()
    {
        var baseDir = AppContext.BaseDirectory;
        var dir = baseDir;
        for (var i = 0; i < 8; i++)
        {
            if (string.IsNullOrEmpty(dir)) return null;
            var path = Path.Combine(dir, "sources_v2.yaml");
            if (File.Exists(path)) return Path.GetFullPath(path);
            dir = Path.GetDirectoryName(dir);
        }
        var fromCwd = Path.Combine(Directory.GetCurrentDirectory(), "sources_v2.yaml");
        return File.Exists(fromCwd) ? Path.GetFullPath(fromCwd) : null;
    }

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
            var sourcesPath = FindSourcesV2Path();
            using var factory = new ZeroKelvinWebApplicationFactory(env.ConnectionString, env.RedisUrl, sourcesPath);
            var client = factory.CreateOperatorClient();
            var config = new ZeroKelvinConfig
            {
                MaxDocs = documentCount,
                SourceId = "tcu_sumulas",
                PhaseTimeout = TimeSpan.FromMinutes(2),
                SampleSize = 30,
                Phases = new[] { "seed", "discovery", "fetch", "ingest" }
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
