using Gabi.ReliabilityLab.Experiment;

namespace Gabi.ReliabilityLab.Policy;

public sealed class DataQualityPolicy : IEvaluationPolicy
{
    public string Name => "DataQuality";
    public double MaxLossRate { get; init; } = 0.01;
    public double MaxCorruptionRate { get; init; } = 0.05;
    public double MinSemanticPreservationScore { get; init; } = 0.95;

    public PolicyVerdict Evaluate(ExperimentResult result)
    {
        var violations = new List<PolicyViolation>();
        var evidence = new Dictionary<string, object>();

        foreach (var v in result.Verifications)
        {
            evidence[v.CheckName] = new { v.Passed, v.Message, v.Severity };
            if (!v.Passed && v.Severity == Gabi.ReliabilityLab.Verification.VerificationSeverity.Error)
                violations.Add(new PolicyViolation(Name, v.CheckName, v.Message ?? "failed", "Pass"));
        }

        return new PolicyVerdict(violations.Count == 0, violations, new List<PolicyWarning>(), evidence);
    }
}
