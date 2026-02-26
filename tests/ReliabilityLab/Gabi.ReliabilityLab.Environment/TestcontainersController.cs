using Microsoft.EntityFrameworkCore;
using Testcontainers.Elasticsearch;
using Testcontainers.PostgreSql;
using Testcontainers.Redis;

namespace Gabi.ReliabilityLab.Environment;

public sealed class TestcontainersController : IEnvironmentController
{
    private PostgreSqlContainer? _postgres;
    private RedisContainer? _redis;
    private ElasticsearchContainer? _elasticsearch;
    private bool _started;
    private EnvironmentConnectionInfo? _connectionInfo;

    public async Task<EnvironmentConnectionInfo> StartAsync(CancellationToken ct = default)
    {
        if (_started && _connectionInfo != null)
            return _connectionInfo;

        _postgres = new PostgreSqlBuilder()
            .WithImage("postgres:15-alpine")
            .Build();
        _redis = new RedisBuilder()
            .WithImage("redis:7-alpine")
            .Build();
        _elasticsearch = new ElasticsearchBuilder()
            .WithImage("elasticsearch:8.11.0")
            .WithEnvironment("discovery.type", "single-node")
            .WithEnvironment("xpack.security.enabled", "false")
            .WithEnvironment("ES_JAVA_OPTS", "-Xms512m -Xmx512m")
            .Build();

        await _postgres.StartAsync(ct).ConfigureAwait(false);
        await _redis.StartAsync(ct).ConfigureAwait(false);
        await _elasticsearch.StartAsync(ct).ConfigureAwait(false);

        var connectionString = _postgres.GetConnectionString();
        var redisUrl = $"redis://{_redis.Hostname}:{_redis.GetMappedPublicPort(6379)}/0";
        var esUrl = $"http://{_elasticsearch.Hostname}:{_elasticsearch.GetMappedPublicPort(9200)}";

        ApplyMigrations(connectionString);
        _connectionInfo = new EnvironmentConnectionInfo
        {
            PostgreSqlConnectionString = connectionString,
            RedisUrl = redisUrl,
            ElasticsearchUrl = esUrl
        };
        _started = true;
        return _connectionInfo;
    }

    public async Task ResetAsync(CancellationToken ct = default)
    {
        if (!_started || _postgres == null || _connectionInfo == null)
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
        try { await cmd.ExecuteNonQueryAsync(ct).ConfigureAwait(false); }
        catch { /* Hangfire schema may not exist */ }
    }

    public async Task StopAsync(CancellationToken ct = default)
    {
        _started = false;
        _connectionInfo = null;
        if (_elasticsearch != null) { await _elasticsearch.StopAsync(ct).ConfigureAwait(false); _elasticsearch = null; }
        if (_redis != null) { await _redis.StopAsync(ct).ConfigureAwait(false); _redis = null; }
        if (_postgres != null) { await _postgres.StopAsync(ct).ConfigureAwait(false); _postgres = null; }
    }

    public async Task<ReadinessSnapshot> GetReadinessAsync(CancellationToken ct = default)
    {
        if (!_started || _connectionInfo == null)
            return new ReadinessSnapshot { PostgreSql = false, Redis = false, Elasticsearch = false };

        var pgOk = await ProbePostgresAsync(_connectionInfo.PostgreSqlConnectionString, ct).ConfigureAwait(false);
        var redisOk = _redis != null;
        var esOk = _elasticsearch != null;
        return new ReadinessSnapshot { PostgreSql = pgOk, Redis = redisOk, Elasticsearch = esOk };
    }

    public async ValueTask DisposeAsync() => await StopAsync().ConfigureAwait(false);

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
}
