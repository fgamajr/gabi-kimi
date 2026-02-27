using Elastic.Clients.Elasticsearch;
using Gabi.Contracts.Jobs;
using Gabi.Contracts.Ingest;
using Gabi.Contracts.Chunk;
using Gabi.Contracts.Embed;
using Gabi.Contracts.Index;
using Gabi.Contracts.Observability;
using Gabi.Contracts.Workflow;
using Gabi.Discover;
using Gabi.Ingest;
using Gabi.Postgres;
using Gabi.Postgres.Repositories;
using Gabi.Worker.Jobs;
using Gabi.Worker.Projection;
using Gabi.Worker.Temporal;
using Hangfire;
using Hangfire.PostgreSql;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using OpenTelemetry.Instrumentation.EntityFrameworkCore;
using OpenTelemetry.Instrumentation.Runtime;
using OpenTelemetry.Metrics;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;
using Serilog;
using Serilog.Formatting.Compact;

var isProduction = Environment.GetEnvironmentVariable("DOTNET_ENVIRONMENT") == "Production";

// Serilog: JSON no console para observabilidade (Fly logs, debugging)
var loggerConfig = new LoggerConfiguration()
    .ReadFrom.Configuration(new ConfigurationBuilder()
        .SetBasePath(Directory.GetCurrentDirectory())
        .AddJsonFile("appsettings.json", optional: false)
        .AddJsonFile($"appsettings.{Environment.GetEnvironmentVariable("DOTNET_ENVIRONMENT") ?? "Production"}.json", optional: true)
        .AddEnvironmentVariables()
        .Build())
    .Enrich.FromLogContext()
    .Enrich.WithProperty("Application", "Gabi.Worker");

if (isProduction)
    loggerConfig.WriteTo.Console(new CompactJsonFormatter());
else
    loggerConfig.WriteTo.Console(outputTemplate: "[{Timestamp:HH:mm:ss} {Level:u3}] {Message:lj} {Properties:j}{NewLine}{Exception}");

Log.Logger = loggerConfig.CreateLogger();

try
{
    Log.Information("Starting Gabi.Worker...");

    var builder = Host.CreateApplicationBuilder(args);
    builder.Services.AddSerilog(Log.Logger);

    var connectionString = builder.Configuration.GetConnectionString("Default");
    if (string.IsNullOrWhiteSpace(connectionString))
        throw new InvalidOperationException("ConnectionStrings:Default is required");

    if (!builder.Environment.IsDevelopment())
    {
        var embeddingsUrl = builder.Configuration["GABI_EMBEDDINGS_URL"];
        if (string.IsNullOrWhiteSpace(embeddingsUrl))
            throw new InvalidOperationException(
                "GABI_EMBEDDINGS_URL is required in non-development. Configure via environment variable GABI_EMBEDDINGS_URL.");
    }

    builder.Services.AddDbContext<GabiDbContext>(options =>
        options.UseNpgsql(connectionString));
    builder.Services.AddHttpClient();

    var otlpEndpoint = builder.Configuration["OTEL_EXPORTER_OTLP_ENDPOINT"] ?? "http://localhost:4317";
    var otlpHeaders = builder.Configuration["OTEL_EXPORTER_OTLP_HEADERS"];
    builder.Services.AddOpenTelemetry()
        .ConfigureResource(resource => resource.AddService(
            serviceName: "gabi-worker",
            serviceVersion: typeof(Program).Assembly.GetName().Version?.ToString() ?? "unknown"))
        .WithTracing(tracing => tracing
            .AddEntityFrameworkCoreInstrumentation()
            .AddHttpClientInstrumentation()
            .AddSource(PipelineTelemetry.ActivitySourceName)
            .AddOtlpExporter(options =>
            {
                options.Endpoint = new Uri(otlpEndpoint);
                if (!string.IsNullOrWhiteSpace(otlpHeaders))
                    options.Headers = otlpHeaders;
            }))
        .WithMetrics(metrics => metrics
            .AddRuntimeInstrumentation()
            .AddMeter(PipelineTelemetry.MeterName)
            .AddOtlpExporter(options =>
            {
                options.Endpoint = new Uri(otlpEndpoint);
                if (!string.IsNullOrWhiteSpace(otlpHeaders))
                    options.Headers = otlpHeaders;
            }));

    builder.Services.Configure<HangfireRetryPolicyOptions>(
        builder.Configuration.GetSection(HangfireRetryPolicyOptions.SectionName));

    builder.Services.AddSingleton<DlqFilter>();

    builder.Services.AddHangfire(config =>
    {
        config
            .SetDataCompatibilityLevel(CompatibilityLevel.Version_180)
            .UseSimpleAssemblyNameTypeSerializer()
            .UseRecommendedSerializerSettings()
            .UsePostgreSqlStorage(
                connectionString,
                new PostgreSqlStorageOptions
                {
                    QueuePollInterval = TimeSpan.FromSeconds(5),
                    InvisibilityTimeout = TimeSpan.FromMinutes(10),
                    UseSlidingInvisibilityTimeout = true
                });
    });

    // DlqFilter will be registered via GlobalJobFilters after host is built
    // pipeline-stages: 1 worker; controls pipeline stage ordering and avoids embed fan-out tarpitting other stages
    builder.Services.AddHangfireServer(options =>
    {
        options.ServerName = "pipeline-stages";
        options.WorkerCount = 1;
        options.Queues = new[] { "seed", "discovery", "fetch", "ingest", "default" };
    });
    // embed-pool: separate concurrency, scales independently of pipeline stages
    builder.Services.AddHangfireServer(options =>
    {
        options.ServerName = "embed-pool";
        options.WorkerCount = builder.Configuration.GetValue<int>("WorkerPool:EmbedWorkerCount", 3);
        options.Queues = new[] { "embed" };
    });

    builder.Services.AddScoped<HangfireJobQueueRepository>();
    builder.Services.AddScoped<IJobQueueRepository>(sp => sp.GetRequiredService<HangfireJobQueueRepository>());
    builder.Services.AddScoped<ISourceRegistryRepository, SourceRegistryRepository>();
    builder.Services.AddScoped<IDiscoveredLinkRepository, DiscoveredLinkRepository>();
    builder.Services.AddScoped<IFetchItemRepository, FetchItemRepository>();
    builder.Services.AddScoped<IDocumentRepository, DocumentRepository>();

    builder.Services.AddSingleton<Gabi.Worker.Security.FetchUrlValidator>();
    builder.Services.AddSingleton<Gabi.Contracts.Fetch.IFetchUrlValidator>(sp => sp.GetRequiredService<Gabi.Worker.Security.FetchUrlValidator>());

    builder.Services.AddSingleton<IDiscoveryAdapter, StaticUrlDiscoveryAdapter>();
    builder.Services.AddSingleton<IDiscoveryAdapter, UrlPatternDiscoveryAdapter>();
    var enableWebCrawlAdapter = builder.Configuration.GetValue<bool>("Gabi:DiscoveryAdapters:EnableWebCrawl");
    var enableApiPaginationAdapter = builder.Configuration.GetValue<bool>("Gabi:DiscoveryAdapters:EnableApiPagination");
    if (enableWebCrawlAdapter)
        builder.Services.AddSingleton<IDiscoveryAdapter, WebCrawlDiscoveryAdapter>();
    if (enableApiPaginationAdapter)
        builder.Services.AddSingleton<IDiscoveryAdapter, ApiPaginationDiscoveryAdapter>();
    builder.Services.AddSingleton<DiscoveryAdapterRegistry>();
    builder.Services.AddSingleton<SourceCatalogStrategyValidator>();
    builder.Services.AddSingleton<DiscoveryEngine>();
    builder.Services.AddHostedService<SourceCatalogStartupValidationService>();
    builder.Services.AddSingleton<ICanonicalDocumentNormalizer, CanonicalDocumentNormalizer>();
    builder.Services.AddSingleton<IChunker, FixedSizeChunker>();

    var teiUrl = builder.Configuration["GABI_EMBEDDINGS_URL"];
    if (!string.IsNullOrWhiteSpace(teiUrl))
    {
        var baseUrl = teiUrl.TrimEnd('/') + "/";
        builder.Services.AddHttpClient("TeiEmbedder", client =>
        {
            client.BaseAddress = new Uri(baseUrl);
            client.Timeout = TimeSpan.FromSeconds(30);
        });
        builder.Services.AddSingleton<TeiEmbedder>(sp => new TeiEmbedder(
            sp.GetRequiredService<IHttpClientFactory>().CreateClient("TeiEmbedder"),
            sp.GetRequiredService<ILogger<TeiEmbedder>>()));
        builder.Services.AddSingleton<IEmbedder>(sp => sp.GetRequiredService<TeiEmbedder>());
    }
    else
    {
        Log.Warning("GABI_EMBEDDINGS_URL not set; using HashEmbedder (dev fallback)");
        builder.Services.AddSingleton<IEmbedder, HashEmbedder>();
    }

    var elasticsearchUrl = builder.Configuration["Gabi:ElasticsearchUrl"]
        ?? builder.Configuration.GetConnectionString("Elasticsearch");
    if (!string.IsNullOrWhiteSpace(elasticsearchUrl))
    {
        var settings = new ElasticsearchClientSettings(new Uri(elasticsearchUrl));
        builder.Services.AddSingleton(new ElasticsearchClient(settings));
        builder.Services.AddSingleton<ElasticsearchIndexSetup>(sp => new ElasticsearchIndexSetup(
            sp.GetRequiredService<ElasticsearchClient>(),
            sp.GetRequiredService<ILogger<ElasticsearchIndexSetup>>(),
            indexName: null));
        builder.Services.AddHostedService<ElasticsearchIndexSetupHostedService>();
        builder.Services.AddSingleton<IDocumentIndexer>(sp => new ElasticsearchDocumentIndexer(
            sp.GetRequiredService<ElasticsearchClient>(),
            sp.GetRequiredService<ILogger<ElasticsearchDocumentIndexer>>(),
            indexName: null));
    }
    else
    {
        Log.Warning("Elasticsearch URL not set; using LocalDocumentIndexer (dev fallback)");
        builder.Services.AddSingleton<IDocumentIndexer, LocalDocumentIndexer>();
    }

    builder.Services.AddSingleton<IMediaTextProjector, MediaTextProjector>();

    builder.Services.AddScoped<IGabiJobRunner, GabiJobRunner>();
    builder.Services.AddScoped<IJobExecutor, CatalogSeedJobExecutor>();
    builder.Services.AddScoped<IJobExecutor, SourceDiscoveryJobExecutor>();
    builder.Services.AddScoped<IJobExecutor, FetchJobExecutor>();
    builder.Services.AddScoped<IJobExecutor, IngestJobExecutor>();
    builder.Services.AddScoped<IJobExecutor, EmbedAndIndexJobExecutor>();
    builder.Services.AddScoped<IJobExecutor, MediaTranscribeJobExecutor>();
    builder.Services.AddScoped<IJobExecutor, DriftAuditorJobExecutor>();

    // Phase A: Workflow event repository (best-effort observability)
    builder.Services.AddScoped<IWorkflowEventRepository, WorkflowEventRepository>();

    // Phase B: Temporal (globally gated; per-source routing in HangfireJobQueueRepository)
    builder.Services.AddSingleton<ITemporalHealthCheck, TemporalHealthCheck>();
    builder.Services.AddHostedService<TemporalWorkerHostedService>();

    // Phase C: WAL projection (globally gated; WalProjectionBootstrapService must run first)
    builder.Services.AddHostedService<WalProjectionBootstrapService>();
    builder.Services.AddHostedService<LogicalReplicationProjectionWorker>();
    builder.Services.AddSingleton<ProjectionLagMonitor>();

    // DriftAuditor recurring job (registered after host build via RecurringJob API)
    var host = builder.Build();

    var retryPolicy = host.Services.GetRequiredService<IOptions<HangfireRetryPolicyOptions>>().Value.Normalize();
    GlobalJobFilters.Filters.Remove<AutomaticRetryAttribute>();

    // Register DlqFilter as global Hangfire filter with DI
    var dlqFilter = host.Services.GetRequiredService<DlqFilter>();
    GlobalJobFilters.Filters.Add(dlqFilter);

    Log.Information(
        "Hangfire retry policy configured: attempts={Attempts}, delays=[{Delays}]",
        retryPolicy.Attempts,
        string.Join(",", retryPolicy.DelaysInSeconds));

    // Register drift-audit as hourly recurring Hangfire job
    RecurringJob.AddOrUpdate<IGabiJobRunner>(
        "drift-audit",
        r => r.RunAsync(Guid.NewGuid(), "drift_audit", "*", "{}", CancellationToken.None),
        "0 * * * *");

    host.Run();
}
finally
{
    Log.Information("Stopping Gabi.Worker...");
    await Log.CloseAndFlushAsync();
}
