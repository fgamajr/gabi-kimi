using Gabi.ReliabilityLab.Environment;

namespace Gabi.ReliabilityLab.Verification;

public interface IIntegrityCheck
{
    string Name { get; }
    Task<VerificationResult> CheckAsync(EnvironmentConnectionInfo env, CancellationToken ct = default);
}
