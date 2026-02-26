namespace Gabi.Postgres.Tests;

/// <summary>
/// xUnit collection for tests that use the shared PostgreSQL container.
/// </summary>
[CollectionDefinition("Postgres")]
public sealed class PostgresCollection : ICollectionFixture<PostgresFixture>
{
}
