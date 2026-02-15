using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Repositories;
using Gabi.Worker.Jobs;
using Hangfire;
using Hangfire.PostgreSql;
using Microsoft.EntityFrameworkCore;

var builder = Host.CreateApplicationBuilder(args);

var connectionString = builder.Configuration.GetConnectionString("Default");
if (string.IsNullOrWhiteSpace(connectionString))
    throw new InvalidOperationException("ConnectionStrings:Default is required");

builder.Services.AddDbContext<GabiDbContext>(options =>
    options.UseNpgsql(connectionString));

builder.Services.AddHangfire(config => config
    .SetDataCompatibilityLevel(CompatibilityLevel.Version_180)
    .UseSimpleAssemblyNameTypeSerializer()
    .UseRecommendedSerializerSettings()
    .UsePostgreSqlStorage(o => o.UseNpgsqlConnection(connectionString)));
builder.Services.AddHangfireServer(options =>
{
    options.WorkerCount = builder.Configuration.GetValue<int>("WorkerPool:WorkerCount", 2);
    options.Queues = new[] { "seed", "discovery", "fetch", "ingest", "default" };
});

builder.Services.AddScoped<ISourceRegistryRepository, SourceRegistryRepository>();
builder.Services.AddScoped<IDiscoveredLinkRepository, DiscoveredLinkRepository>();
builder.Services.AddScoped<IFetchItemRepository, FetchItemRepository>();

builder.Services.AddScoped<IGabiJobRunner, GabiJobRunner>();
builder.Services.AddScoped<IJobExecutor, CatalogSeedJobExecutor>();
builder.Services.AddScoped<IJobExecutor, SourceSyncJobExecutor>();
builder.Services.AddScoped<IJobExecutor, SourceDiscoveryJobExecutor>();
builder.Services.AddScoped<IJobExecutor, FetchJobExecutor>();
builder.Services.AddScoped<IJobExecutor, IngestJobExecutor>();

var host = builder.Build();
host.Run();
