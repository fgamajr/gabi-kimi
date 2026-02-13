using System.Diagnostics;
using System.Threading.Channels;
using Gabi.Contracts.Jobs;
using Microsoft.Extensions.Logging;

namespace Gabi.Sync.Jobs;

/// <summary>
/// Worker that processes jobs from a channel.
/// </summary>
public class JobWorker : IJobWorker
{
    private readonly ChannelReader<IngestJob> _channel;
    private readonly IJobQueueRepository _queueRepository;
    private readonly IEnumerable<IJobExecutor> _executors;
    private readonly ILogger<JobWorker> _logger;
    private readonly WorkerPoolOptions _options;
    private readonly CancellationTokenSource _cts = new();
    private Task? _executingTask;

    public string WorkerId { get; }
    public WorkerStatus CurrentStatus { get; private set; } = WorkerStatus.Idle;
    public Guid? CurrentJobId { get; private set; }
    public string? CurrentSourceId { get; private set; }
    public DateTime? JobStartedAt { get; private set; }

    public JobWorker(
        int workerNumber,
        ChannelReader<IngestJob> channel,
        IJobQueueRepository queueRepository,
        IEnumerable<IJobExecutor> executors,
        ILogger<JobWorker> logger,
        WorkerPoolOptions options)
    {
        WorkerId = $"{Environment.MachineName}:{Environment.ProcessId}:{workerNumber}";
        _channel = channel;
        _queueRepository = queueRepository;
        _executors = executors;
        _logger = logger;
        _options = options;
    }

    public Task StartAsync(CancellationToken ct)
    {
        _executingTask = ExecuteAsync(ct);
        return Task.CompletedTask;
    }

    private async Task ExecuteAsync(CancellationToken externalCt)
    {
        using var linkedCts = CancellationTokenSource.CreateLinkedTokenSource(
            externalCt, _cts.Token);
        var ct = linkedCts.Token;

        _logger.LogInformation("Worker {WorkerId} started", WorkerId);

        try
        {
            await foreach (var job in _channel.ReadAllAsync(ct))
            {
                await ProcessJobAsync(job, ct);
            }
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested)
        {
            _logger.LogInformation("Worker {WorkerId} cancelled", WorkerId);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Worker {WorkerId} failed", WorkerId);
        }
    }

    private async Task ProcessJobAsync(IngestJob job, CancellationToken ct)
    {
        CurrentStatus = WorkerStatus.Busy;
        CurrentJobId = job.Id;
        CurrentSourceId = job.SourceId;
        JobStartedAt = DateTime.UtcNow;

        var executor = _executors.FirstOrDefault(e => e.JobType.Equals(job.JobType, StringComparison.OrdinalIgnoreCase));
        if (executor == null)
        {
            _logger.LogError("No executor found for job type {JobType}", job.JobType);
            await _queueRepository.FailAsync(job.Id, $"No executor for type: {job.JobType}", false, ct);
            ResetState();
            return;
        }

        using var heartbeatCts = new CancellationTokenSource();
        var heartbeatTask = SendHeartbeatsAsync(job.Id, heartbeatCts.Token);
        var stopwatch = Stopwatch.StartNew();

        try
        {
            _logger.LogInformation(
                "Worker {WorkerId} processing job {JobId} for source {SourceId} (type: {JobType})",
                WorkerId, job.Id, job.SourceId, job.JobType);

            var progress = new Progress<JobProgress>(p =>
            {
                _logger.LogDebug(
                    "Job {JobId} progress: {Percent}% - {Message}",
                    job.Id, p.PercentComplete, p.Message);
            });

            var result = await executor.ExecuteAsync(job, progress, ct);
            stopwatch.Stop();

            if (result.Success)
            {
                await _queueRepository.CompleteAsync(job.Id, ct);
                _logger.LogInformation(
                    "Job {JobId} completed successfully in {Duration}s",
                    job.Id, stopwatch.Elapsed.TotalSeconds);
            }
            else
            {
                var shouldRetry = RetryPolicy.ShouldRetry(job.RetryCount, job.MaxRetries);
                await _queueRepository.FailAsync(job.Id, result.ErrorMessage ?? "Unknown error", shouldRetry, ct);
                
                if (!shouldRetry)
                {
                    _logger.LogError(
                        "Job {JobId} failed permanently after {RetryCount} retries: {Error}",
                        job.Id, job.RetryCount + 1, result.ErrorMessage);
                }
                else
                {
                    _logger.LogWarning(
                        "Job {JobId} failed, will retry: {Error}",
                        job.Id, result.ErrorMessage);
                }
            }
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested)
        {
            _logger.LogWarning("Job {JobId} was cancelled", job.Id);
            // Release the lease so another worker can pick it up
            await _queueRepository.ReleaseLeaseAsync(job.Id, CancellationToken.None);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Job {JobId} failed with exception", job.Id);
            var shouldRetry = RetryPolicy.ShouldRetry(job.RetryCount, job.MaxRetries);
            await _queueRepository.FailAsync(job.Id, ex.Message, shouldRetry, ct);
        }
        finally
        {
            heartbeatCts.Cancel();
            try { await heartbeatTask; }
            catch (OperationCanceledException) { /* ignore */ }
            
            ResetState();
        }
    }

    private async Task SendHeartbeatsAsync(Guid jobId, CancellationToken ct)
    {
        try
        {
            while (!ct.IsCancellationRequested)
            {
                await Task.Delay(_options.HeartbeatInterval, ct);
                
                // Use None to ensure heartbeat goes through even during shutdown
                var success = await _queueRepository.HeartbeatAsync(jobId, CancellationToken.None);
                
                if (!success)
                {
                    _logger.LogWarning(
                        "Heartbeat failed for job {JobId} - job may have been reclaimed",
                        jobId);
                }
                else
                {
                    _logger.LogDebug("Heartbeat sent for job {JobId}", jobId);
                }
            }
        }
        catch (OperationCanceledException)
        {
            // Expected when cancellation is requested
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error sending heartbeat for job {JobId}", jobId);
        }
    }

    private void ResetState()
    {
        CurrentStatus = WorkerStatus.Idle;
        CurrentJobId = null;
        CurrentSourceId = null;
        JobStartedAt = null;
    }

    public async Task StopAsync(CancellationToken ct)
    {
        CurrentStatus = WorkerStatus.Stopping;
        _cts.Cancel();

        if (_executingTask != null)
        {
            try
            {
                await _executingTask.WaitAsync(_options.ShutdownTimeout, ct);
            }
            catch (TimeoutException)
            {
                _logger.LogWarning("Worker {WorkerId} stop timed out", WorkerId);
            }
            catch (OperationCanceledException)
            {
                // Expected
            }
        }

        CurrentStatus = WorkerStatus.Stopped;
        _logger.LogInformation("Worker {WorkerId} stopped", WorkerId);
    }

    public void Dispose()
    {
        _cts.Dispose();
    }
}
