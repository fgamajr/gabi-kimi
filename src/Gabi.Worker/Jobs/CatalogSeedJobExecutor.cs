using System.Collections.Generic;
using System.Text.Json;
using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Microsoft.Extensions.Configuration;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Executa o seed do catálogo: lê sources_v2.yaml, persiste cada fonte no banco com retry (exponential backoff),
/// falha individual não interrompe o lote (failsafe). Ao final registra a execução em seed_runs para alimentar a fase de discovery.
/// </summary>
public class CatalogSeedJobExecutor : IJobExecutor
{
    public string JobType => "catalog_seed";

    private readonly ISourceRegistryRepository _sourceRepo;
    private readonly GabiDbContext _context;
    private readonly IConfiguration _configuration;
    private readonly ILogger<CatalogSeedJobExecutor> _logger;

    private const int MaxRetryAttempts = 3;
    private static readonly TimeSpan InitialRetryDelay = TimeSpan.FromSeconds(1);

    public CatalogSeedJobExecutor(
        ISourceRegistryRepository sourceRepo,
        GabiDbContext context,
        IConfiguration configuration,
        ILogger<CatalogSeedJobExecutor> logger)
    {
        _sourceRepo = sourceRepo;
        _context = context;
        _configuration = configuration;
        _logger = logger;
    }

    public async Task<JobResult> ExecuteAsync(
        IngestJob job,
        IProgress<JobProgress> progress,
        CancellationToken ct)
    {
        var startedAt = DateTime.UtcNow;
        progress.Report(new JobProgress { PercentComplete = 0, Message = "Carregando YAML...", Metrics = new Dictionary<string, object>() });

        var sourcesPath = ResolveSourcesPath();
        if (string.IsNullOrEmpty(sourcesPath) || !File.Exists(sourcesPath))
        {
            _logger.LogError("Sources file not found: {Path}", sourcesPath ?? "(null)");
            return new JobResult
            {
                Success = false,
                ErrorMessage = $"Sources file not found at {sourcesPath ?? "GABI_SOURCES_PATH not set"}"
            };
        }

        var sources = LoadSourcesFromYaml(sourcesPath);
        if (sources.Count == 0)
        {
            _logger.LogWarning("No sources parsed from YAML at {Path}", sourcesPath);
            return new JobResult
            {
                Success = false,
                ErrorMessage = "No sources found in YAML or parse error"
            };
        }

        progress.Report(new JobProgress
        {
            PercentComplete = 5,
            Message = $"Persistindo {sources.Count} fontes (retry até {MaxRetryAttempts}x por fonte)...",
            Metrics = new Dictionary<string, object> { ["total"] = sources.Count }
        });

        var seeded = 0;
        var failedIds = new List<string>();
        var total = sources.Count;

        for (var i = 0; i < sources.Count; i++)
        {
            var source = sources[i];
            var success = await UpsertWithRetryAsync(source, ct);
            if (success)
                seeded++;
            else
                failedIds.Add(source.Id);

            var pct = 5 + (int)((i + 1) * 85.0 / total);
            progress.Report(new JobProgress
            {
                PercentComplete = Math.Min(90, pct),
                Message = $"Seed: {seeded}/{total} ok, {failedIds.Count} falhas",
                Metrics = new Dictionary<string, object> { ["seeded"] = seeded, ["failed"] = failedIds.Count, ["total"] = total }
            });
        }

        var status = failedIds.Count == 0 ? "completed" : (seeded > 0 ? "partial" : "failed");
        var errorSummary = failedIds.Count > 0
            ? string.Join(", ", failedIds.Take(50)) + (failedIds.Count > 50 ? $" (+{failedIds.Count - 50} mais)" : null)
            : null;

        var seedRun = new SeedRunEntity
        {
            Id = Guid.NewGuid(),
            JobId = job.Id,
            StartedAt = startedAt,
            CompletedAt = DateTime.UtcNow,
            SourcesTotal = total,
            SourcesSeeded = seeded,
            SourcesFailed = failedIds.Count,
            Status = status,
            ErrorSummary = errorSummary
        };
        _context.SeedRuns.Add(seedRun);
        await _context.SaveChangesAsync(ct);

        progress.Report(new JobProgress
        {
            PercentComplete = 100,
            Message = $"Seed concluído: {seeded} fontes persistidas, {failedIds.Count} falhas. Registro em seed_runs.",
            Metrics = new Dictionary<string, object> { ["sourcesSeeded"] = seeded, ["sourcesFailed"] = failedIds.Count, ["status"] = status }
        });

        _logger.LogInformation(
            "Catalog seed completed: {Seeded}/{Total} sources, {Failed} failures, status={Status}",
            seeded, total, failedIds.Count, status);

        return new JobResult
        {
            Success = true,
            Metadata = new Dictionary<string, object>
            {
                ["sourcesSeeded"] = seeded,
                ["sourcesFailed"] = failedIds.Count,
                ["sourcesTotal"] = total,
                ["status"] = status,
                ["seedRunId"] = seedRun.Id.ToString()
            }
        };
    }

    private string? ResolveSourcesPath()
    {
        var envPath = Environment.GetEnvironmentVariable("GABI_SOURCES_PATH");
        if (!string.IsNullOrEmpty(envPath))
            return envPath;
        return _configuration["GABI_SOURCES_PATH"];
    }

    private async Task<bool> UpsertWithRetryAsync(SourceRegistryEntity source, CancellationToken ct)
    {
        for (var attempt = 1; attempt <= MaxRetryAttempts; attempt++)
        {
            try
            {
                await _sourceRepo.UpsertAsync(source, ct);
                return true;
            }
            catch (Exception ex) when (attempt < MaxRetryAttempts)
            {
                var delay = TimeSpan.FromSeconds(Math.Pow(2, attempt - 1)) + InitialRetryDelay;
                _logger.LogWarning(ex, "Seed upsert attempt {Attempt}/{Max} for {SourceId}, retrying in {Delay}ms",
                    attempt, MaxRetryAttempts, source.Id, delay.TotalMilliseconds);
                await Task.Delay(delay, ct);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Seed upsert failed after {Max} attempts for {SourceId}", MaxRetryAttempts, source.Id);
                return false;
            }
        }
        return false;
    }

    private List<SourceRegistryEntity> LoadSourcesFromYaml(string path)
    {
        var sources = new List<SourceRegistryEntity>();
        try
        {
            var yaml = File.ReadAllText(path);
            var deserializer = new DeserializerBuilder()
                .WithNamingConvention(UnderscoredNamingConvention.Instance)
                .IgnoreUnmatchedProperties()
                .Build();
            var doc = deserializer.Deserialize<SeedYamlDocument>(yaml);
            if (doc?.Sources != null)
            {
                foreach (var (id, sourceDef) in doc.Sources)
                {
                    sources.Add(new SourceRegistryEntity
                    {
                        Id = id,
                        Name = sourceDef.Identity?.Name ?? id,
                        Description = sourceDef.Identity?.Description,
                        Provider = sourceDef.Identity?.Provider ?? "Unknown",
                        Domain = sourceDef.Identity?.Domain,
                        Jurisdiction = sourceDef.Identity?.Jurisdiction,
                        Category = sourceDef.Identity?.Category,
                        DiscoveryStrategy = sourceDef.Discovery?.Strategy ?? "unknown",
                        DiscoveryConfig = JsonSerializer.Serialize(new
                        {
                            url = sourceDef.Discovery?.Config?.Url,
                            template = sourceDef.Discovery?.Config?.Template,
                            parameters = sourceDef.Discovery?.Config?.Parameters
                        }),
                        Enabled = sourceDef.Enabled
                    });
                }
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to parse sources YAML at {Path}", path);
        }
        return sources;
    }

    private class SeedYamlDocument
    {
        [YamlDotNet.Serialization.YamlMember(Alias = "sources")]
        public Dictionary<string, SeedSourceDefinition>? Sources { get; set; }
    }

    private class SeedSourceDefinition
    {
        public bool Enabled { get; set; } = true;
        public SeedIdentityDefinition? Identity { get; set; }
        public SeedDiscoveryDefinition? Discovery { get; set; }
    }

    private class SeedIdentityDefinition
    {
        public string? Name { get; set; }
        public string? Description { get; set; }
        public string? Provider { get; set; }
        public string? Domain { get; set; }
        public string? Jurisdiction { get; set; }
        public string? Category { get; set; }
    }

    private class SeedDiscoveryDefinition
    {
        public string? Strategy { get; set; }
        public SeedDiscoveryConfigDefinition? Config { get; set; }
    }

    private class SeedDiscoveryConfigDefinition
    {
        public string? Url { get; set; }
        public string? Template { get; set; }
        public Dictionary<string, object>? Parameters { get; set; }
    }
}
