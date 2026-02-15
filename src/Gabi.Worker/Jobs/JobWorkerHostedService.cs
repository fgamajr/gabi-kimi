using System.Threading.Channels;
using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Repositories;
using Microsoft.Extensions.Options;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Hosted service that manages a pool of job workers.
/// </summary>
public class JobWorkerHostedService : IHostedService
{
    private readonly IServiceProvider _serviceProvider;
    private readonly ILogger<JobWorkerHostedService> _logger;
    private readonly WorkerPoolOptions _options;
    private readonly List<CancellationTokenSource> _workerCts = new();
    private readonly List<Task> _workers = new();
    private Channel<IngestJob>? _channel;
    private Task? _dequeueTask;
    private Task? _recoveryTask;
    private CancellationTokenSource? _cts;

    public JobWorkerHostedService(
        IServiceProvider serviceProvider,
        ILogger<JobWorkerHostedService> logger,
        IOptions<WorkerPoolOptions> options)
    {
        _serviceProvider = serviceProvider;
        _logger = logger;
        _options = options.Value;
    }

    public Task StartAsync(CancellationToken ct)
    {
        _logger.LogInformation(
            "Starting job worker pool with {Count} workers",
            _options.WorkerCount);

        _cts = new CancellationTokenSource();
        _channel = Channel.CreateBounded<IngestJob>(
            new BoundedChannelOptions(10)
            {
                FullMode = BoundedChannelFullMode.Wait
            });

        // Start worker tasks
        for (int i = 0; i < _options.WorkerCount; i++)
        {
            var workerCts = new CancellationTokenSource();
            _workerCts.Add(workerCts);
            var workerId = $"{Environment.MachineName}:{Environment.ProcessId}:{i}";
            _workers.Add(Task.Run(() => WorkerLoopAsync(workerId, workerCts.Token)));
        }

        // Start dequeue task
        _dequeueTask = Task.Run(() => DequeueLoopAsync(_cts.Token));

        // Start recovery task
        _recoveryTask = Task.Run(() => RecoveryLoopAsync(_cts.Token));

        return Task.CompletedTask;
    }

    private async Task WorkerLoopAsync(string workerId, CancellationToken ct)
    {
        _logger.LogInformation("Worker {WorkerId} started", workerId);

        try
        {
            await foreach (var job in _channel!.Reader.ReadAllAsync(ct))
            {
                await ProcessJobAsync(workerId, job, ct);
            }
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested)
        {
            _logger.LogInformation("Worker {WorkerId} cancelled", workerId);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Worker {WorkerId} failed", workerId);
        }
    }

    private async Task ProcessJobAsync(string workerId, IngestJob job, CancellationToken ct)
    {
        using var scope = _serviceProvider.CreateScope();
        var jobQueue = scope.ServiceProvider.GetRequiredService<IJobQueueRepository>();
        var executors = scope.ServiceProvider.GetRequiredService<IEnumerable<IJobExecutor>>();

        var executor = executors.FirstOrDefault(e => e.JobType == job.JobType);
        if (executor == null)
        {
            _logger.LogError("No executor found for job type {JobType}", job.JobType);
            await jobQueue.FailAsync(job.Id, $"No executor for type: {job.JobType}", false, ct);
            return;
        }

        _logger.LogInformation(
            "Worker {WorkerId} processing job {JobId} for source {SourceId}",
            workerId, job.Id, job.SourceId);

        // Create progress reporter so frontend can show progress via GET /api/v1/jobs/{sourceId}/status
        var progress = new Progress<JobProgress>(p =>
        {
            _ = UpdateProgressIsolatedAsync(job.Id, p);
        });

        // Start heartbeat
        using var heartbeatCts = new CancellationTokenSource();
        var heartbeatTask = SendHeartbeatsAsync(job.Id, heartbeatCts.Token);

        try
        {
            var result = await executor.ExecuteAsync(job, progress, ct);
            
            if (result.Success)
            {
                await jobQueue.CompleteAsync(job.Id, ct);
            }
            else
            {
                await jobQueue.FailAsync(job.Id, result.ErrorMessage ?? "Unknown error", true, ct);
            }

            _logger.LogInformation(
                "Job {JobId} completed with status {Status}",
                job.Id, result.Success ? "success" : "failed");
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested)
        {
            _logger.LogWarning("Job {JobId} was cancelled", job.Id);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Job {JobId} failed with exception", job.Id);
            await jobQueue.FailAsync(job.Id, ex.Message, true, ct);
        }
        finally
        {
            heartbeatCts.Cancel();
            try { await heartbeatTask.WaitAsync(TimeSpan.FromSeconds(5), CancellationToken.None); }
            catch { /* ignore */ }
        }
    }

    private async Task UpdateProgressIsolatedAsync(Guid jobId, JobProgress progress)
    {
        try
        {
            using var scope = _serviceProvider.CreateScope();
            var jobQueue = scope.ServiceProvider.GetRequiredService<IJobQueueRepository>();
            var linksFound = progress.Metrics != null &&
                             progress.Metrics.TryGetValue("linksFound", out var v) &&
                             v is int n
                ? n
                : (int?)null;

            await jobQueue.UpdateProgressAsync(jobId, progress.PercentComplete, progress.Message, linksFound, CancellationToken.None);
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Failed to update progress for job {JobId}", jobId);
        }
    }

    private async Task SendHeartbeatsAsync(Guid jobId, CancellationToken ct)
    {
        try
        {
            while (!ct.IsCancellationRequested)
            {
                await Task.Delay(_options.HeartbeatInterval, ct);
                using var scope = _serviceProvider.CreateScope();
                var jobQueue = scope.ServiceProvider.GetRequiredService<IJobQueueRepository>();
                await jobQueue.HeartbeatAsync(jobId, CancellationToken.None);
            }
        }
        catch (OperationCanceledException) { }
    }

    private async Task DequeueLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                using var scope = _serviceProvider.CreateScope();
                var jobQueue = scope.ServiceProvider.GetRequiredService<IJobQueueRepository>();
                var workerId = $"{Environment.MachineName}:{Environment.ProcessId}:dequeue";

                // Try to get a job
                var job = await jobQueue.DequeueAsync(workerId, _options.LeaseDuration, ct);

                if (job != null)
                {
                    _logger.LogDebug("Dequeued job {JobId} for source {SourceId}",
                        job.Id, job.SourceId);

                    // Wait for channel space and write
                    await _channel!.Writer.WriteAsync(job, ct);
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
        while (!ct.IsCancellationRequested)
        {
            try
            {
                // Wait before first recovery check
                await Task.Delay(_options.RecoveryInterval, ct);

                using var scope = _serviceProvider.CreateScope();
                var jobQueue = scope.ServiceProvider.GetRequiredService<IJobQueueRepository>();

                var stalled = await jobQueue.RecoverStalledJobsAsync(_options.StallTimeout, ct);

                if (stalled.Count > 0)
                {
                    _logger.LogWarning("Recovered {Count} stalled jobs", stalled.Count);
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
        _logger.LogInformation("Stopping job worker pool...");

        _cts?.Cancel();
        _channel?.Writer.Complete();

        // Cancel all workers
        foreach (var workerCts in _workerCts)
        {
            workerCts.Cancel();
        }

        // Wait for all workers to complete
        try
        {
            await Task.WhenAll(_workers)
                .WaitAsync(_options.ShutdownTimeout, ct);
        }
        catch (TimeoutException)
        {
            _logger.LogWarning("Worker pool stop timed out");
        }

        _logger.LogInformation("Job worker pool stopped");
    }
}
