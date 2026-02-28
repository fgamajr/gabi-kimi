using Gabi.ReliabilityLab.Experiment;

namespace Gabi.ReliabilityLab.Policy;

public static class PolicyEvaluator
{
    public static PolicyVerdict EvaluateAll(ExperimentResult result, IReadOnlyList<IEvaluationPolicy> policies)
    {
        var allViolations = new List<PolicyViolation>();
        var allWarnings = new List<PolicyWarning>();
        var allEvidence = new Dictionary<string, object>();

        foreach (var policy in policies)
        {
            var verdict = policy.Evaluate(result);
            allViolations.AddRange(verdict.Violations);
            allWarnings.AddRange(verdict.Warnings);
            foreach (var kv in verdict.Evidence)
                allEvidence[$"{policy.Name}.{kv.Key}"] = kv.Value;
        }

        return new PolicyVerdict(allViolations.Count == 0, allViolations, allWarnings, allEvidence);
    }
}
