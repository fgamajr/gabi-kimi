using Gabi.Contracts.Reconciliation;
using Gabi.Jobs.Reconciliation;
using Microsoft.Extensions.DependencyInjection;

namespace Gabi.Jobs;

/// <summary>
/// Extension methods for registering Gabi.Jobs services.
/// </summary>
public static class DependencyInjection
{
    /// <summary>
    /// Adds Gabi.Jobs services to the dependency injection container.
    /// </summary>
    public static IServiceCollection AddGabiJobs(this IServiceCollection services)
    {
        services.AddSingleton<IJobStateMachine, JobStateMachine>();
        services.AddSingleton<IJobFactory, JobFactory>();
        services.AddSingleton<IReconciliationEngine, ReconciliationEngine>();
        
        return services;
    }
}
