using Gabi.Contracts.Pipeline;
using Microsoft.Extensions.Logging;
using System.Threading.Channels;

namespace Gabi.Sync.Pipeline;

/// <summary>
/// Orquestrador de pipeline para processamento serverless.
/// </summary>
public class PipelineOrchestrator : IPipelineOrchestrator
{
    private readonly IMemoryManager _memoryManager;
    private readonly ILogger<PipelineOrchestrator> _logger;

    public event EventHandler<MemoryPressureEventArgs>? MemoryPressure;
    public event EventHandler<ItemDroppedEventArgs>? ItemDropped;

    public PipelineOrchestrator(IMemoryManager memoryManager, ILogger<PipelineOrchestrator> logger)
    {
        _memoryManager = memoryManager;
        _logger = logger;
    }

    public async Task<PipelineResult> ExecuteAsync<TSource>(
        TSource sourceId,
        IAsyncEnumerable<Document> documents,
        PipelineOptions options,
        CancellationToken ct = default)
    {
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(options.Timeout);
        
        _logger.LogInformation(
            "Pipeline starting for {SourceId} - parallelism={Parallelism}, batchSize={BatchSize}",
            sourceId, options.MaxParallelism, options.BatchSize);

        var metrics = new PipelineMetrics
        {
            SourceId = sourceId?.ToString() ?? "unknown",
            StartedAt = DateTime.UtcNow
        };

        try
        {
            // Canal com backpressure
            var channel = Channel.CreateBounded<Document>(
                new BoundedChannelOptions(options.BatchSize * 2)
                {
                    FullMode = BoundedChannelFullMode.Wait,
                    SingleReader = options.MaxParallelism == 1,
                    SingleWriter = true
                });

            // Producer
            var producer = Task.Run(async () =>
            {
                await foreach (var doc in documents.WithCancellation(ct))
                {
                    await channel.Writer.WriteAsync(doc, cts.Token);
                    metrics.DocumentsProcessed++;
                }
                channel.Writer.Complete();
            }, cts.Token);

            // Consumer(s) - sequencial por padrão (MaxParallelism = 1)
            var consumers = Enumerable.Range(0, options.MaxParallelism)
                .Select(_ => Task.Run(async () =>
                {
                    await foreach (var doc in channel.Reader.ReadAllAsync(cts.Token))
                    {
                        using var lease = _memoryManager.Acquire(doc.EstimatedMemory);
                        // Process document here
                        await Task.Delay(1, cts.Token); // placeholder
                    }
                }, cts.Token))
                .ToArray();

            await Task.WhenAll(producer, Task.WhenAll(consumers));

            metrics.CompletedAt = DateTime.UtcNow;
            metrics.PeakMemoryBytes = _memoryManager.PeakUsage;

            _logger.LogInformation(
                "Pipeline completed for {SourceId} in {Duration}s. Processed: {Processed}, PeakMemory: {PeakMB}MB",
                sourceId,
                metrics.TotalDuration.TotalSeconds,
                metrics.DocumentsProcessed,
                metrics.PeakMemoryBytes / 1024 / 1024);

            return new PipelineResult
            {
                Success = true,
                Metrics = metrics
            };
        }
        catch (OperationCanceledException) when (cts.Token.IsCancellationRequested)
        {
            _logger.LogError("Pipeline timeout for {SourceId}", sourceId);
            return new PipelineResult
            {
                Success = false,
                ErrorMessage = $"Timeout after {options.Timeout}",
                Metrics = metrics
            };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Pipeline failed for {SourceId}", sourceId);
            return new PipelineResult
            {
                Success = false,
                ErrorMessage = ex.Message,
                Metrics = metrics
            };
        }
    }
}
