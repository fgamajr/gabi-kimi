using Gabi.Discover;

namespace Gabi.Worker.Jobs;

public sealed class SourceCatalogStartupValidationService : IHostedService
{
    private readonly IConfiguration _configuration;
    private readonly SourceCatalogStrategyValidator _validator;
    private readonly ILogger<SourceCatalogStartupValidationService> _logger;

    public SourceCatalogStartupValidationService(
        IConfiguration configuration,
        SourceCatalogStrategyValidator validator,
        ILogger<SourceCatalogStartupValidationService> logger)
    {
        _configuration = configuration;
        _validator = validator;
        _logger = logger;
    }

    public Task StopAsync(CancellationToken cancellationToken) => Task.CompletedTask;

    public Task StartAsync(CancellationToken cancellationToken)
    {
        var path = ResolveSourcesPath();
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            _logger.LogWarning(
                "Startup source-strategy validation skipped: sources file not found (path={Path})",
                path ?? "(null)");
            return Task.CompletedTask;
        }

        var yaml = File.ReadAllText(path);
        var unsupported = _validator.FindUnsupportedEnabledStrategies(yaml);
        if (unsupported.Count == 0)
        {
            _logger.LogInformation("Startup source-strategy validation passed for {Path}", path);
            return Task.CompletedTask;
        }

        var details = string.Join(", ", unsupported.Select(x => $"{x.SourceId}:{x.Strategy}"));
        var supported = string.Join(", ", _validator.SupportedStrategies.OrderBy(x => x));
        throw new InvalidOperationException(
            "Unsupported enabled discovery strategies in sources catalog. " +
            "Implement adapters or disable these sources. " +
            $"Entries: {details}. Supported strategies: [{supported}]");
    }

    private string? ResolveSourcesPath()
    {
        var envPath = Environment.GetEnvironmentVariable("GABI_SOURCES_PATH");
        if (string.IsNullOrWhiteSpace(envPath))
            envPath = _configuration["GABI_SOURCES_PATH"];
        if (string.IsNullOrWhiteSpace(envPath))
            envPath = _configuration["Gabi:SourcesPath"];
        if (string.IsNullOrWhiteSpace(envPath))
            return null;

        envPath = envPath.Trim();
        if (Path.IsPathRooted(envPath))
            return envPath;

        var fromBaseDir = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", envPath));
        if (File.Exists(fromBaseDir))
            return fromBaseDir;

        var fromCwd = Path.GetFullPath(Path.Combine(Directory.GetCurrentDirectory(), envPath));
        if (File.Exists(fromCwd))
            return fromCwd;

        return envPath;
    }
}
