using Gabi.Contracts.Jobs;
using Gabi.Contracts.Observability;
using Gabi.Discover;
using Gabi.Postgres;
using Gabi.Postgres.Repositories;
using Gabi.Worker.Jobs;
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
    builder.Services.AddHangfireServer(options =>
    {
        options.WorkerCount = builder.Configuration.GetValue<int>("WorkerPool:WorkerCount", 2);
        options.Queues = new[] { "seed", "discovery", "fetch", "ingest", "default" };
    });

    builder.Services.AddScoped<ISourceRegistryRepository, SourceRegistryRepository>();
    builder.Services.AddScoped<IDiscoveredLinkRepository, DiscoveredLinkRepository>();
    builder.Services.AddScoped<IFetchItemRepository, FetchItemRepository>();

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

    builder.Services.AddScoped<IGabiJobRunner, GabiJobRunner>();
    builder.Services.AddScoped<IJobExecutor, CatalogSeedJobExecutor>();
    builder.Services.AddScoped<IJobExecutor, SourceSyncJobExecutor>();
    builder.Services.AddScoped<IJobExecutor, SourceDiscoveryJobExecutor>();
    builder.Services.AddScoped<IJobExecutor, FetchJobExecutor>();
    builder.Services.AddScoped<IJobExecutor, IngestJobExecutor>();
    builder.Services.AddScoped<IJobExecutor, MediaTranscribeJobExecutor>();

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

    host.Run();
}
finally
{
    Log.Information("Stopping Gabi.Worker...");
    await Log.CloseAndFlushAsync();
}
