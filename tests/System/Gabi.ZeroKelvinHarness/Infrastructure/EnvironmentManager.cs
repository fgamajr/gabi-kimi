using Microsoft.EntityFrameworkCore;
using Testcontainers.Elasticsearch;
using Testcontainers.PostgreSql;
using Testcontainers.Redis;

namespace Gabi.ZeroKelvinHarness.Infrastructure;

/// <summary>
/// Deterministic environment control: starts/stops/resets Testcontainers (Postgres, Redis, Elasticsearch)
/// and applies EF migrations. No manual steps.
/// </summary>
public sealed class EnvironmentManager : IAsyncDisposable
{
    private PostgreSqlContainer? _postgres;
    private RedisContainer? _redis;
    private ElasticsearchContainer? _elasticsearch;
    private bool _started;

    public string ConnectionString { get; private set; } = string.Empty;
    public string RedisUrl { get; private set; } = string.Empty;
    public string ElasticsearchUrl { get; private set; } = string.Empty;

    /// <summary>
    /// Starts dependencies and applies migrations. Idempotent (no-op if already started).
    /// </summary>
    public async Task StartAsync(CancellationToken ct = default)
    {
        if (_started)
            return;

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

        ConnectionString = _postgres.GetConnectionString();
        RedisUrl = $"redis://{_redis.Hostname}:{_redis.GetMappedPublicPort(6379)}/0";
        ElasticsearchUrl = $"http://{_elasticsearch.Hostname}:{_elasticsearch.GetMappedPublicPort(9200)}";

        ApplyMigrations();
        _started = true;
    }

    /// <summary>
    /// Resets database (truncate pipeline tables) and clears Hangfire queue. Does not drop schema.
    /// </summary>
    public async Task ResetAsync(CancellationToken ct = default)
    {
        if (!_started || _postgres == null)
            return;

        var tables = new[]
        {
            "documents", "reconciliation_records", "fetch_items", "fetch_runs", "execution_manifest",
            "discovery_runs", "discovered_links", "seed_runs", "source_registry", "job_registry",
            "dlq_entries", "media_items", "source_pipeline_state", "pipeline_actions", "audit_log", "ingest_jobs"
        };

        await using var conn = new Npgsql.NpgsqlConnection(ConnectionString);
        await conn.OpenAsync(ct).ConfigureAwait(false);
        await using var cmd = conn.CreateCommand();
        var truncateSql = "TRUNCATE " + string.Join(", ", tables) + " RESTART IDENTITY CASCADE;";
        try
        {
            cmd.CommandText = truncateSql;
            await cmd.ExecuteNonQueryAsync(ct).ConfigureAwait(false);
        }
        catch (Npgsql.PostgresException ex) when (ex.SqlState == "42P01")
        {
            // One or more tables do not exist; truncate only existing tables
            foreach (var table in tables)
            {
                cmd.CommandText = $"TRUNCATE {table} RESTART IDENTITY CASCADE;";
                try
                {
                    await cmd.ExecuteNonQueryAsync(ct).ConfigureAwait(false);
                }
                catch (Npgsql.PostgresException inner) when (inner.SqlState == "42P01")
                {
                    // relation does not exist
                }
            }
        }

        // Clear Hangfire enqueued/scheduled jobs so next run has clean queue
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
            // Hangfire schema may not exist yet
        }
    }

    /// <summary>
    /// Stops all containers.
    /// </summary>
    public async Task StopAsync(CancellationToken ct = default)
    {
        _started = false;
        if (_elasticsearch != null) { await _elasticsearch.StopAsync(ct).ConfigureAwait(false); _elasticsearch = null; }
        if (_redis != null) { await _redis.StopAsync(ct).ConfigureAwait(false); _redis = null; }
        if (_postgres != null) { await _postgres.StopAsync(ct).ConfigureAwait(false); _postgres = null; }
        ConnectionString = string.Empty;
        RedisUrl = string.Empty;
        ElasticsearchUrl = string.Empty;
    }

    public async ValueTask DisposeAsync() => await StopAsync().ConfigureAwait(false);

    private void ApplyMigrations()
    {
        var options = new DbContextOptionsBuilder<Gabi.Postgres.GabiDbContext>()
            .UseNpgsql(ConnectionString)
            .Options;
        using var context = new Gabi.Postgres.GabiDbContext(options);
        context.Database.Migrate();
    }
}
