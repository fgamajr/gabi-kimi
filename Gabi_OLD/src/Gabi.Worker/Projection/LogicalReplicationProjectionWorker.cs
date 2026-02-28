using Polly;
using System.Text.Json;
using Gabi.Contracts.Index;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Npgsql;
using Npgsql.Replication;
using Npgsql.Replication.PgOutput;
using Npgsql.Replication.PgOutput.Messages;
using NpgsqlTypes;

namespace Gabi.Worker.Projection;

/// <summary>
/// WAL logical replication worker. Listens to the gabi_projection slot on the documents table
/// and forwards changes to Elasticsearch with external versioning (UpdatedAt.Ticks as ES version).
///
/// Only runs when Gabi:EnableWalProjection = true (global kill-switch).
/// Only processes documents from sources where use_wal_projection = true (per-source gate).
///
/// Invariant 2: ES writes use version_type=external with UpdatedAt.Ticks. Stale writes (409) are
/// logged as metrics, NOT written to DLQ.
/// Invariant 3: For WAL-enabled sources, EmbedAndIndexJobExecutor skips the ES write.
/// </summary>
public class LogicalReplicationProjectionWorker : BackgroundService
{
    private const string SlotName = "gabi_projection";
    private const string PublicationName = "gabi_docs_pub";
    private const string DocumentsTable = "documents";
    private const int CheckpointBatchSize = 100;
    private static readonly TimeSpan CheckpointInterval = TimeSpan.FromSeconds(5);

    private readonly IConfiguration _configuration;
    private readonly IServiceProvider _services;
    private readonly ILogger<LogicalReplicationProjectionWorker> _logger;

    private int _consecutiveDlqWriteFailures;
    private const int MaxDlqWriteFailures = 5;
    private int _consecutiveCheckpointFailures;
    private const int MaxCheckpointFailures = 3;

    public LogicalReplicationProjectionWorker(
        IConfiguration configuration,
        IServiceProvider services,
        ILogger<LogicalReplicationProjectionWorker> logger)
    {
        _configuration = configuration;
        _services = services;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        if (!string.Equals(_configuration["Gabi:EnableWalProjection"], "true", StringComparison.OrdinalIgnoreCase))
        {
            _logger.LogInformation("WAL projection disabled (Gabi:EnableWalProjection=false); worker not started");
            return;
        }

        var connectionString = _configuration.GetConnectionString("Default");
        if (string.IsNullOrWhiteSpace(connectionString))
        {
            _logger.LogWarning("ConnectionStrings:Default not set; WAL projection worker not started");
            return;
        }

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await RunReplicationLoopAsync(connectionString, stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "WAL projection loop crashed; restarting in 10s");
                await Task.Delay(TimeSpan.FromSeconds(10), stoppingToken);
            }
        }
    }

    private async Task RunReplicationLoopAsync(string connectionString, CancellationToken ct)
    {
        // Load last persisted LSN from checkpoint
        string lastLsnText;
        using (var scope = _services.CreateScope())
        {
            var ctx = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
            var checkpoint = await ctx.ProjectionCheckpoints
                .AsNoTracking()
                .FirstOrDefaultAsync(c => c.SlotName == SlotName, ct);
            lastLsnText = checkpoint?.Lsn ?? "0/0";
        }

        // Replication connections must not be pooled
        var csb = new NpgsqlConnectionStringBuilder(connectionString) { Pooling = false };

        await using var conn = new LogicalReplicationConnection(csb.ConnectionString);
        await conn.Open(ct);

        _logger.LogInformation("WAL projection worker connected; resuming from LSN {Lsn}", lastLsnText);

        var slot = new PgOutputReplicationSlot(SlotName);
        var options = new PgOutputReplicationOptions(PublicationName, 1UL);
        var startLsn = NpgsqlLogSequenceNumber.Parse(lastLsnText);

        var sem = new SemaphoreSlim(8, 8); // max 8 parallel ES writes
        var messageCount = 0;
        var lastCheckpoint = DateTime.UtcNow;
        NpgsqlLogSequenceNumber currentLsn = startLsn;

        await foreach (var message in conn.StartReplication(slot, options, ct, startLsn))
        {
            currentLsn = message.WalEnd;
            messageCount++;

            if (message is InsertMessage insert && IsDocumentsTable(insert.Relation))
            {
                await HandleRowChangeAsync(insert.Relation, await ReadColumnsAsync(insert.Relation, insert.NewRow), "upsert", sem, ct);
            }
            else if (message is UpdateMessage update && IsDocumentsTable(update.Relation))
            {
                await HandleRowChangeAsync(update.Relation, await ReadColumnsAsync(update.Relation, update.NewRow), "upsert", sem, ct);
            }
            else if (message is FullDeleteMessage fullDelete && IsDocumentsTable(fullDelete.Relation))
            {
                var cols = await ReadColumnsAsync(fullDelete.Relation, fullDelete.OldRow);
                await HandleDeleteAsync(cols, ct);
            }

            // Checkpoint every N messages or every 5 seconds
            if (messageCount >= CheckpointBatchSize || DateTime.UtcNow - lastCheckpoint >= CheckpointInterval)
            {
                var success = await PersistCheckpointAsync(currentLsn.ToString(), ct);
                if (success)
                {
                    conn.SetReplicationStatus(currentLsn);
                    await conn.SendStatusUpdate(ct);
                }
                messageCount = 0;
                lastCheckpoint = DateTime.UtcNow;
            }
        }
    }

    private static bool IsDocumentsTable(RelationMessage relation)
        => string.Equals(relation.RelationName, DocumentsTable, StringComparison.OrdinalIgnoreCase);

    private static async Task<Dictionary<string, object?>> ReadColumnsAsync(RelationMessage relation, ReplicationTuple tuple)
    {
        var result = new Dictionary<string, object?>(StringComparer.OrdinalIgnoreCase);
        var columns = relation.Columns;
        var index = 0;
        await foreach (var col in tuple)
        {
            if (index < columns.Count)
                result[columns[index].ColumnName] = col.IsDBNull ? null : await col.Get<string>();
            index++;
        }
        return result;
    }

    private async Task HandleRowChangeAsync(
        RelationMessage relation,
        Dictionary<string, object?> cols,
        string operation,
        SemaphoreSlim sem,
        CancellationToken ct)
    {
        var documentId = cols.GetValueOrDefault("Id")?.ToString() ?? cols.GetValueOrDefault("id")?.ToString();
        var sourceId = cols.GetValueOrDefault("SourceId")?.ToString() ?? cols.GetValueOrDefault("source_id")?.ToString();
        var status = cols.GetValueOrDefault("Status")?.ToString() ?? cols.GetValueOrDefault("status")?.ToString();
        var updatedAtStr = cols.GetValueOrDefault("UpdatedAt")?.ToString() ?? cols.GetValueOrDefault("updated_at")?.ToString();

        if (string.IsNullOrEmpty(documentId) || string.IsNullOrEmpty(sourceId))
            return;

        // Per-source gate: only process sources opted into WAL projection
        using var scope = _services.CreateScope();
        var ctx = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
        var source = await ctx.SourceRegistries.AsNoTracking()
            .FirstOrDefaultAsync(s => s.Id == sourceId, ct);
        if (source?.UseWalProjection != true)
            return;

        // Only index documents in valid statuses
        if (status is null || (status != "pending_projection" && status != "active" && status != "completed"))
            return;

        DateTime updatedAt = DateTime.TryParse(updatedAtStr, out var dt) ? dt.ToUniversalTime() : DateTime.UtcNow;
        var version = updatedAt.Ticks;

        await sem.WaitAsync(ct);
        try
        {
            await IndexDocumentWithVersionAsync(ctx, documentId, version, cols, ct);
        }
        finally
        {
            sem.Release();
        }
    }

    private async Task IndexDocumentWithVersionAsync(
        GabiDbContext ctx,
        string documentId,
        long version,
        Dictionary<string, object?> cols,
        CancellationToken ct)
    {
        try
        {
            using var scope = _services.CreateScope();
            var indexer = scope.ServiceProvider.GetRequiredService<IDocumentIndexer>();

            var title = cols.GetValueOrDefault("Title")?.ToString() ?? string.Empty;
            var sourceId = cols.GetValueOrDefault("SourceId")?.ToString() ?? string.Empty;
            var content = cols.GetValueOrDefault("Content")?.ToString() ?? string.Empty;
            var updatedAtStr = cols.GetValueOrDefault("UpdatedAt")?.ToString();
            var updatedAt = DateTime.TryParse(updatedAtStr, out var dt) ? dt.ToUniversalTime() : DateTime.UtcNow;

            var indexDoc = new IndexDocument
            {
                DocumentId = documentId,
                SourceId = sourceId,
                Title = title,
                ContentPreview = content.Length > 240 ? content[..240] : content,
                Status = "active",
                IngestedAt = updatedAt,
                UpdatedAt = updatedAt,
                ExternalVersion = version,
                Metadata = new Dictionary<string, object> { ["wal_projected"] = true, ["doc_version"] = version }
            };

            // For WAL projection we call IndexAsync with external versioning
            var result = await indexer.IndexAsync(indexDoc, Array.Empty<IndexChunk>(), ct);
            if (result.Status == IndexingStatus.VersionConflict)
            {
                _logger.LogDebug("stale_write_ignored for doc {DocId}: ES version is newer", documentId);
                // NOT written to DLQ per Invariant 2
            }
            else if (result.Status == IndexingStatus.Failed)
            {
                await WriteToDlqAsync(documentId, sourceId, "upsert", cols, string.Join("; ", result.Errors), ct);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "WAL projection index failed for doc {DocId}", documentId);
            var sourceId = cols.GetValueOrDefault("SourceId")?.ToString() ?? string.Empty;
            await WriteToDlqAsync(documentId, sourceId, "upsert", cols, ex.Message, ct);
        }
    }

    private async Task HandleDeleteAsync(Dictionary<string, object?> cols, CancellationToken ct)
    {
        var documentId = cols.GetValueOrDefault("Id")?.ToString() ?? cols.GetValueOrDefault("id")?.ToString();
        if (string.IsNullOrEmpty(documentId)) return;

        try
        {
            using var scope = _services.CreateScope();
            var indexer = scope.ServiceProvider.GetRequiredService<IDocumentIndexer>();
            await indexer.DeleteAsync(documentId, ct);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "WAL projection delete failed for doc {DocId}", documentId);
            var sourceId = cols.GetValueOrDefault("SourceId")?.ToString() ?? string.Empty;
            await WriteToDlqAsync(documentId, sourceId, "delete", cols, ex.Message, ct);
        }
    }

    private async Task WriteToDlqAsync(
        string documentId,
        string sourceId,
        string operation,
        Dictionary<string, object?> payload,
        string? error,
        CancellationToken ct)
    {
        var retryPolicy = Policy
            .Handle<Exception>()
            .WaitAndRetryAsync(
                3,
                retryAttempt => TimeSpan.FromSeconds(Math.Pow(2, retryAttempt)),
                (ex, time, retryCount, context) =>
                {
                    _logger.LogWarning(ex, "Failed to write DLQ entry for {DocId} (attempt {RetryCount}/3), retrying in {Time}s...", documentId, retryCount, time.TotalSeconds);
                });

        try
        {
            await retryPolicy.ExecuteAsync(async () =>
            {
                using var scope = _services.CreateScope();
                var ctx = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
                ctx.ProjectionDlqEntries.Add(new ProjectionDlqEntity
                {
                    DocumentId = documentId,
                    SourceId = sourceId,
                    Operation = operation,
                    Payload = JsonSerializer.Serialize(payload),
                    Error = error?.Length > 2000 ? error[..2000] : error,
                    Status = "pending"
                });
                await ctx.SaveChangesAsync(ct);
            });
            _consecutiveDlqWriteFailures = 0;
        }
        catch (Exception ex)
        {
            _consecutiveDlqWriteFailures++;
            _logger.LogError(ex,
                "Failed to write projection DLQ entry for doc {DocId} (consecutive failures: {Count}/{Max}). Slot: {Slot}",
                documentId, _consecutiveDlqWriteFailures, MaxDlqWriteFailures, SlotName);

            if (_consecutiveDlqWriteFailures >= MaxDlqWriteFailures)
                throw new InvalidOperationException(
                    $"WAL projection: {MaxDlqWriteFailures} consecutive DLQ write failures — stopping worker", ex);
        }
    }

    private async Task<bool> PersistCheckpointAsync(string lsn, CancellationToken ct)
    {
        try
        {
            using var scope = _services.CreateScope();
            var ctx = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
            var checkpoint = await ctx.ProjectionCheckpoints.FirstOrDefaultAsync(c => c.SlotName == SlotName, ct);
            if (checkpoint is null)
            {
                ctx.ProjectionCheckpoints.Add(new ProjectionCheckpointEntity
                {
                    SlotName = SlotName,
                    Lsn = lsn,
                    UpdatedAt = DateTime.UtcNow
                });
            }
            else
            {
                checkpoint.Lsn = lsn;
                checkpoint.UpdatedAt = DateTime.UtcNow;
            }
            await ctx.SaveChangesAsync(ct);
            _consecutiveCheckpointFailures = 0;
            return true;
        }
        catch (Exception ex)
        {
            _consecutiveCheckpointFailures++;
            _logger.LogError(ex,
                "Failed to persist WAL checkpoint (consecutive failures: {Count}/{Max}). Slot: {Slot}, Lsn: {Lsn}",
                _consecutiveCheckpointFailures, MaxCheckpointFailures, SlotName, lsn);

            if (_consecutiveCheckpointFailures >= MaxCheckpointFailures)
                throw;

            return false;
        }
    }
}
