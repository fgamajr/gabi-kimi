using Gabi.Contracts.Pipeline;
using Microsoft.Extensions.DependencyInjection;

namespace Gabi.Sync.Phase0;

/// <summary>
/// Extension methods for registering Phase 0 pipeline services.
/// </summary>
public static class DependencyInjection
{
    /// <summary>
    /// Adds Phase 0 pipeline services to the dependency injection container.
    /// </summary>
    public static IServiceCollection AddPhase0Pipeline(this IServiceCollection services)
    {
        services.AddSingleton<IPhase0Orchestrator, Phase0Orchestrator>();
        services.AddSingleton<IPhase0LinkComparator, LinkComparator>();
        
        // Register HttpMetadataFetcher with HttpClient
        services.AddHttpClient<IMetadataFetcher, HttpMetadataFetcher>();
        
        return services;
    }
}
