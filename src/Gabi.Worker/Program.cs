using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Repositories;
using Gabi.Worker.Jobs;
using Microsoft.EntityFrameworkCore;

var builder = Host.CreateApplicationBuilder(args);

// Database
var connectionString = builder.Configuration.GetConnectionString("Default");
if (string.IsNullOrWhiteSpace(connectionString))
{
    throw new InvalidOperationException("ConnectionStrings:Default is required");
}

builder.Services.AddDbContext<GabiDbContext>(options =>
    options.UseNpgsql(connectionString));

// Repositories
builder.Services.AddScoped<ISourceRegistryRepository, SourceRegistryRepository>();
builder.Services.AddScoped<IDiscoveredLinkRepository, DiscoveredLinkRepository>();
builder.Services.AddScoped<JobQueueRepository>();
builder.Services.AddScoped<IJobQueueRepository>(sp => sp.GetRequiredService<JobQueueRepository>());

// Job executors
builder.Services.AddScoped<IJobExecutor, SourceSyncJobExecutor>();

// Worker pool options
builder.Services.Configure<WorkerPoolOptions>(options =>
{
    options.WorkerCount = builder.Configuration.GetValue<int>("WorkerPool:WorkerCount", 1);
    options.PollInterval = builder.Configuration.GetValue<TimeSpan>("WorkerPool:PollInterval", TimeSpan.FromSeconds(5));
    options.HeartbeatInterval = builder.Configuration.GetValue<TimeSpan>("WorkerPool:HeartbeatInterval", TimeSpan.FromSeconds(30));
    options.LeaseDuration = builder.Configuration.GetValue<TimeSpan>("WorkerPool:LeaseDuration", TimeSpan.FromMinutes(2));
    options.ShutdownTimeout = builder.Configuration.GetValue<TimeSpan>("WorkerPool:ShutdownTimeout", TimeSpan.FromMinutes(1));
    options.RecoveryInterval = builder.Configuration.GetValue<TimeSpan>("WorkerPool:RecoveryInterval", TimeSpan.FromMinutes(1));
    options.StallTimeout = builder.Configuration.GetValue<TimeSpan>("WorkerPool:StallTimeout", TimeSpan.FromMinutes(5));
});

// Hosted service
builder.Services.AddHostedService<JobWorkerHostedService>();

var host = builder.Build();
host.Run();
