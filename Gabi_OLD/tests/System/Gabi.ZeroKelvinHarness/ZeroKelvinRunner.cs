using Gabi.ZeroKelvinHarness.Infrastructure;
using Gabi.ZeroKelvinHarness.Metrics;
using Gabi.ZeroKelvinHarness.Models;
using Gabi.ZeroKelvinHarness.Pipeline;
using Gabi.ZeroKelvinHarness.Verification;

namespace Gabi.ZeroKelvinHarness;

/// <summary>
/// Orchestrates a full Zero-Kelvin run: pipeline execution, metrics, verification. Returns structured result; never asserts.
/// </summary>
public static class ZeroKelvinRunner
{
    /// <summary>
    /// Runs the pipeline with the given config, collects metrics and verification, returns a machine-readable result.
    /// </summary>
    public static async Task<ZeroKelvinResult> RunAsync(
        EnvironmentManager env,
        HttpClient client,
        ZeroKelvinConfig config,
        Func<string, CancellationToken, Task<int>>? getPendingDocumentCountAsync,
        CancellationToken ct = default)
    {
        var stopwatch = System.Diagnostics.Stopwatch.StartNew();
        var crashed = false;
        string? errorSummary = null;

        try
        {
            await env.ResetAsync(ct).ConfigureAwait(false);
            var pendingDelegate = getPendingDocumentCountAsync != null
                ? (CancellationToken t) => getPendingDocumentCountAsync(config.SourceId ?? "tcu_sumulas", t)
                : (Func<CancellationToken, Task<int>>?)null;
            await PipelineRunner.RunPipelineAsync(client, config, pendingDelegate, ct).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            crashed = true;
            errorSummary = ex.Message;
        }

        stopwatch.Stop();
        var duration = stopwatch.Elapsed;
        var sourceId = config.SourceId ?? "tcu_sumulas";

        var stageCounts = await StageTracker.GetStageCountsAsync(env.ConnectionString, sourceId, ct).ConfigureAwait(false);
        var retries = await MetricsCollector.GetRetriesAsync(env.ConnectionString, ct).ConfigureAwait(false);
        var dlqEntries = await MetricsCollector.GetDlqEntriesAsync(env.ConnectionString, ct).ConfigureAwait(false);
        var peakMemoryMb = MetricsCollector.GetCurrentProcessMemoryMb();

        var (_, lossRate, duplicationRate, corruptionRate) = await SampleVerifier.VerifyAsync(
            env.ConnectionString, sourceId, config.SampleSize, 10, ct).ConfigureAwait(false);

        // Semantic score: we don't have original text in DB, so use 1 - corruptionRate as proxy (no truncation = preserved)
        var semanticPreservationScore = 1.0 - corruptionRate;

        return new ZeroKelvinResult
        {
            Duration = duration,
            PeakMemoryMb = peakMemoryMb,
            Retries = retries,
            DlqEntries = dlqEntries,
            StageCounts = stageCounts,
            LossRate = lossRate,
            DuplicationRate = duplicationRate,
            CorruptionRate = corruptionRate,
            SemanticPreservationScore = semanticPreservationScore,
            Crashed = crashed,
            ErrorSummary = errorSummary
        };
    }
}
