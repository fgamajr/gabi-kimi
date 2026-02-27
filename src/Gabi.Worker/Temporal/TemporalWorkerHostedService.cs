using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Temporalio.Client;
using Temporalio.Worker;

namespace Gabi.Worker.Temporal;

/// <summary>
/// IHostedService that starts the Temporal worker connecting PipelineWorkflow + PipelineActivities.
/// Gate 1 (global kill-switch): if Gabi:EnableTemporalWorker = false, StartAsync returns immediately.
/// Gate 2 (config presence): if Temporal:Address is absent, returns immediately.
/// </summary>
public class TemporalWorkerHostedService : IHostedService, IAsyncDisposable
{
    private readonly IConfiguration _configuration;
    private readonly ILogger<TemporalWorkerHostedService> _logger;
    private readonly IServiceProvider _services;

    private TemporalWorker? _worker;
    private Task? _workerTask;
    private CancellationTokenSource? _cts;

    public TemporalWorkerHostedService(
        IConfiguration configuration,
        ILogger<TemporalWorkerHostedService> logger,
        IServiceProvider services)
    {
        _configuration = configuration;
        _logger = logger;
        _services = services;
    }

    public async Task StartAsync(CancellationToken cancellationToken)
    {
        // Gate 1: global kill-switch
        if (!string.Equals(_configuration["Gabi:EnableTemporalWorker"], "true", StringComparison.OrdinalIgnoreCase))
        {
            _logger.LogInformation("Temporal worker disabled (Gabi:EnableTemporalWorker=false)");
            return;
        }

        // Gate 2: config presence
        var address = _configuration["Temporal:Address"];
        if (string.IsNullOrWhiteSpace(address))
        {
            _logger.LogInformation("Temporal worker disabled: Temporal:Address not configured");
            return;
        }

        var ns = _configuration["Temporal:Namespace"] ?? "default";
        var taskQueue = _configuration["Temporal:TaskQueue"] ?? "pipeline";

        try
        {
            var client = await TemporalClient.ConnectAsync(new TemporalClientConnectOptions(address)
            {
                Namespace = ns
            });

            var activities = ActivatorUtilities.CreateInstance<PipelineActivities>(_services);

            _cts = new CancellationTokenSource();
            _worker = new TemporalWorker(client, new TemporalWorkerOptions(taskQueue)
                .AddWorkflow<PipelineWorkflow>()
                .AddAllActivities(activities));

            _workerTask = _worker.ExecuteAsync(_cts.Token);
            _logger.LogInformation("Temporal worker started on task queue '{Queue}' at {Address}", taskQueue, address);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Temporal worker failed to start; Hangfire handles all jobs");
        }
    }

    public async Task StopAsync(CancellationToken cancellationToken)
    {
        if (_cts is not null)
        {
            await _cts.CancelAsync();
            if (_workerTask is not null)
                await _workerTask.WaitAsync(TimeSpan.FromSeconds(10), cancellationToken).ConfigureAwait(false);
        }
    }

    public async ValueTask DisposeAsync()
    {
        _cts?.Dispose();
        if (_worker is IAsyncDisposable ad)
            await ad.DisposeAsync();
        else if (_worker is IDisposable d)
            d.Dispose();
    }
}
