namespace Gabi.ReliabilityLab.Environment;

/// <summary>
/// Connection strings and endpoints for started infrastructure.
/// </summary>
public sealed record EnvironmentConnectionInfo
{
    public required string PostgreSqlConnectionString { get; init; }
    public required string RedisUrl { get; init; }
    public required string ElasticsearchUrl { get; init; }
}
