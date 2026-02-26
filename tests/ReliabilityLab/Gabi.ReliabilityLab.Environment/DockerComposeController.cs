using Microsoft.EntityFrameworkCore;

namespace Gabi.ReliabilityLab.Environment;

/// <summary>
/// Environment controller that uses an already-running docker-compose stack.
/// Does not start or stop containers; use when infra is up via <c>docker compose up -d</c> (e.g. to avoid Testcontainers flakiness).
/// </summary>
public sealed class DockerComposeController : IEnvironmentController
{
    private readonly EnvironmentConnectionInfo _connectionInfo;
    private bool _started;

    public DockerComposeController(
        string postgreSqlConnectionString,
        string redisUrl,
        string elasticsearchUrl)
    {
        _connectionInfo = new EnvironmentConnectionInfo
        {
            PostgreSqlConnectionString = postgreSqlConnectionString,
            RedisUrl = redisUrl,
            ElasticsearchUrl = elasticsearchUrl
        };
    }

    /// <summary>Creates a controller with default local compose ports (Postgres 5433, Redis 6380, ES 9200).</summary>
    public static DockerComposeController CreateLocal()
    {
        return new DockerComposeController(
            "Host=localhost;Port=5433;Database=gabi;Username=gabi;Password=gabi_dev_password",
            "redis://localhost:6380/0",
            "http://localhost:9200");
    }

    public Task<EnvironmentConnectionInfo> StartAsync(CancellationToken ct = default)
    {
        if (_started)
            return Task.FromResult(_connectionInfo);

        ApplyMigrations(_connectionInfo.PostgreSqlConnectionString);
        _started = true;
        return Task.FromResult(_connectionInfo);
    }

    public async Task ResetAsync(CancellationToken ct = default)
    {
        if (!_started)
            return;

        var tables = new[]
        {
            "documents", "reconciliation_records", "fetch_items", "fetch_runs", "execution_manifest",
            "discovery_runs", "discovered_links", "seed_runs", "source_registry", "job_registry",
            "dlq_entries", "media_items", "source_pipeline_state", "pipeline_actions", "audit_log", "ingest_jobs"
        };
        var truncateSql = "TRUNCATE " + string.Join(", ", tables) + " RESTART IDENTITY CASCADE;";

        await using var conn = new Npgsql.NpgsqlConnection(_connectionInfo.PostgreSqlConnectionString);
        await conn.OpenAsync(ct).ConfigureAwait(false);
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = truncateSql;
        await cmd.ExecuteNonQueryAsync(ct).ConfigureAwait(false);

        cmd.CommandText = @"
            DELETE FROM hangfire.job WHERE statename IN ('Enqueued','Scheduled','Processing','Awaiting');
            DELETE FROM hangfire.jobqueue;
        ";
        try
        {
            await cmd.ExecuteNonQueryAsync(ct).ConfigureAwait(false);
        }
        catch
        {
            /* Hangfire schema may not exist */
        }
    }

    public Task StopAsync(CancellationToken ct = default)
    {
        _started = false;
        return Task.CompletedTask;
    }

    public async Task<ReadinessSnapshot> GetReadinessAsync(CancellationToken ct = default)
    {
        if (!_started)
            return new ReadinessSnapshot { PostgreSql = false, Redis = false, Elasticsearch = false };

        var pgOk = await ProbePostgresAsync(_connectionInfo.PostgreSqlConnectionString, ct).ConfigureAwait(false);
        var esOk = await ProbeElasticsearchAsync(_connectionInfo.ElasticsearchUrl, ct).ConfigureAwait(false);
        return new ReadinessSnapshot { PostgreSql = pgOk, Redis = true, Elasticsearch = esOk };
    }

    public ValueTask DisposeAsync() => ValueTask.CompletedTask;

    private static void ApplyMigrations(string connectionString)
    {
        var options = new DbContextOptionsBuilder<Gabi.Postgres.GabiDbContext>()
            .UseNpgsql(connectionString)
            .Options;
        using var context = new Gabi.Postgres.GabiDbContext(options);
        context.Database.Migrate();
    }

    private static async Task<bool> ProbePostgresAsync(string connectionString, CancellationToken ct)
    {
        try
        {
            await using var conn = new Npgsql.NpgsqlConnection(connectionString);
            await conn.OpenAsync(ct).ConfigureAwait(false);
            return true;
        }
        catch
        {
            return false;
        }
    }

    private static async Task<bool> ProbeElasticsearchAsync(string esUrl, CancellationToken ct)
    {
        try
        {
            using var client = new HttpClient();
            client.Timeout = TimeSpan.FromSeconds(3);
            var res = await client.GetAsync($"{esUrl.TrimEnd('/')}/_cluster/health", ct).ConfigureAwait(false);
            return res.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }
}
