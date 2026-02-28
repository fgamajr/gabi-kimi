namespace Gabi.ReliabilityLab.Verification;

public enum VerificationSeverity { Info, Warning, Error, Critical }

public sealed record VerificationResult
{
    public required string CheckName { get; init; }
    public required bool Passed { get; init; }
    public required VerificationSeverity Severity { get; init; }
    public string? Message { get; init; }
    public IReadOnlyDictionary<string, object> Evidence { get; init; } = new Dictionary<string, object>();
}
