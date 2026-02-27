using System.Diagnostics;
using Gabi.Contracts.Api;
using Gabi.Contracts.Common;
using Gabi.Contracts.Dashboard;
using Gabi.Contracts.Discovery;
using Gabi.Contracts.Jobs;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Microsoft.Extensions.Hosting;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace Gabi.Api.Services;

/// <summary>
/// PostgreSQL-based implementation of ISourceCatalog.
/// Uses database for persistence and job queue for async processing.
/// Implements IHostedService so that YAML initialization runs during ASP.NET Core startup;
/// failures are surfaced immediately rather than swallowed silently.
/// </summary>
public class PostgreSqlSourceCatalogService : ISourceCatalog, IHostedService
{
    private readonly IServiceProvider _serviceProvider;
    private readonly ILogger<PostgreSqlSourceCatalogService> _logger;
    private readonly string _sourcesPath;

    public PostgreSqlSourceCatalogService(
        IServiceProvider serviceProvider,
        ILogger<PostgreSqlSourceCatalogService> logger,
        IConfiguration configuration,
        IHostEnvironment env)
    {
        _serviceProvider = serviceProvider;
        _logger = logger;
        _sourcesPath = ResolveSourcesPath(configuration, env);
    }

    // IHostedService — called by ASP.NET Core during startup before the app starts serving.
    public async Task StartAsync(CancellationToken cancellationToken)
    {
        await InitializeAsync(cancellationToken);
    }

    public Task StopAsync(CancellationToken cancellationToken) => Task.CompletedTask;

    /// <summary>
    /// Initialize source registry from YAML file.
    /// </summary>
    public async Task InitializeAsync(CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var repo = scope.ServiceProvider.GetRequiredService<ISourceRegistryRepository>();

        _logger.LogInformation("Attempting to load sources from: {Path}", _sourcesPath);

        if (!File.Exists(_sourcesPath))
        {
            // Sources file missing is a fatal startup error — throw so the host surfaces it.
            throw new InvalidOperationException(
                $"Sources file NOT FOUND at: {_sourcesPath}. " +
                "Set GABI_SOURCES_PATH or place sources_v2.yaml in the application root.");
        }

        var sources = LoadSourcesFromYaml();
        _logger.LogInformation("Parsed {Count} sources from YAML", sources.Count);

        foreach (var source in sources)
        {
            await repo.UpsertAsync(source, ct);
        }

        _logger.LogInformation("Initialized {Count} sources from YAML", sources.Count);
    }

    public async Task<IReadOnlyList<SourceSummaryDto>> ListSourcesAsync(CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var repo = scope.ServiceProvider.GetRequiredService<ISourceRegistryRepository>();
        var linkRepo = scope.ServiceProvider.GetRequiredService<IDiscoveredLinkRepository>();

        var sources = await repo.GetAllAsync(ct);
        var sourceIds = sources.Select(s => s.Id).ToList();

        var allLinks = await linkRepo.GetBySourcesAsync(sourceIds, ct);
        var linkCountBySource = allLinks
            .GroupBy(l => l.SourceId)
            .ToDictionary(g => g.Key, g => g.Count());

        return sources.Select(s => new SourceSummaryDto(
            s.Id,
            s.Name,
            s.Provider,
            s.DiscoveryStrategy,
            s.Enabled,
            linkCountBySource.GetValueOrDefault(s.Id, 0),
            SourceType: s.DiscoveryStrategy
        )).ToList();
    }

    public async Task<SourceDetailDto?> GetSourceAsync(string sourceId, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var sourceRepo = scope.ServiceProvider.GetRequiredService<ISourceRegistryRepository>();
        var linkRepo = scope.ServiceProvider.GetRequiredService<IDiscoveredLinkRepository>();

        var source = await sourceRepo.GetByIdAsync(sourceId, ct);
        if (source == null)
            return null;

        // Get discovered links from database
        var links = await linkRepo.GetBySourceAsync(sourceId, ct);
        var linkDtos = links.Select(l => new DiscoveredLinkDto(
            l.Url,
            l.DiscoveredAt,
            l.Etag,
            l.Status ?? "pending",
            0 // DocumentCount - will be populated when document tracking is implemented
        )).ToList();

        var lastRefreshed = links.Any() ? links.Max(l => l.DiscoveredAt) : (DateTime?)null;

        return new SourceDetailDto(
            source.Id,
            source.Name,
            source.Description,
            source.Provider,
            source.DiscoveryStrategy,
            source.Enabled,
            linkDtos,
            new SourceMetadataDto(
                source.Domain,
                source.Jurisdiction,
                source.Category,
                lastRefreshed ?? (links.Any() ? links.First().DiscoveredAt : DateTime.MinValue),
                links.Count
            )
        );
    }

    public async Task<RefreshResult> RefreshSourceAsync(string sourceId, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var sourceRepo = scope.ServiceProvider.GetRequiredService<ISourceRegistryRepository>();
        var jobQueue = scope.ServiceProvider.GetRequiredService<IJobQueueRepository>();

        // Verify source exists
        var source = await sourceRepo.GetByIdAsync(sourceId, ct);
        if (source == null)
            throw new KeyNotFoundException($"Source not found: {sourceId}");

        // Check if there's already a running job for this source
        var latestJob = await jobQueue.GetLatestForSourceAsync(sourceId, ct);
        if (latestJob?.Status == JobStatus.Running || latestJob?.Status == JobStatus.Pending)
        {
            _logger.LogInformation("Source {SourceId} already has a running job {JobId}", sourceId, latestJob.Id);
            return new RefreshResult(sourceId, latestJob.ProgressPercent, TimeSpan.Zero);
        }

        // Create and enqueue the job
        var job = new IngestJob
        {
            SourceId = sourceId,
            JobType = "source_discovery",
            DiscoveryConfig = ParseDiscoveryConfig(source.DiscoveryConfig),
            Status = JobStatus.Pending,
            Priority = JobPriority.Normal,
            MaxRetries = 3
        };

        var jobId = await jobQueue.EnqueueAsync(job, ct);

        _logger.LogInformation("Enqueued refresh job {JobId} for source {SourceId}", jobId, sourceId);

        return new RefreshResult(sourceId, 0, TimeSpan.Zero);
    }

    public async Task<JobsResponseDto> ListSyncJobsAsync(CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var jobQueue = scope.ServiceProvider.GetRequiredService<IJobQueueRepository>();

        // Get recent jobs from the queue and map to SyncJobDto
        var stats = await jobQueue.GetStatisticsAsync(ct);
        
        // Return empty response for now - this would need more detailed tracking
        return new JobsResponseDto(
            new List<SyncJobDto>(),
            0,
            new Dictionary<string, long>()
        );
    }

    public async Task<SystemStatsDto> GetSystemStatsAsync(CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var sourceRepo = scope.ServiceProvider.GetRequiredService<ISourceRegistryRepository>();
        var linkRepo = scope.ServiceProvider.GetRequiredService<IDiscoveredLinkRepository>();

        var sources = await sourceRepo.GetAllAsync(ct);
        var sourceIds = sources.Select(s => s.Id).ToList();

        var allLinks = await linkRepo.GetBySourcesAsync(sourceIds, ct);
        var linkCountBySource = allLinks
            .GroupBy(l => l.SourceId)
            .ToDictionary(g => g.Key, g => g.Count());

        var sourceSummaries = sources.Select(s => new SourceSummaryDto(
            s.Id,
            s.Name,
            s.Provider,
            s.DiscoveryStrategy,
            s.Enabled,
            linkCountBySource.GetValueOrDefault(s.Id, 0),
            SourceType: s.DiscoveryStrategy
        )).ToList();

        return new SystemStatsDto(
            sourceSummaries,
            allLinks.Count,
            true, // Assume ES is available for now
            DateTime.UtcNow
        );
    }

    public async Task<IReadOnlyList<PipelineStageDto>> GetPipelineStagesAsync(CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var jobQueue = scope.ServiceProvider.GetRequiredService<IJobQueueRepository>();
        var linkRepo = scope.ServiceProvider.GetRequiredService<IDiscoveredLinkRepository>();

        var stats = await jobQueue.GetStatisticsAsync(ct);
        var totalLinks = await linkRepo.GetTotalCountAsync(ct);
        var total = Math.Max(1, totalLinks);
        var status = stats.RunningCount > 0 ? Status.Active : Status.Idle;
        var lastActivity = DateTime.UtcNow;

        return new List<PipelineStageDto>
        {
            new("harvest", "Harvest", "Download from sources", totalLinks, total, status, lastActivity),
            new("sync", "Sync", "PostgreSQL ingestion", totalLinks, total, status, lastActivity),
            new("ingest", "Ingest", "Document processing", (long)stats.CompletedCount, total, status, lastActivity),
            new("index", "Index", "Elasticsearch indexing", totalLinks, total, status, lastActivity)
        };
    }

    /// <summary>
    /// Get job status for a source (used by frontend polling).
    /// </summary>
    public async Task<Gabi.Contracts.Api.JobStatusDto?> GetJobStatusForSourceAsync(string sourceId, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var jobQueue = scope.ServiceProvider.GetRequiredService<IJobQueueRepository>();
        
        var dto = await jobQueue.GetJobStatusDtoAsync(sourceId, ct);
        if (dto == null) return null;

        return new Gabi.Contracts.Api.JobStatusDto(
            dto.JobId,
            dto.SourceId,
            dto.Status,
            dto.ProgressPercent,
            dto.ProgressMessage,
            dto.LinksDiscovered,
            dto.StartedAt,
            dto.CompletedAt,
            dto.ErrorMessage
        );
    }

    /// <summary>
    /// Obtém detalhes completos de uma fonte.
    /// </summary>
    public async Task<SourceDetailsResponse?> GetSourceDetailsAsync(string sourceId, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var sourceRepo = scope.ServiceProvider.GetRequiredService<ISourceRegistryRepository>();
        var linkRepo = scope.ServiceProvider.GetRequiredService<IDiscoveredLinkRepository>();

        var source = await sourceRepo.GetByIdAsync(sourceId, ct);
        if (source == null) return null;

        var links = await linkRepo.GetBySourceAsync(sourceId, ct);
        var statusCounts = links.GroupBy(l => l.Status)
            .ToDictionary(g => g.Key, g => g.Count());

        return new SourceDetailsResponse
        {
            Id = source.Id,
            Name = source.Name,
            Description = source.Description,
            Provider = source.Provider,
            DiscoveryStrategy = source.DiscoveryStrategy,
            Enabled = source.Enabled,
            TotalLinks = links.Count,
            LastRefresh = source.LastRefresh?.ToString("O"),
            Statistics = new SourceStatisticsDto
            {
                LinksByStatus = statusCounts,
                TotalDocuments = links.Count,
                LastDiscoveryAt = links.Any() ? links.Max(l => l.DiscoveredAt).ToString("O") : null
            }
        };
    }

    /// <summary>
    /// Obtém links descobertos de uma fonte com paginação.
    /// </summary>
    public async Task<PagedResult<DiscoveredLinkDto>> GetLinksAsync(
        string sourceId, 
        int page, 
        int pageSize, 
        string? status, 
        string? sort, 
        CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var linkRepo = scope.ServiceProvider.GetRequiredService<IDiscoveredLinkRepository>();
        var sourceRepo = scope.ServiceProvider.GetRequiredService<ISourceRegistryRepository>();

        // Verify source exists
        var source = await sourceRepo.GetByIdAsync(sourceId, ct);
        if (source == null)
            throw new KeyNotFoundException($"Source not found: {sourceId}");

        var paginated = await linkRepo.GetBySourcePaginatedAsync(sourceId, page, pageSize, status, sort, ct);

        var linkDtos = paginated.Items.Select(l => new DiscoveredLinkDto(
            l.Url,
            l.DiscoveredAt,
            l.Etag,
            l.Status ?? "pending",
            0 // DocumentCount
        )).ToList();

        return new PagedResult<DiscoveredLinkDto>(
            linkDtos,
            paginated.Page,
            paginated.PageSize,
            paginated.TotalItems,
            paginated.TotalPages
        );
    }

    /// <summary>
    /// Load sources from YAML file.
    /// </summary>
    private List<SourceRegistryEntity> LoadSourcesFromYaml()
    {
        var sources = new List<SourceRegistryEntity>();

        if (!File.Exists(_sourcesPath))
        {
            _logger.LogWarning("Sources file not found: {Path}", _sourcesPath);
            return sources;
        }

        try
        {
            var yaml = File.ReadAllText(_sourcesPath);
            var deserializer = new DeserializerBuilder()
                .WithNamingConvention(UnderscoredNamingConvention.Instance)
                .IgnoreUnmatchedProperties()
                .Build();

            var doc = deserializer.Deserialize<YamlDocument>(yaml);

            if (doc?.Sources != null)
            {
                foreach (var (id, sourceDef) in doc.Sources)
                {
                    var source = new SourceRegistryEntity
                    {
                        Id = id,
                        Name = sourceDef.Identity?.Name ?? id,
                        Description = sourceDef.Identity?.Description,
                        Provider = sourceDef.Identity?.Provider ?? "Unknown",
                        Domain = sourceDef.Identity?.Domain,
                        Jurisdiction = sourceDef.Identity?.Jurisdiction,
                        Category = sourceDef.Identity?.Category,
                        DiscoveryStrategy = sourceDef.Discovery?.Strategy ?? "unknown",
                        DiscoveryConfig = System.Text.Json.JsonSerializer.Serialize(BuildDiscoveryConfigObject(sourceDef.Discovery)),
                        Enabled = sourceDef.Enabled
                    };

                    sources.Add(source);
                }
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to parse sources YAML");
        }

        return sources;
    }

    private static DiscoveryConfig ParseDiscoveryConfig(string configJson)
    {
        if (string.IsNullOrWhiteSpace(configJson))
            return new DiscoveryConfig();

        try
        {
            var options = new System.Text.Json.JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true
            };

            return System.Text.Json.JsonSerializer.Deserialize<DiscoveryConfig>(configJson, options)
                ?? new DiscoveryConfig();
        }
        catch
        {
            return new DiscoveryConfig();
        }
    }

    private static string ResolveSourcesPath(IConfiguration config, IHostEnvironment env)
    {
        var envPath = Environment.GetEnvironmentVariable("GABI_SOURCES_PATH");
        if (!string.IsNullOrEmpty(envPath) && File.Exists(envPath))
            return Path.GetFullPath(envPath);

        var configPath = config.GetValue<string>("Gabi:SourcesPath") ?? "sources_v2.yaml";

        var dir = new DirectoryInfo(env.ContentRootPath);
        while (dir != null)
        {
            var candidate = Path.Combine(dir.FullName, configPath);
            if (File.Exists(candidate))
                return candidate;
            dir = dir.Parent;
        }

        return Path.Combine(env.ContentRootPath, configPath);
    }

    // YAML Models (YAML root key "sources" is lowercase; alias ensures match)
    private class YamlDocument
    {
        [YamlDotNet.Serialization.YamlMember(Alias = "sources")]
        public Dictionary<string, SourceDefinition>? Sources { get; set; }
    }

    private class SourceDefinition
    {
        public bool Enabled { get; set; } = true;
        public IdentityDefinition? Identity { get; set; }
        public DiscoveryDefinition? Discovery { get; set; }
    }

    private class IdentityDefinition
    {
        public string? Name { get; set; }
        public string? Description { get; set; }
        public string? Provider { get; set; }
        public string? Domain { get; set; }
        public string? Jurisdiction { get; set; }
        public string? Category { get; set; }
    }

    private class DiscoveryDefinition
    {
        public string? Strategy { get; set; }
        public object? Config { get; set; }
    }

    private static Dictionary<string, object?> BuildDiscoveryConfigObject(DiscoveryDefinition? discovery)
    {
        var strategy = discovery?.Strategy ?? "static_url";
        var map = NormalizeMap(discovery?.Config);
        var result = new Dictionary<string, object?>(StringComparer.OrdinalIgnoreCase)
        {
            ["strategy"] = strategy
        };

        foreach (var (key, value) in map)
            result[key] = value;

        return result;
    }

    private static Dictionary<string, object?> NormalizeMap(object? value)
    {
        var result = new Dictionary<string, object?>(StringComparer.OrdinalIgnoreCase);

        if (value is IDictionary<object, object> objDict)
        {
            foreach (var (k, v) in objDict)
                result[k?.ToString() ?? string.Empty] = NormalizeValue(v);
            return result;
        }

        if (value is IDictionary<string, object> strDict)
        {
            foreach (var (k, v) in strDict)
                result[k] = NormalizeValue(v);
            return result;
        }

        return result;
    }

    private static object? NormalizeValue(object? value)
    {
        if (value is IDictionary<object, object> nestedObj)
        {
            var dict = new Dictionary<string, object?>(StringComparer.OrdinalIgnoreCase);
            foreach (var (k, v) in nestedObj)
                dict[k?.ToString() ?? string.Empty] = NormalizeValue(v);
            return dict;
        }

        if (value is IDictionary<string, object> nestedStr)
        {
            var dict = new Dictionary<string, object?>(StringComparer.OrdinalIgnoreCase);
            foreach (var (k, v) in nestedStr)
                dict[k] = NormalizeValue(v);
            return dict;
        }

        if (value is IList<object> list)
            return list.Select(NormalizeValue).ToList();

        return value;
    }

    private class ParameterDefinition
    {
        public int Start { get; set; }
        public object? End { get; set; }
        public int? Step { get; set; }
    }
}
