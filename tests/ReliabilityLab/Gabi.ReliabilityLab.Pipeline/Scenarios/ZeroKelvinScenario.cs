using System.Net.Http.Json;
using System.Text.Json;
using Gabi.ReliabilityLab.Experiment;
using Gabi.ReliabilityLab.Pipeline.Checks;
using Gabi.ReliabilityLab.Verification;
using Gabi.ReliabilityLab.Pipeline.Infrastructure;
using Gabi.ReliabilityLab.Telemetry;
using Microsoft.Extensions.Logging;

namespace Gabi.ReliabilityLab.Pipeline.Scenarios;

public sealed class ZeroKelvinScenario : IExperiment
{
    private static readonly JsonSerializerOptions JsonOptions = new() { PropertyNameCaseInsensitive = true };
    private readonly ZeroKelvinConfig _config;
    private readonly IReadOnlyList<IIntegrityCheck> _integrityChecks;
    private readonly IReadOnlyList<ISemanticCheck> _semanticChecks;
    private readonly IReadOnlyList<IConsistencyCheck> _consistencyChecks;

    public ZeroKelvinScenario(ZeroKelvinConfig? config = null)
    {
        _config = config ?? new ZeroKelvinConfig();
        var sid = _config.SourceId;
        var sample = _config.SampleSize;
        _integrityChecks = new List<IIntegrityCheck> { new PipelineIntegrityCheck(sid, sample) };
        _semanticChecks = new List<ISemanticCheck> { new DocumentSemanticCheck(sid, sample) };
        _consistencyChecks = new List<IConsistencyCheck> { new StageContinuityCheck(sid) };
    }

    public string Name => "ZeroKelvin";
    public IReadOnlyList<IIntegrityCheck> IntegrityChecks => _integrityChecks;
    public IReadOnlyList<ISemanticCheck> SemanticChecks => _semanticChecks;
    public IReadOnlyList<IConsistencyCheck> ConsistencyChecks => _consistencyChecks;

    public async Task ExecuteAsync(ExperimentContext context, CancellationToken ct = default)
    {
        var env = context.Environment;
        using var factory = new LabWebApplicationFactory(env.PostgreSqlConnectionString, env.RedisUrl);
        var client = factory.CreateOperatorClient();
        var pollInterval = TimeSpan.FromSeconds(3);
        var sourceId = _config.SourceId ?? "tcu_sumulas";

        if (_config.Phases.Contains("seed", StringComparer.OrdinalIgnoreCase))
        {
            var start = context.Clock.UtcNow;
            await TriggerSeedAsync(client, ct).ConfigureAwait(false);
            await WaitForSeedCompletedAsync(client, _config.PhaseTimeout, pollInterval, ct).ConfigureAwait(false);
            context.Telemetry.RecordSpan("seed", start, context.Clock.UtcNow);
        }

        if (_config.Phases.Contains("discovery", StringComparer.OrdinalIgnoreCase))
        {
            var start = context.Clock.UtcNow;
            var body = _config.MaxDocs > 0 ? new { max_docs_per_source = _config.MaxDocs } : null;
            await TriggerPhaseAsync(client, sourceId, "discovery", body, ct).ConfigureAwait(false);
            await WaitForPhaseCompletedAsync(client, sourceId, "discovery", _config.PhaseTimeout, pollInterval, ct).ConfigureAwait(false);
            context.Telemetry.RecordSpan("discovery", start, context.Clock.UtcNow);
        }

        if (_config.Phases.Contains("fetch", StringComparer.OrdinalIgnoreCase))
        {
            var start = context.Clock.UtcNow;
            var body = _config.MaxDocs > 0 ? new { max_docs_per_source = _config.MaxDocs } : null;
            await TriggerPhaseAsync(client, sourceId, "fetch", body, ct).ConfigureAwait(false);
            await WaitForPhaseCompletedAsync(client, sourceId, "fetch", _config.PhaseTimeout, pollInterval, ct).ConfigureAwait(false);
            context.Telemetry.RecordSpan("fetch", start, context.Clock.UtcNow);
        }

        if (_config.Phases.Contains("ingest", StringComparer.OrdinalIgnoreCase))
        {
            var start = context.Clock.UtcNow;
            await TriggerPhaseAsync(client, sourceId, "ingest", null, ct).ConfigureAwait(false);
            var pending = await GetPendingDocumentsAsync(env.PostgreSqlConnectionString, sourceId, ct).ConfigureAwait(false);
            await WaitForIngestCompletedAsync(c => GetPendingDocumentsAsync(env.PostgreSqlConnectionString, sourceId, c), _config.PhaseTimeout, pollInterval, ct).ConfigureAwait(false);
            context.Telemetry.RecordSpan("ingest", start, context.Clock.UtcNow);
        }
    }

    private static async Task TriggerSeedAsync(HttpClient client, CancellationToken ct)
    {
        var res = await client.PostAsync("/api/v1/dashboard/seed", null, ct).ConfigureAwait(false);
        res.EnsureSuccessStatusCode();
    }

    private static async Task TriggerPhaseAsync(HttpClient client, string sourceId, string phase, object? body, CancellationToken ct)
    {
        var content = body != null ? JsonContent.Create(body) : null;
        var res = await client.PostAsync($"/api/v1/dashboard/sources/{sourceId}/phases/{phase}", content, ct).ConfigureAwait(false);
        res.EnsureSuccessStatusCode();
    }

    private static async Task<bool> WaitForSeedCompletedAsync(HttpClient client, TimeSpan timeout, TimeSpan pollInterval, CancellationToken ct)
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
                    if (status is "completed" or "partial") return true;
                }
            }
            catch (OperationCanceledException) { return false; }
            await Task.Delay(pollInterval, cts.Token).ConfigureAwait(false);
        }
    }

    private static async Task<bool> WaitForPhaseCompletedAsync(HttpClient client, string sourceId, string phase, TimeSpan timeout, TimeSpan pollInterval, CancellationToken ct)
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
                    if (status is "completed" or "partial" or "failed" or "capped" or "inconclusive") return true;
                }
            }
            catch (OperationCanceledException) { return false; }
            await Task.Delay(pollInterval, cts.Token).ConfigureAwait(false);
        }
    }

    private static async Task<bool> WaitForIngestCompletedAsync(Func<CancellationToken, Task<int>> getPending, TimeSpan timeout, TimeSpan pollInterval, CancellationToken ct)
    {
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(timeout);
        while (true)
        {
            try
            {
                if (await getPending(cts.Token).ConfigureAwait(false) == 0) return true;
            }
            catch (OperationCanceledException) { return false; }
            await Task.Delay(pollInterval, cts.Token).ConfigureAwait(false);
        }
    }

    private static async Task<int> GetPendingDocumentsAsync(string connectionString, string? sourceId, CancellationToken ct)
    {
        var counts = await PipelineStageTracker.GetStageCountsAsync(connectionString, sourceId, ct).ConfigureAwait(false);
        return counts.GetValueOrDefault("documents_pending", 0);
    }
}
