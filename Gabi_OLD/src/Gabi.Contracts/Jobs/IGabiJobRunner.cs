namespace Gabi.Contracts.Jobs;

/// <summary>
/// Contrato do job Hangfire executado no Worker. A API enfileira via BackgroundJob.Enqueue&lt;IGabiJobRunner&gt;.
/// Implementado por Gabi.Worker.Jobs.GabiJobRunner.
/// </summary>
public interface IGabiJobRunner
{
    /// <summary>
    /// Executa o job: atualiza job_registry, monta IngestJob a partir do payloadJson, resolve IJobExecutor e executa.
    /// </summary>
    Task RunAsync(Guid jobId, string jobType, string sourceId, string payloadJson, CancellationToken ct);
}
