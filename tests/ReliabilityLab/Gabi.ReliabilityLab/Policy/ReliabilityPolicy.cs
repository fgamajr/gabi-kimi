using Gabi.ReliabilityLab.Experiment;

namespace Gabi.ReliabilityLab.Policy;

public sealed class ReliabilityPolicy : IEvaluationPolicy
{
    public string Name => "Reliability";
    public int MaxCrashCount { get; init; }
    public int MaxRetryCount { get; init; }
    public int MaxDlqEntries { get; init; }

    public PolicyVerdict Evaluate(ExperimentResult result)
    {
        var violations = new List<PolicyViolation>();
        var evidence = new Dictionary<string, object>
        {
            ["Crashed"] = result.Crashed,
            ["ErrorSummary"] = result.ErrorSummary ?? ""
        };

        if (result.Crashed && MaxCrashCount < 1)
            violations.Add(new PolicyViolation(Name, "NoCrash", "true (crashed)", "Crashed = false"));

        return new PolicyVerdict(violations.Count == 0, violations, new List<PolicyWarning>(), evidence);
    }
}
