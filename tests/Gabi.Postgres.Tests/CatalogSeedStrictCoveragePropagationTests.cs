using System.Text.Json;
using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Moq;
using Gabi.Worker.Jobs;

namespace Gabi.Postgres.Tests;

/// <summary>
/// Verifies that pipeline.coverage.strict from YAML is persisted into source_registry.PipelineConfig (config propagation A).
/// </summary>
[Collection("Postgres")]
public class CatalogSeedStrictCoveragePropagationTests : IDisposable
{
    private readonly GabiDbContext _context;
    private readonly CatalogSeedJobExecutor _executor;

    public CatalogSeedStrictCoveragePropagationTests(PostgresFixture fixture)
    {
        var options = new DbContextOptionsBuilder<GabiDbContext>()
            .UseNpgsql(fixture.ConnectionString)
            .Options;
        _context = new GabiDbContext(options);

        var repo = new SourceRegistryRepository(_context, Mock.Of<ILogger<SourceRegistryRepository>>());
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["GABI_SOURCES_PATH"] = "" // set per test to temp file
            })
            .Build();
        var logger = new Mock<ILogger<CatalogSeedJobExecutor>>();
        _executor = new CatalogSeedJobExecutor(repo, _context, config, logger.Object);
    }

    [Fact]
    public async Task Seed_WhenYamlHasPipelineCoverageStrictTrue_PersistsStrictInPipelineConfig()
    {
        var yaml = """
            apiVersion: gabi.io/v2
            kind: SourceCatalog
            sources:
              test_strict_source:
                identity:
                  name: "Test Strict"
                  provider: TCU
                discovery:
                  strategy: static_url
                  config:
                    url: "https://example.com/data.csv"
                fetch:
                  protocol: https
                pipeline:
                  coverage:
                    strict: true
                  ingest:
                    readiness: text_ready
            """;

        using var tmp = new TempYamlFile(yaml);
        Environment.SetEnvironmentVariable("GABI_SOURCES_PATH", tmp.Path);

        try
        {
            var job = new IngestJob
            {
                Id = Guid.NewGuid(),
                JobType = "catalog_seed",
                SourceId = "",
                Payload = new Dictionary<string, object>(),
                Status = JobStatus.Pending,
                Priority = JobPriority.Normal,
                ScheduledAt = DateTime.UtcNow,
                MaxRetries = 3
            };

            var result = await _executor.ExecuteAsync(job, new Progress<JobProgress>(_ => { }), CancellationToken.None);

            Assert.True(result.Success);

            var entity = await _context.SourceRegistries
                .AsNoTracking()
                .FirstOrDefaultAsync(s => s.Id == "test_strict_source");
            Assert.NotNull(entity);
            Assert.NotNull(entity.PipelineConfig);

            using var doc = JsonDocument.Parse(entity.PipelineConfig);
            var root = doc.RootElement;
            Assert.True(root.TryGetProperty("coverage", out var coverage), "PipelineConfig should contain 'coverage'");
            Assert.True(coverage.TryGetProperty("strict", out var strictProp), "coverage should contain 'strict'");
            Assert.True(strictProp.ValueKind == JsonValueKind.True || (strictProp.ValueKind == JsonValueKind.String && strictProp.GetString() == "true"),
                "coverage.strict should be true");
        }
        finally
        {
            Environment.SetEnvironmentVariable("GABI_SOURCES_PATH", null);
        }
    }

    [Fact]
    public async Task Seed_WhenYamlHasPipelineCoverageStrictFalse_PersistsStrictFalseInPipelineConfig()
    {
        var yaml = """
            apiVersion: gabi.io/v2
            kind: SourceCatalog
            sources:
              test_non_strict_source:
                identity:
                  name: "Test Non-Strict"
                  provider: TCU
                discovery:
                  strategy: static_url
                  config:
                    url: "https://example.com/other.csv"
                fetch:
                  protocol: https
                pipeline:
                  coverage:
                    strict: false
                  ingest:
                    readiness: text_ready
            """;

        using var tmp = new TempYamlFile(yaml);
        Environment.SetEnvironmentVariable("GABI_SOURCES_PATH", tmp.Path);

        try
        {
            var job = new IngestJob
            {
                Id = Guid.NewGuid(),
                JobType = "catalog_seed",
                SourceId = "",
                Payload = new Dictionary<string, object>(),
                Status = JobStatus.Pending,
                Priority = JobPriority.Normal,
                ScheduledAt = DateTime.UtcNow,
                MaxRetries = 3
            };

            var result = await _executor.ExecuteAsync(job, new Progress<JobProgress>(_ => { }), CancellationToken.None);

            Assert.True(result.Success);

            var entity = await _context.SourceRegistries
                .AsNoTracking()
                .FirstOrDefaultAsync(s => s.Id == "test_non_strict_source");
            Assert.NotNull(entity);
            Assert.NotNull(entity.PipelineConfig);

            using var doc = JsonDocument.Parse(entity.PipelineConfig);
            var root = doc.RootElement;
            Assert.True(root.TryGetProperty("coverage", out var coverage), "PipelineConfig should contain 'coverage'");
            Assert.True(coverage.TryGetProperty("strict", out var strictProp), "coverage should contain 'strict'");
            Assert.True(strictProp.ValueKind == JsonValueKind.False || (strictProp.ValueKind == JsonValueKind.String && strictProp.GetString() == "false"),
                "coverage.strict should be false");
        }
        finally
        {
            Environment.SetEnvironmentVariable("GABI_SOURCES_PATH", null);
        }
    }

    [Fact]
    public async Task Seed_WhenYamlHasDefaultsPipeline_MergesDefaultsIntoSources()
    {
        var uniqueId = $"defaults_test_{Guid.NewGuid():N}"[..30];
        var yaml = $"""
            apiVersion: gabi.io/v2
            kind: SourceCatalog
            defaults:
              pipeline:
                coverage:
                  strict: true
                ingest:
                  readiness: text_ready
            sources:
              {uniqueId}:
                identity:
                  name: "Defaults Merge Test"
                  provider: TCU
                discovery:
                  strategy: static_url
                  config:
                    url: "https://example.com/defaults.csv"
                fetch:
                  protocol: https
            """;

        using var tmp = new TempYamlFile(yaml);
        Environment.SetEnvironmentVariable("GABI_SOURCES_PATH", tmp.Path);

        try
        {
            var job = new IngestJob
            {
                Id = Guid.NewGuid(),
                JobType = "catalog_seed",
                SourceId = "",
                Payload = new Dictionary<string, object>(),
                Status = JobStatus.Pending,
                Priority = JobPriority.Normal,
                ScheduledAt = DateTime.UtcNow,
                MaxRetries = 3
            };

            var result = await _executor.ExecuteAsync(job, new Progress<JobProgress>(_ => { }), CancellationToken.None);

            Assert.True(result.Success);

            var entity = await _context.SourceRegistries
                .AsNoTracking()
                .FirstOrDefaultAsync(s => s.Id == uniqueId);
            Assert.NotNull(entity);
            Assert.NotNull(entity.PipelineConfig);

            using var doc = JsonDocument.Parse(entity.PipelineConfig);
            var root = doc.RootElement;
            Assert.True(root.TryGetProperty("coverage", out var coverage),
                "PipelineConfig should contain 'coverage' merged from defaults");
            Assert.True(coverage.TryGetProperty("strict", out var strictProp),
                "coverage should contain 'strict' merged from defaults");
            Assert.True(strictProp.ValueKind == JsonValueKind.True
                || (strictProp.ValueKind == JsonValueKind.String && strictProp.GetString() == "true"),
                "coverage.strict should be true (from defaults)");
        }
        finally
        {
            Environment.SetEnvironmentVariable("GABI_SOURCES_PATH", null);
        }
    }

    [Fact]
    public async Task Seed_WhenSourceOverridesPipelineDefaults_SourceValueWins()
    {
        var uniqueId = $"override_test_{Guid.NewGuid():N}"[..30];
        var yaml = $"""
            apiVersion: gabi.io/v2
            kind: SourceCatalog
            defaults:
              pipeline:
                coverage:
                  strict: true
            sources:
              {uniqueId}:
                identity:
                  name: "Override Test"
                  provider: TCU
                discovery:
                  strategy: static_url
                  config:
                    url: "https://example.com/override.csv"
                fetch:
                  protocol: https
                pipeline:
                  coverage:
                    strict: false
            """;

        using var tmp = new TempYamlFile(yaml);
        Environment.SetEnvironmentVariable("GABI_SOURCES_PATH", tmp.Path);

        try
        {
            var job = new IngestJob
            {
                Id = Guid.NewGuid(),
                JobType = "catalog_seed",
                SourceId = "",
                Payload = new Dictionary<string, object>(),
                Status = JobStatus.Pending,
                Priority = JobPriority.Normal,
                ScheduledAt = DateTime.UtcNow,
                MaxRetries = 3
            };

            var result = await _executor.ExecuteAsync(job, new Progress<JobProgress>(_ => { }), CancellationToken.None);

            Assert.True(result.Success);

            var entity = await _context.SourceRegistries
                .AsNoTracking()
                .FirstOrDefaultAsync(s => s.Id == uniqueId);
            Assert.NotNull(entity);
            Assert.NotNull(entity.PipelineConfig);

            using var doc = JsonDocument.Parse(entity.PipelineConfig);
            var root = doc.RootElement;
            Assert.True(root.TryGetProperty("coverage", out var coverage));
            Assert.True(coverage.TryGetProperty("strict", out var strictProp));
            Assert.True(strictProp.ValueKind == JsonValueKind.False
                || (strictProp.ValueKind == JsonValueKind.String && strictProp.GetString() == "false"),
                "coverage.strict should be false (source overrides default true)");
        }
        finally
        {
            Environment.SetEnvironmentVariable("GABI_SOURCES_PATH", null);
        }
    }

    public void Dispose() => _context.Dispose();

    private sealed class TempYamlFile : IDisposable
    {
        public string Path { get; }

        public TempYamlFile(string content)
        {
            Path = System.IO.Path.Combine(System.IO.Path.GetTempPath(), $"gabi_seed_test_{Guid.NewGuid():N}.yaml");
            File.WriteAllText(Path, content);
        }

        public void Dispose()
        {
            if (File.Exists(Path))
                File.Delete(Path);
        }
    }
}
