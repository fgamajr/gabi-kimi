using System.Threading.Channels;
using Gabi.Contracts.Jobs;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Gabi.Sync.Jobs;

/// <summary>
/// Hosted service that manages a pool of job workers.
/// Polls the database for jobs and distributes them to workers via channels.
/// </summary>
public class JobWorkerService : IHostedService, IDisposable
{
    private readonly IServiceProvider _serviceProvider;
    private readonly ILogger<JobWorkerService> _logger;
    private readonly WorkerPoolOptions _options;
    private readonly List<IJobWorker> _workers = new();
    private Channel<IngestJob>? _channel;
    private Task? _dequeueTask;
    private Task? _recoveryTask;
    private CancellationTokenSource? _cts;

    public JobWorkerService(
        IServiceProvider serviceProvider,
        ILogger<JobWorkerService> logger,
        IOptions<WorkerPoolOptions> options)
    {
        _serviceProvider = serviceProvider;
        _logger = logger;
        _options = options.Value;
    }

    public Task StartAsync(CancellationToken ct)
    {
        _logger.LogInformation(
            "Starting job worker service with {WorkerCount} workers",
            _options.WorkerCount);

        _cts = new CancellationTokenSource();
        
        // Create bounded channel for backpressure
        var channelCapacity = Math.Max(_options.WorkerCount * 2, 10);
        _channel = Channel.CreateBounded<IngestJob>(
            new BoundedChannelOptions(channelCapacity)
            {
                FullMode = BoundedChannelFullMode.Wait,
                SingleReader = false,
                SingleWriter = true
            });

        // Create and start workers
        for (int i = 0; i < _options.WorkerCount; i++)
        {
            var worker = CreateWorker(i);
            _workers.Add(worker);
            _ = worker.StartAsync(_cts.Token);
        }

        // Start dequeue loop
        _dequeueTask = DequeueLoopAsync(_cts.Token);
        
        // Start recovery loop
        _recoveryTask = RecoveryLoopAsync(_cts.Token);

        _logger.LogInformation(
            "Job worker service started with {WorkerCount} workers, poll interval: {PollInterval}",
            _workers.Count, _options.PollInterval);

        return Task.CompletedTask;
    }

    private IJobWorker CreateWorker(int number)
    {
        var scope = _serviceProvider.CreateScope();
        var queueRepository = scope.ServiceProvider.GetRequiredService<IJobQueueRepository>();
        var executors = scope.ServiceProvider.GetRequiredService<IEnumerable<IJobExecutor>>();
        var logger = scope.ServiceProvider.GetRequiredService<ILogger<JobWorker>>();

        return new JobWorker(
            number,
            _channel!.Reader,
            queueRepository,
            executors,
            logger,
            _options);
    }

    private async Task DequeueLoopAsync(CancellationToken ct)
    {
        await using var scope = _serviceProvider.CreateAsyncScope();
        var queueRepository = scope.ServiceProvider.GetRequiredService<IJobQueueRepository>();

        // Worker ID for this dequeue process
        var workerId = $"{Environment.MachineName}:{Environment.ProcessId}:dequeue";

        while (!ct.IsCancellationRequested)
        {
            try
            {
                // Try to dequeue a job
                var job = await queueRepository.DequeueAsync(workerId, _options.LeaseDuration, ct);

                if (job != null)
                {
                    // Wait for channel space and write the job
                    await _channel!.Writer.WriteAsync(job, ct);
                    
                    _logger.LogDebug(
                        "Dequeued job {JobId} for source {SourceId} and sent to worker channel",
                        job.Id, job.SourceId);
                    
                    // Small delay to prevent hammering the database
                    await Task.Delay(TimeSpan.FromMilliseconds(100), ct);
                }
                else
                {
                    // No jobs available, wait before polling again
                    await Task.Delay(_options.PollInterval, ct);
                }
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error in dequeue loop");
                await Task.Delay(_options.PollInterval, ct);
            }
        }
    }

    private async Task RecoveryLoopAsync(CancellationToken ct)
    {
        await using var scope = _serviceProvider.CreateAsyncScope();
        var queueRepository = scope.ServiceProvider.GetRequiredService<IJobQueueRepository>();

        while (!ct.IsCancellationRequested)
        {
            try
            {
                await Task.Delay(_options.RecoveryInterval, ct);

                // Recover stalled jobs
                var recoveredJobs = await queueRepository.RecoverStalledJobsAsync(
                    _options.StallTimeout, ct);

                if (recoveredJobs.Count > 0)
                {
                    _logger.LogWarning(
                        "Recovered {Count} stalled jobs",
                        recoveredJobs.Count);
                }
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error in recovery loop");
            }
        }
    }

    public async Task StopAsync(CancellationToken ct)
    {
        _logger.LogInformation("Stopping job worker service...");

        _cts?.Cancel();
        _channel?.Writer.Complete();

        // Stop all workers
        var stopTasks = _workers.Select(w => w.StopAsync(ct));
        await Task.WhenAll(stopTasks);

        // Wait for dequeue task
        if (_dequeueTask != null)
        {
            try
            {
                await _dequeueTask.WaitAsync(_options.ShutdownTimeout, ct);
            }
            catch (TimeoutException)
            {
                _logger.LogWarning("Dequeue task stop timed out");
            }
        }

        // Wait for recovery task
        if (_recoveryTask != null)
        {
            try
            {
                await _recoveryTask.WaitAsync(_options.ShutdownTimeout, ct);
            }
            catch (TimeoutException)
            {
                _logger.LogWarning("Recovery task stop timed out");
            }
        }

        _logger.LogInformation("Job worker service stopped");
    }

    public void Dispose()
    {
        foreach (var worker in _workers)
        {
            worker.Dispose();
        }
        _cts?.Dispose();
    }
}
