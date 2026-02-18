using Gabi.Contracts.Jobs;
using Gabi.Discover;
using Gabi.Postgres;
using Gabi.Postgres.Repositories;
using Gabi.Worker.Jobs;
using Hangfire;
using Hangfire.PostgreSql;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
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

    builder.Services.Configure<HangfireRetryPolicyOptions>(
        builder.Configuration.GetSection(HangfireRetryPolicyOptions.SectionName));

    builder.Services.AddScoped<DlqFilter>();

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

    var host = builder.Build();

    var retryPolicy = host.Services.GetRequiredService<IOptions<HangfireRetryPolicyOptions>>().Value.Normalize();
    GlobalJobFilters.Filters.Remove<AutomaticRetryAttribute>();
    GlobalJobFilters.Filters.Add(new AutomaticRetryAttribute
    {
        Attempts = retryPolicy.Attempts,
        DelaysInSeconds = retryPolicy.DelaysInSeconds,
        LogEvents = true,
        OnAttemptsExceeded = AttemptsExceededAction.Fail
    });

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
