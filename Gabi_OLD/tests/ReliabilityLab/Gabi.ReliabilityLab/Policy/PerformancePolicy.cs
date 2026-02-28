using Gabi.ReliabilityLab.Experiment;

namespace Gabi.ReliabilityLab.Policy;

public sealed class PerformancePolicy : IEvaluationPolicy
{
    public string Name => "Performance";
    public double MaxMemoryMb { get; init; } = 300;
    public TimeSpan MaxTotalDuration { get; init; } = TimeSpan.FromMinutes(30);

    public PolicyVerdict Evaluate(ExperimentResult result)
    {
        var violations = new List<PolicyViolation>();
        var warnings = new List<PolicyWarning>();

        if (result.Resources.PeakMemoryMb > MaxMemoryMb)
            violations.Add(new PolicyViolation(Name, "MaxMemoryMb", result.Resources.PeakMemoryMb.ToString("F1"), MaxMemoryMb.ToString("F0")));

        if (result.Duration > MaxTotalDuration)
            violations.Add(new PolicyViolation(Name, "MaxTotalDuration", result.Duration.ToString(), MaxTotalDuration.ToString()));

        var evidence = new Dictionary<string, object>
        {
            ["PeakMemoryMb"] = result.Resources.PeakMemoryMb,
            ["Duration"] = result.Duration.TotalSeconds
        };
        return new PolicyVerdict(violations.Count == 0, violations, warnings, evidence);
    }
}
