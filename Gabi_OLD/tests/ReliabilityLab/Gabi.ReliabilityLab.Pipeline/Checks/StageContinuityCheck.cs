using Gabi.ReliabilityLab.Environment;
using Gabi.ReliabilityLab.Pipeline.Infrastructure;
using Gabi.ReliabilityLab.Verification;

namespace Gabi.ReliabilityLab.Pipeline.Checks;

public sealed class StageContinuityCheck : IConsistencyCheck
{
    private readonly string? _sourceId;

    public StageContinuityCheck(string? sourceId)
    {
        _sourceId = sourceId;
        Name = "StageContinuity";
    }

    public string Name { get; }

    public async Task<VerificationResult> CheckAsync(EnvironmentConnectionInfo env, CancellationToken ct = default)
    {
        var counts = await PipelineStageTracker.GetStageCountsAsync(env.PostgreSqlConnectionString, _sourceId, ct).ConfigureAwait(false);
        var completed = counts.GetValueOrDefault("documents_completed", 0);
        var pending = counts.GetValueOrDefault("documents_pending", 0);
        var links = counts.GetValueOrDefault("discovered_links", 0);
        var continuityOk = links == 0 || (completed + pending) > 0;
        return new VerificationResult
        {
            CheckName = Name,
            Passed = continuityOk,
            Severity = continuityOk ? VerificationSeverity.Info : VerificationSeverity.Warning,
            Message = $"discovered_links={links}, documents_completed={completed}, documents_pending={pending}",
            Evidence = counts.ToDictionary(k => k.Key, v => (object)v.Value)
        };
    }
}
