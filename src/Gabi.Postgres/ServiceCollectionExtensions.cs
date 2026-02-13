using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace Gabi.Postgres;

/// <summary>
/// Extension methods for registering GABI persistence services.
/// </summary>
public static class ServiceCollectionExtensions
{
    /// <summary>
    /// Adds GABI persistence services to the dependency injection container.
    /// </summary>
    /// <param name="services">The service collection.</param>
    /// <param name="connectionString">PostgreSQL connection string.</param>
    /// <returns>The service collection for chaining.</returns>
    public static IServiceCollection AddGabiPersistence(
        this IServiceCollection services,
        string connectionString)
    {
        // Register DbContext
        services.AddDbContext<GabiDbContext>(options =>
        {
            options.UseNpgsql(connectionString, npgsqlOptions =>
            {
                npgsqlOptions.EnableRetryOnFailure(
                    maxRetryCount: 3,
                    maxRetryDelay: TimeSpan.FromSeconds(30),
                    errorCodesToAdd: null);
            });
        });

        // Register repositories
        services.AddScoped<IDiscoveredLinkRepository, DiscoveredLinkRepository>();
        services.AddScoped<ISourceRegistryRepository, SourceRegistryRepository>();
        services.AddScoped<IDocumentRepository, DocumentRepository>();

        // Register Unit of Work
        services.AddScoped<IUnitOfWork, UnitOfWork>();

        return services;
    }

    /// <summary>
    /// Adds GABI persistence services with custom DbContext configuration.
    /// </summary>
    /// <param name="services">The service collection.</param>
    /// <param name="configureOptions">Action to configure DbContext options.</param>
    /// <returns>The service collection for chaining.</returns>
    public static IServiceCollection AddGabiPersistence(
        this IServiceCollection services,
        Action<DbContextOptionsBuilder> configureOptions)
    {
        // Register DbContext with custom configuration
        services.AddDbContext<GabiDbContext>(configureOptions);

        // Register repositories
        services.AddScoped<IDiscoveredLinkRepository, DiscoveredLinkRepository>();
        services.AddScoped<ISourceRegistryRepository, SourceRegistryRepository>();
        services.AddScoped<IDocumentRepository, DocumentRepository>();

        // Register Unit of Work
        services.AddScoped<IUnitOfWork, UnitOfWork>();

        return services;
    }
}
