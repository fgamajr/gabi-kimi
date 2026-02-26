namespace Gabi.ReliabilityLab.Policy;

public sealed record PolicyVerdict(
    bool Passed,
    IReadOnlyList<PolicyViolation> Violations,
    IReadOnlyList<PolicyWarning> Warnings,
    IReadOnlyDictionary<string, object> Evidence);

public sealed record PolicyViolation(string PolicyName, string Rule, string ActualValue, string Threshold);

public sealed record PolicyWarning(string PolicyName, string Message);
