using System.Net.Http.Json;
using System.Text.Json;
using Gabi.ZeroKelvinHarness.Models;

namespace Gabi.ZeroKelvinHarness.Pipeline;

/// <summary>
/// Executes full pipeline runs via HTTP: trigger seed/phases and poll for completion.
/// Does not assert; returns when phase completes or timeout.
/// </summary>
public static class PipelineRunner
{
    private static readonly JsonSerializerOptions JsonOptions = new() { PropertyNameCaseInsensitive = true };

    /// <summary>
    /// Triggers seed (POST /api/v1/dashboard/seed). Does not wait.
    /// </summary>
    public static async Task TriggerSeedAsync(HttpClient client, CancellationToken ct = default)
    {
        var res = await client.PostAsync("/api/v1/dashboard/seed", null, ct).ConfigureAwait(false);
        res.EnsureSuccessStatusCode();
    }

    /// <summary>
    /// Triggers a phase for a source (POST /api/v1/dashboard/sources/{sourceId}/phases/{phase}). Body optional.
    /// </summary>
    public static async Task TriggerPhaseAsync(
        HttpClient client,
        string sourceId,
        string phase,
        object? body = null,
        CancellationToken ct = default)
    {
        var content = body != null ? JsonContent.Create(body, options: JsonOptions) : null;
        var res = await client.PostAsync(
            $"/api/v1/dashboard/sources/{sourceId}/phases/{phase}",
            content,
            ct).ConfigureAwait(false);
        if (!res.IsSuccessStatusCode)
        {
            var bodyText = await res.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            throw new HttpRequestException(
                $"Phase {phase} failed: {res.StatusCode}. Response: {bodyText}");
        }
    }

    /// <summary>
    /// Waits for seed to complete by polling GET /api/v1/dashboard/seed/last. Returns when status is completed or partial, or timeout.
    /// </summary>
    public static async Task<bool> WaitForSeedCompletedAsync(
        HttpClient client,
        TimeSpan timeout,
        TimeSpan pollInterval,
        CancellationToken ct = default)
    {
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(timeout);
        while (true)
        {
            try
            {
                var res = await client.GetAsync("/api/v1/dashboard/seed/last", cts.Token).ConfigureAwait(false);
                if (res.IsSuccessStatusCode)
                {
                    var json = await res.Content.ReadFromJsonAsync<JsonElement>(JsonOptions, cts.Token).ConfigureAwait(false);
                    var status = json.TryGetProperty("status", out var s) ? s.GetString() : null;
                    if (status is "completed" or "partial")
                        return true;
                }
                await Task.Delay(pollInterval, cts.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return false;
            }
        }
    }

    /// <summary>
    /// Waits for discovery/fetch phase for a source by polling the phase/last endpoint. Returns when status is completed, partial, or failed, or timeout.
    /// </summary>
    public static async Task<bool> WaitForPhaseCompletedAsync(
        HttpClient client,
        string sourceId,
        string phase,
        TimeSpan timeout,
        TimeSpan pollInterval,
        CancellationToken ct = default)
    {
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(timeout);
        var path = $"/api/v1/dashboard/sources/{sourceId}/{phase}/last";
        while (true)
        {
            try
            {
                var res = await client.GetAsync(path, cts.Token).ConfigureAwait(false);
                if (res.IsSuccessStatusCode)
                {
                    var json = await res.Content.ReadFromJsonAsync<JsonElement>(JsonOptions, cts.Token).ConfigureAwait(false);
                    var status = json.TryGetProperty("status", out var s) ? s.GetString() : null;
                    if (status is "completed" or "partial" or "failed" or "capped" or "inconclusive")
                        return true;
                }
                await Task.Delay(pollInterval, cts.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return false;
            }
        }
    }

    /// <summary>
    /// Waits for ingest completion by checking pending documents count in DB (caller passes a delegate that returns pending count).
    /// Returns when pending == 0 or timeout.
    /// </summary>
    public static async Task<bool> WaitForIngestCompletedAsync(
        Func<CancellationToken, Task<int>> getPendingCountAsync,
        TimeSpan timeout,
        TimeSpan pollInterval,
        CancellationToken ct = default)
    {
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(timeout);
        while (true)
        {
            try
            {
                var pending = await getPendingCountAsync(cts.Token).ConfigureAwait(false);
                if (pending == 0)
                    return true;
                await Task.Delay(pollInterval, cts.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return false;
            }
        }
    }

    /// <summary>
    /// Runs the full pipeline: seed -> wait -> for each phase trigger and wait. Caller provides HttpClient and optional getPendingCount for ingest.
    /// Returns a result summary (duration, etc.); metrics and stage counts must be filled by MetricsCollector and StageTracker after the run.
    /// </summary>
    public static async Task RunPipelineAsync(
        HttpClient client,
        ZeroKelvinConfig config,
        Func<CancellationToken, Task<int>>? getPendingCountAsync,
        CancellationToken ct = default)
    {
        var pollInterval = TimeSpan.FromSeconds(3);
        if (config.Phases.Contains("seed", StringComparer.OrdinalIgnoreCase))
        {
            await TriggerSeedAsync(client, ct).ConfigureAwait(false);
            await WaitForSeedCompletedAsync(client, config.PhaseTimeout, pollInterval, ct).ConfigureAwait(false);
        }

        var sourceId = config.SourceId ?? "tcu_sumulas"; // default single source for harness
        if (config.Phases.Contains("discovery", StringComparer.OrdinalIgnoreCase))
        {
            var body = config.MaxDocs > 0 ? new { max_docs_per_source = config.MaxDocs } : null;
            await TriggerPhaseAsync(client, sourceId, "discovery", body, ct).ConfigureAwait(false);
            await WaitForPhaseCompletedAsync(client, sourceId, "discovery", config.PhaseTimeout, pollInterval, ct).ConfigureAwait(false);
        }
        if (config.Phases.Contains("fetch", StringComparer.OrdinalIgnoreCase))
        {
            var body = config.MaxDocs > 0 ? new { max_docs_per_source = config.MaxDocs } : null;
            await TriggerPhaseAsync(client, sourceId, "fetch", body, ct).ConfigureAwait(false);
            await WaitForPhaseCompletedAsync(client, sourceId, "fetch", config.PhaseTimeout, pollInterval, ct).ConfigureAwait(false);
        }
        if (config.Phases.Contains("ingest", StringComparer.OrdinalIgnoreCase))
        {
            await TriggerPhaseAsync(client, sourceId, "ingest", null, ct).ConfigureAwait(false);
            if (getPendingCountAsync != null)
                await WaitForIngestCompletedAsync(getPendingCountAsync, config.PhaseTimeout, pollInterval, ct).ConfigureAwait(false);
        }
    }
}
