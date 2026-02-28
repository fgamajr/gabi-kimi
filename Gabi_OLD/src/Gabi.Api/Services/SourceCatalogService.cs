using System.Diagnostics;
using Gabi.Contracts.Api;
using Gabi.Contracts.Dashboard;
using Gabi.Contracts.Discovery;
using Gabi.Discover;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;
using YamlDotNet.Core;

namespace Gabi.Api.Services;

/// <summary>
/// Serviço de catálogo de fontes que lê sources_v2.yaml e executa discovery.
/// </summary>
public class SourceCatalogService : ISourceCatalog
{
    private readonly ILogger<SourceCatalogService> _logger;
    private readonly string _sourcesPath;
    private readonly DiscoveryEngine _discoveryEngine;
    
    // Cache em memória (v1 - upgradeable para Postgres depois)
    private readonly Dictionary<string, SourceDefinition> _sources = new();
    private readonly Dictionary<string, List<DiscoveredLinkDto>> _discoveredLinks = new();
    private readonly Dictionary<string, DateTime> _lastRefreshed = new();

    public SourceCatalogService(ILogger<SourceCatalogService> logger, string contentRootPath)
    {
        _logger = logger;
        _sourcesPath = ResolveSourcesPath(contentRootPath);
        _discoveryEngine = new DiscoveryEngine();
        
        LoadSources();
    }

    public Task InitializeAsync(CancellationToken ct = default)
    {
        LoadSources();
        return Task.CompletedTask;
    }

    /// <summary>
    /// Resolves sources_v2.yaml path: ENV var → walk up from content root → fallback.
    /// </summary>
    private static string ResolveSourcesPath(string contentRoot)
    {
        // 1. Explicit env var (Docker, Fly.io, CI)
        var envPath = Environment.GetEnvironmentVariable("GABI_SOURCES_PATH");
        if (!string.IsNullOrEmpty(envPath) && File.Exists(envPath))
            return Path.GetFullPath(envPath);

        // 2. Walk up from ContentRoot to find sources_v2.yaml (local dev)
        const string fileName = "sources_v2.yaml";
        var dir = new DirectoryInfo(contentRoot);
        while (dir != null)
        {
            var candidate = Path.Combine(dir.FullName, fileName);
            if (File.Exists(candidate))
                return candidate;
            dir = dir.Parent;
        }

        // 3. Fallback — ContentRoot (will log warning if missing)
        return Path.Combine(contentRoot, fileName);
    }

    private void LoadSources()
    {
        if (!File.Exists(_sourcesPath))
        {
            _logger.LogWarning("Sources file not found: {Path}", _sourcesPath);
            return;
        }

        var yaml = File.ReadAllText(_sourcesPath);
        var deserializer = new DeserializerBuilder()
            .WithNamingConvention(UnderscoredNamingConvention.Instance)
            .IgnoreUnmatchedProperties()  // Ignore apiVersion, kind, defaults, etc.
            .Build();

        try
        {
            var doc = deserializer.Deserialize<YamlDocument>(yaml);
            
            if (doc?.Sources != null)
            {
                foreach (var (id, source) in doc.Sources)
                {
                    source.Id = id;
                    _sources[id] = source;
                    _discoveredLinks[id] = new List<DiscoveredLinkDto>();
                    _lastRefreshed[id] = source.LastRefreshed ?? DateTime.MinValue;
                }
            }
            
            _logger.LogInformation("Loaded {Count} sources from {Path}", _sources.Count, _sourcesPath);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to parse sources file");
        }
    }

    public Task<IReadOnlyList<SourceSummaryDto>> ListSourcesAsync(CancellationToken ct = default)
    {
        var summaries = _sources.Values.Select(s => new SourceSummaryDto(
            s.Id!,
            s.Identity?.Name ?? s.Id!,
            s.Identity?.Provider ?? "Unknown",
            s.Discovery?.Strategy ?? "unknown",
            s.Enabled,
            _discoveredLinks.GetValueOrDefault(s.Id!)?.Count ?? 0,
            s.Discovery?.Strategy // Usando Strategy como SourceType para alinhar com 'csv_http' etc.
        )).ToList();

        return Task.FromResult<IReadOnlyList<SourceSummaryDto>>(summaries);
    }

    public Task<SourceDetailDto?> GetSourceAsync(string sourceId, CancellationToken ct = default)
    {
        if (!_sources.TryGetValue(sourceId, out var source))
            return Task.FromResult<SourceDetailDto?>(null);

        var links = _discoveredLinks.GetValueOrDefault(sourceId) ?? new List<DiscoveredLinkDto>();
        var strategy = source.Discovery?.Strategy?.ToLowerInvariant();
        var discoveryNotice = (strategy == "web_crawl" || strategy == "api_pagination") && links.Count == 0
            ? "Discovery para este tipo de fonte (crawler/API) ainda não implementado. Será listado quando o adaptador estiver disponível."
            : null;

        var detail = new SourceDetailDto(
            source.Id!,
            source.Identity?.Name ?? source.Id!,
            source.Identity?.Description,
            source.Identity?.Provider ?? "Unknown",
            source.Discovery?.Strategy ?? "unknown",
            source.Enabled,
            links,
            new SourceMetadataDto(
                source.Identity?.Domain,
                source.Identity?.Jurisdiction,
                source.Identity?.Category,
                _lastRefreshed.GetValueOrDefault(sourceId),
                links.Count,
                DiscoveryNotice: discoveryNotice
            )
        );

        return Task.FromResult<SourceDetailDto?>(detail);
    }

    public async Task<RefreshResult> RefreshSourceAsync(string sourceId, CancellationToken ct = default)
    {
        if (!_sources.TryGetValue(sourceId, out var source))
            throw new KeyNotFoundException($"Source not found: {sourceId}");

        _logger.LogInformation("Starting refresh for source: {SourceId}", sourceId);
        var stopwatch = Stopwatch.StartNew();

        var config = ParseDiscoveryConfig(source.Discovery);
        var links = new List<DiscoveredLinkDto>();

        await foreach (var discovered in _discoveryEngine.DiscoverAsync(sourceId, config, ct))
        {
            links.Add(new DiscoveredLinkDto(
                discovered.Url,
                discovered.DiscoveredAt,
                discovered.Etag
            ));
        }

        _discoveredLinks[sourceId] = links;
        _lastRefreshed[sourceId] = DateTime.UtcNow;
        stopwatch.Stop();

        _logger.LogInformation("Refresh completed for {SourceId}: {Count} links discovered in {Duration}ms",
            sourceId, links.Count, stopwatch.ElapsedMilliseconds);

        return new RefreshResult(sourceId, links.Count, stopwatch.Elapsed);
    }

    public async Task<JobsResponseDto> ListSyncJobsAsync(CancellationToken ct = default)
    {
        // Mock data alinhado ao JobsResponse do reference
        var jobs = new List<SyncJobDto>();
        
        foreach (var sourceId in _sources.Keys.Take(1))
        {
            for (int i = 0; i < 8; i++)
            {
                jobs.Add(new SyncJobDto(
                    sourceId,
                    (2024 - i).ToString(),
                    "synced",
                    DateTime.UtcNow.AddMinutes(-i * 15)
                ));
            }
        }

        var totalElasticDocs = _discoveredLinks.Values.Sum(v => v.Count);
        var indexes = _sources.Keys.ToDictionary(id => $"gabi_{id}", id => (long)(_discoveredLinks.GetValueOrDefault(id)?.Count ?? 0));

        return await Task.FromResult(new JobsResponseDto(jobs, totalElasticDocs, indexes));
    }

    public async Task<SystemStatsDto> GetSystemStatsAsync(CancellationToken ct = default)
    {
        var sources = await ListSourcesAsync(ct);
        var totalDocs = sources.Sum(s => s.DocumentCount ?? 0);
        
        return new SystemStatsDto(
            sources,
            totalDocs,
            true, // Elasticsearch mock status
            DateTime.UtcNow
        );
    }

    public async Task<IReadOnlyList<PipelineStageDto>> GetPipelineStagesAsync(CancellationToken ct = default)
    {
        var sources = await ListSourcesAsync(ct);
        var totalLinks = sources.Sum(s => s.DocumentCount ?? 0);

        var stages = new List<PipelineStageDto>
        {
            new("harvest", "Harvest", "Download from sources", totalLinks, totalLinks, "active", DateTime.UtcNow),
            new("sync", "Sync", "PostgreSQL ingestion", totalLinks, totalLinks, "active", DateTime.UtcNow.AddMinutes(-1)),
            new("ingest", "Ingest", "Document processing", (long)(totalLinks * 0.9), totalLinks, "active", DateTime.UtcNow.AddMinutes(-2)),
            new("index", "Index", "Elasticsearch indexing", (long)(totalLinks * 0.8), totalLinks, "active", DateTime.UtcNow)
        };

        return await Task.FromResult(stages);
    }

    public Task<JobStatusDto?> GetJobStatusForSourceAsync(string sourceId, CancellationToken ct = default)
    {
        // In-memory service doesn't track jobs - return null
        return Task.FromResult<JobStatusDto?>(null);
    }

    public Task<SourceDetailsResponse?> GetSourceDetailsAsync(string sourceId, CancellationToken ct = default)
    {
        // In-memory implementation - simplified
        if (!_sources.TryGetValue(sourceId, out var source))
            return Task.FromResult<SourceDetailsResponse?>(null);

        var links = _discoveredLinks.GetValueOrDefault(sourceId) ?? new List<DiscoveredLinkDto>();
        
        return Task.FromResult<SourceDetailsResponse?>(new SourceDetailsResponse
        {
            Id = source.Id!,
            Name = source.Identity?.Name ?? source.Id!,
            Description = source.Identity?.Description,
            Provider = source.Identity?.Provider ?? "Unknown",
            DiscoveryStrategy = source.Discovery?.Strategy ?? "unknown",
            Enabled = source.Enabled,
            TotalLinks = links.Count,
            LastRefresh = _lastRefreshed.GetValueOrDefault(sourceId).ToString("O"),
            Statistics = new SourceStatisticsDto
            {
                LinksByStatus = new Dictionary<string, int> { ["pending"] = links.Count },
                TotalDocuments = links.Count,
                LastDiscoveryAt = links.Any() ? links.Max(l => l.DiscoveredAt).ToString("O") : null
            }
        });
    }

    public Task<PagedResult<DiscoveredLinkDto>> GetLinksAsync(string sourceId, int page, int pageSize, string? status, string? sort, CancellationToken ct = default)
    {
        if (!_sources.TryGetValue(sourceId, out _))
            throw new KeyNotFoundException($"Source not found: {sourceId}");

        var allLinks = _discoveredLinks.GetValueOrDefault(sourceId) ?? new List<DiscoveredLinkDto>();
        
        // Simple pagination
        var totalItems = allLinks.Count;
        var totalPages = Math.Max(1, (int)Math.Ceiling(totalItems / (double)pageSize));
        var pagedLinks = allLinks
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .ToList();

        return Task.FromResult(new PagedResult<DiscoveredLinkDto>(
            pagedLinks,
            page,
            pageSize,
            totalItems,
            totalPages
        ));
    }

    private static DiscoveryConfig ParseDiscoveryConfig(DiscoveryDefinition? discovery)
    {
        if (discovery == null)
            return new DiscoveryConfig();

        var strategy = discovery.Strategy?.ToLowerInvariant() switch
        {
            "static_url" => DiscoveryMode.StaticUrl,
            "url_pattern" => DiscoveryMode.UrlPattern,
            _ => DiscoveryMode.StaticUrl
        };

        var config = new DiscoveryConfig
        {
            Mode = strategy,
            Url = discovery.Config?.Url,
            UrlTemplate = discovery.Config?.Template
        };

        // Parse parameters for url_pattern
        if (strategy == DiscoveryMode.UrlPattern && discovery.Config?.Parameters != null)
        {
            var parameters = new Dictionary<string, object>();
            foreach (var (key, param) in discovery.Config.Parameters)
            {
                if (param != null)
                {
                    // Handle "current" keyword for year
                    var endValue = param.End?.ToString() == "current" 
                        ? DateTime.UtcNow.Year 
                        : param.End;
                        
                    parameters[key] = new { Start = param.Start, End = endValue, Step = param.Step ?? 1 };
                }
            }
            config.Params = parameters;
        }

        return config;
    }

    // YAML Models
    private class YamlDocument
    {
        public Dictionary<string, SourceDefinition>? Sources { get; set; }
    }

    private class SourceDefinition
    {
        public string? Id { get; set; }
        public bool Enabled { get; set; } = true;
        public DateTime? LastRefreshed { get; set; }
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
        public DiscoveryConfigDefinition? Config { get; set; }
    }

    private class DiscoveryConfigDefinition
    {
        public string? Url { get; set; }
        public string? Template { get; set; }
        public Dictionary<string, ParameterDefinition>? Parameters { get; set; }
    }

    private class ParameterDefinition
    {
        public int Start { get; set; }
        public object? End { get; set; }
        public int? Step { get; set; }
    }
}
