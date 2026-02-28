using Gabi.ReliabilityLab.Environment;

namespace Gabi.ReliabilityLab.Verification;

public interface ISemanticCheck
{
    string Name { get; }
    Task<VerificationResult> CheckAsync(EnvironmentConnectionInfo env, CancellationToken ct = default);
}
