using Gabi.ReliabilityLab.Environment;

namespace Gabi.ReliabilityLab.Verification;

public interface IConsistencyCheck
{
    string Name { get; }
    Task<VerificationResult> CheckAsync(EnvironmentConnectionInfo env, CancellationToken ct = default);
}
