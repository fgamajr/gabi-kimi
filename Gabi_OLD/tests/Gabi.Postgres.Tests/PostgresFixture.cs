using Microsoft.EntityFrameworkCore;
using Testcontainers.PostgreSql;

namespace Gabi.Postgres.Tests;

/// <summary>
/// Shared PostgreSQL container for repository tests. Applies EF migrations once.
/// Use with [Collection("Postgres")] and inject in test class constructor.
/// </summary>
public sealed class PostgresFixture : IAsyncLifetime
{
    private readonly PostgreSqlContainer _container;

    public PostgresFixture()
    {
        _container = new PostgreSqlBuilder()
            .WithImage("postgres:15-alpine")
            .Build();
    }

    public string ConnectionString { get; private set; } = string.Empty;

    public async Task InitializeAsync()
    {
        await _container.StartAsync();
        ConnectionString = _container.GetConnectionString();

        var options = new DbContextOptionsBuilder<GabiDbContext>()
            .UseNpgsql(ConnectionString)
            .Options;
        await using var context = new GabiDbContext(options);
        await context.Database.MigrateAsync();
    }

    public async Task DisposeAsync() => await _container.DisposeAsync();
}
