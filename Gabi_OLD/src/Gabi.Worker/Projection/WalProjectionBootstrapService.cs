using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Npgsql;

namespace Gabi.Worker.Projection;

/// <summary>
/// Runs once at Worker startup before LogicalReplicationProjectionWorker.
/// Creates the WAL replication slot and publication if they don't exist.
/// These DDL commands cannot run inside an EF migration transaction (PG restriction).
/// Only runs when Gabi:EnableWalProjection = true.
/// Idempotent: safe to run on every startup.
/// </summary>
public class WalProjectionBootstrapService : IHostedService
{
    private readonly IConfiguration _configuration;
    private readonly ILogger<WalProjectionBootstrapService> _logger;

    private const string PublicationName = "gabi_docs_pub";
    private const string SlotName = "gabi_projection";

    public WalProjectionBootstrapService(IConfiguration configuration, ILogger<WalProjectionBootstrapService> logger)
    {
        _configuration = configuration;
        _logger = logger;
    }

    public async Task StartAsync(CancellationToken cancellationToken)
    {
        if (!_configuration.GetValue<bool>("Gabi:EnableWalProjection"))
        {
            _logger.LogInformation("WAL projection disabled (Gabi:EnableWalProjection=false); skipping slot/publication bootstrap");
            return;
        }

        var connectionString = _configuration.GetConnectionString("Default");
        if (string.IsNullOrWhiteSpace(connectionString))
        {
            _logger.LogWarning("ConnectionStrings:Default not set; cannot bootstrap WAL projection");
            return;
        }

        // Replication connections must NOT be pooled (Npgsql requirement)
        var csb = new NpgsqlConnectionStringBuilder(connectionString) { Pooling = false };

        try
        {
            await using var conn = new NpgsqlConnection(csb.ConnectionString);
            await conn.OpenAsync(cancellationToken);

            // Create publication if not exists
            await using var pubCheckCmd = conn.CreateCommand();
            pubCheckCmd.CommandText = $"SELECT COUNT(1) FROM pg_publication WHERE pubname = '{PublicationName}'";
            var pubExists = (long)(await pubCheckCmd.ExecuteScalarAsync(cancellationToken))! > 0;
            if (!pubExists)
            {
                await using var pubCmd = conn.CreateCommand();
                pubCmd.CommandText = $"CREATE PUBLICATION {PublicationName} FOR TABLE documents";
                await pubCmd.ExecuteNonQueryAsync(cancellationToken);
                _logger.LogInformation("Created WAL publication {Publication}", PublicationName);
            }
            else
            {
                _logger.LogDebug("WAL publication {Publication} already exists", PublicationName);
            }

            // Create replication slot if not exists
            await using var slotCheckCmd = conn.CreateCommand();
            slotCheckCmd.CommandText = $"SELECT COUNT(1) FROM pg_replication_slots WHERE slot_name = '{SlotName}'";
            var slotExists = (long)(await slotCheckCmd.ExecuteScalarAsync(cancellationToken))! > 0;
            if (!slotExists)
            {
                await using var slotCmd = conn.CreateCommand();
                slotCmd.CommandText = $"SELECT pg_create_logical_replication_slot('{SlotName}', 'pgoutput')";
                await slotCmd.ExecuteNonQueryAsync(cancellationToken);
                _logger.LogInformation("Created WAL replication slot {Slot}", SlotName);
            }
            else
            {
                _logger.LogDebug("WAL replication slot {Slot} already exists", SlotName);
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "WalProjectionBootstrapService failed; WAL projection may not work correctly");
            // Non-fatal: WAL worker will fail to connect later if slot doesn't exist
        }
    }

    public Task StopAsync(CancellationToken cancellationToken) => Task.CompletedTask;
}
