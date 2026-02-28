namespace Gabi.ReliabilityLab.Environment;

/// <summary>
/// Controls infrastructure lifecycle. No business logic — only container/infra management.
/// </summary>
public interface IEnvironmentController : IAsyncDisposable
{
    /// <summary>Starts all infrastructure components. Idempotent.</summary>
    Task<EnvironmentConnectionInfo> StartAsync(CancellationToken ct = default);

    /// <summary>Resets to clean state without full teardown.</summary>
    Task ResetAsync(CancellationToken ct = default);

    /// <summary>Stops all infrastructure. Guaranteed execution via IAsyncDisposable.</summary>
    Task StopAsync(CancellationToken ct = default);

    /// <summary>Current readiness status of all components.</summary>
    Task<ReadinessSnapshot> GetReadinessAsync(CancellationToken ct = default);
}
