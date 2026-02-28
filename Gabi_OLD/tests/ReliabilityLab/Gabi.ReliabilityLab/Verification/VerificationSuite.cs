using Gabi.ReliabilityLab.Environment;

namespace Gabi.ReliabilityLab.Verification;

public static class VerificationSuite
{
    public static async Task<IReadOnlyList<VerificationResult>> RunAllAsync(
        IReadOnlyList<IIntegrityCheck> integrityChecks,
        IReadOnlyList<ISemanticCheck> semanticChecks,
        IReadOnlyList<IConsistencyCheck> consistencyChecks,
        EnvironmentConnectionInfo env,
        CancellationToken ct)
    {
        var results = new List<VerificationResult>();
        foreach (var check in integrityChecks)
            results.Add(await check.CheckAsync(env, ct).ConfigureAwait(false));
        foreach (var check in semanticChecks)
            results.Add(await check.CheckAsync(env, ct).ConfigureAwait(false));
        foreach (var check in consistencyChecks)
            results.Add(await check.CheckAsync(env, ct).ConfigureAwait(false));
        return results;
    }
}
