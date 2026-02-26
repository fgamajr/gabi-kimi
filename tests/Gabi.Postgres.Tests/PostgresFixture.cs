using Microsoft.EntityFrameworkCore;
using Testcontainers.PostgreSql;

namespace Gabi.Postgres.Tests;

/// <summary>
/// Shared PostgreSQL container for repository tests. Applies EF migrations once.
/// Use with [Collection("Postgres")] and inject in test class constructor.
/// </summary>
public sealed class PostgresFixture : IDisposable
{
    private readonly PostgreSqlContainer _container;

    public PostgresFixture()
    {
        _container = new PostgreSqlBuilder()
            .WithImage("postgres:15-alpine")
            .Build();
        _container.StartAsync().GetAwaiter().GetResult();
        ConnectionString = _container.GetConnectionString();
        ApplyMigrations();
    }

    public string ConnectionString { get; }

    public void Dispose() => _container.DisposeAsync().AsTask().GetAwaiter().GetResult();

    private void ApplyMigrations()
    {
        var options = new DbContextOptionsBuilder<GabiDbContext>()
            .UseNpgsql(ConnectionString)
            .Options;
        using var context = new GabiDbContext(options);
        context.Database.Migrate();
    }
}
