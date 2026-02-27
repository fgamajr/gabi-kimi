using Gabi.Contracts.Chunk;
using Gabi.Contracts.Embed;
using Gabi.Contracts.Fetch;
using Gabi.Contracts.Index;
using Gabi.Contracts.Ingest;
using Gabi.Contracts.Jobs;
using Gabi.Discover;
using Gabi.Ingest;
using Gabi.Postgres;
using Gabi.Postgres.Repositories;
using Gabi.Worker.Jobs;
using Hangfire;
using Hangfire.PostgreSql;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace Gabi.ReliabilityLab.Pipeline.Infrastructure;

/// <summary>
/// Hosts the Gabi Worker in-process with Hangfire job processors for ReliabilityLab scenarios.
/// Uses HashEmbedder and LocalDocumentIndexer as dev fallbacks — no TEI or Elasticsearch required.
/// The API factory enqueues Hangfire jobs to shared PostgreSQL; this host dequeues and executes them.
/// </summary>
public sealed class LabWorkerHost : IAsyncDisposable
{
    private readonly IHost _host;

    private LabWorkerHost(IHost host) => _host = host;

    public static LabWorkerHost Create(string connectionString)
    {
        var builder = Host.CreateApplicationBuilder(new HostApplicationBuilderSettings
        {
            EnvironmentName = "Development"
        });

        builder.Services.AddLogging(b => b.AddConsole().SetMinimumLevel(LogLevel.Warning));

        builder.Services.AddDbContext<GabiDbContext>(opts => opts.UseNpgsql(connectionString));
        builder.Services.AddHttpClient();

        builder.Services.AddHangfire(config => config
            .SetDataCompatibilityLevel(CompatibilityLevel.Version_180)
            .UseSimpleAssemblyNameTypeSerializer()
            .UseRecommendedSerializerSettings()
            .UsePostgreSqlStorage(connectionString, new PostgreSqlStorageOptions
            {
                QueuePollInterval = TimeSpan.FromSeconds(2),
                InvisibilityTimeout = TimeSpan.FromMinutes(5),
                UseSlidingInvisibilityTimeout = true
            }));

        // Use unique server names so parallel lab runs don't collide
        builder.Services.AddHangfireServer(options =>
        {
            options.ServerName = $"lab-pipeline-{Guid.NewGuid():N}";
            options.WorkerCount = 1;
            options.Queues = ["seed", "discovery", "fetch", "ingest", "default"];
        });
        builder.Services.AddHangfireServer(options =>
        {
            options.ServerName = $"lab-embed-{Guid.NewGuid():N}";
            options.WorkerCount = 2;
            options.Queues = ["embed"];
        });

        builder.Services.AddScoped<HangfireJobQueueRepository>();
        builder.Services.AddScoped<IJobQueueRepository>(sp => sp.GetRequiredService<HangfireJobQueueRepository>());
        builder.Services.AddScoped<ISourceRegistryRepository, SourceRegistryRepository>();
        builder.Services.AddScoped<IDiscoveredLinkRepository, DiscoveredLinkRepository>();
        builder.Services.AddScoped<IFetchItemRepository, FetchItemRepository>();
        builder.Services.AddScoped<IDocumentRepository, DocumentRepository>();

        builder.Services.AddSingleton<Gabi.Worker.Security.FetchUrlValidator>();
        builder.Services.AddSingleton<IFetchUrlValidator>(sp =>
            sp.GetRequiredService<Gabi.Worker.Security.FetchUrlValidator>());

        builder.Services.AddSingleton<IDiscoveryAdapter, StaticUrlDiscoveryAdapter>();
        builder.Services.AddSingleton<IDiscoveryAdapter, UrlPatternDiscoveryAdapter>();
        builder.Services.AddSingleton<DiscoveryAdapterRegistry>();
        builder.Services.AddSingleton<SourceCatalogStrategyValidator>();
        builder.Services.AddSingleton<DiscoveryEngine>();
        // SourceCatalogStartupValidationService is intentionally NOT registered
        // to avoid blocking startup before the catalog is seeded

        builder.Services.AddSingleton<ICanonicalDocumentNormalizer, CanonicalDocumentNormalizer>();
        builder.Services.AddSingleton<IChunker, FixedSizeChunker>();

        // Dev fallbacks: no TEI embedder or Elasticsearch needed in ReliabilityLab
        builder.Services.AddSingleton<IEmbedder, HashEmbedder>();
        builder.Services.AddSingleton<IDocumentIndexer, LocalDocumentIndexer>();
        builder.Services.AddSingleton<IMediaTextProjector, MediaTextProjector>();

        builder.Services.AddScoped<IGabiJobRunner, GabiJobRunner>();
        builder.Services.AddScoped<IJobExecutor, CatalogSeedJobExecutor>();
        builder.Services.AddScoped<IJobExecutor, SourceDiscoveryJobExecutor>();
        builder.Services.AddScoped<IJobExecutor, FetchJobExecutor>();
        builder.Services.AddScoped<IJobExecutor, IngestJobExecutor>();
        builder.Services.AddScoped<IJobExecutor, EmbedAndIndexJobExecutor>();

        return new LabWorkerHost(builder.Build());
    }

    public async Task StartAsync(CancellationToken ct = default) =>
        await _host.StartAsync(ct).ConfigureAwait(false);

    public async ValueTask DisposeAsync()
    {
        await _host.StopAsync(TimeSpan.FromSeconds(10)).ConfigureAwait(false);
        _host.Dispose();
    }
}
