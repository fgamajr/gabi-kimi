using System.Text.Json;
using Gabi.ReliabilityLab.Experiment;
using Gabi.ReliabilityLab.Policy;
using Microsoft.Extensions.Logging;

namespace Gabi.ReliabilityLab.Reporting;

public sealed class JsonDiagnosticReporter : IDiagnosticReporter
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };
    private readonly ILogger<JsonDiagnosticReporter> _logger;

    public JsonDiagnosticReporter(ILogger<JsonDiagnosticReporter> logger) => _logger = logger;

    public async Task<string> GenerateAsync(
        string artifactRoot,
        ExperimentResult result,
        PolicyVerdict verdict,
        CancellationToken ct = default)
    {
        Directory.CreateDirectory(artifactRoot);
        var rawDir = Path.Combine(artifactRoot, "raw");
        Directory.CreateDirectory(rawDir);

        var summaryPath = Path.Combine(artifactRoot, "summary.json");
        await WriteSummaryAsync(summaryPath, result, verdict, ct).ConfigureAwait(false);

        var metricsPath = Path.Combine(artifactRoot, "metrics.json");
        await WriteMetricsAsync(metricsPath, result, ct).ConfigureAwait(false);

        var timelinePath = Path.Combine(artifactRoot, "timeline.json");
        await WriteTimelineAsync(timelinePath, result.Trace, ct).ConfigureAwait(false);

        var verificationPath = Path.Combine(artifactRoot, "verification.json");
        await WriteVerificationAsync(verificationPath, result.Verifications, ct).ConfigureAwait(false);

        if (verdict.Violations.Count > 0)
        {
            var failuresPath = Path.Combine(artifactRoot, "failures.md");
            await WriteFailuresMdAsync(failuresPath, result, verdict, ct).ConfigureAwait(false);
        }

        _logger.LogInformation("Artifacts written to {Path}", artifactRoot);
        return artifactRoot;
    }

    private static async Task WriteSummaryAsync(string path, ExperimentResult result, PolicyVerdict verdict, CancellationToken ct)
    {
        var summary = new
        {
            result.ExperimentName,
            result.CorrelationId,
            result.StartedAt,
            result.CompletedAt,
            result.Duration,
            result.Crashed,
            result.ErrorSummary,
            VerdictPassed = verdict.Passed,
            ViolationCount = verdict.Violations.Count,
            WarningCount = verdict.Warnings.Count
        };
        await File.WriteAllTextAsync(path, JsonSerializer.Serialize(summary, JsonOptions), ct).ConfigureAwait(false);
    }

    private static async Task WriteMetricsAsync(string path, ExperimentResult result, CancellationToken ct)
    {
        var o = new
        {
            Resources = result.Resources,
            Stages = result.Stages
        };
        await File.WriteAllTextAsync(path, JsonSerializer.Serialize(o, JsonOptions), ct).ConfigureAwait(false);
    }

    private static async Task WriteTimelineAsync(string path, Telemetry.ExecutionTrace trace, CancellationToken ct)
    {
        await File.WriteAllTextAsync(path, JsonSerializer.Serialize(trace, JsonOptions), ct).ConfigureAwait(false);
    }

    private static async Task WriteVerificationAsync(string path, IReadOnlyList<Verification.VerificationResult> verifications, CancellationToken ct)
    {
        await File.WriteAllTextAsync(path, JsonSerializer.Serialize(verifications, JsonOptions), ct).ConfigureAwait(false);
    }

    private static async Task WriteFailuresMdAsync(string path, ExperimentResult result, PolicyVerdict verdict, CancellationToken ct)
    {
        var lines = new List<string>
        {
            "# Failure Analysis",
            "",
            $"**Experiment:** {result.ExperimentName}",
            $"**CorrelationId:** {result.CorrelationId}",
            $"**CompletedAt:** {result.CompletedAt}",
            "",
            "## Violations",
            ""
        };
        foreach (var v in verdict.Violations)
            lines.Add($"- **{v.PolicyName}.{v.Rule}**: actual={v.ActualValue}, threshold={v.Threshold}");
        lines.Add("");
        if (result.ErrorSummary != null)
        {
            lines.Add("## Error Summary");
            lines.Add("");
            lines.Add(result.ErrorSummary);
        }
        await File.WriteAllLinesAsync(path, lines, ct).ConfigureAwait(false);
    }
}
