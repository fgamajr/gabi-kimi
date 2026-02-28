using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Gabi.Worker.Jobs.Fetch;

/// <summary>
/// Handles DB batch writes, claim-with-retry, save-with-retry, and stuck/capped item cleanup
/// for the fetch pipeline stage.
/// </summary>
internal sealed class FetchBatchPersistence
{
    private readonly GabiDbContext _context;
    private readonly IFetchItemRepository _fetchItemRepository;
    private readonly IJobQueueRepository _jobQueue;
    private readonly ILogger _logger;

    private const int ClaimBatchRetryAttempts = 5;

    public FetchBatchPersistence(
        GabiDbContext context,
        IFetchItemRepository fetchItemRepository,
        IJobQueueRepository jobQueue,
        ILogger logger)
    {
        _context = context;
        _fetchItemRepository = fetchItemRepository;
        _jobQueue = jobQueue;
        _logger = logger;
    }

    public async Task InsertBatchAsync(List<DocumentEntity> batch, CancellationToken ct)
    {
        foreach (var doc in batch)
        {
            const string sql = """
                INSERT INTO documents ("Id", "LinkId", "FetchItemId", "SourceId", "ExternalId",
                    "DocumentId", "Title", "Content", "ContentHash", "Status", "ProcessingStage",
                    "Metadata", "CreatedAt", "UpdatedAt", "CreatedBy", "UpdatedBy")
                VALUES (@Id, @LinkId, @FetchItemId, @SourceId, @ExternalId,
                    @DocumentId, @Title, @Content, @ContentHash, @Status, @ProcessingStage,
                    @Metadata::jsonb, @CreatedAt, @UpdatedAt, @CreatedBy, @UpdatedBy)
                ON CONFLICT ("SourceId", "ExternalId") WHERE "RemovedFromSourceAt" IS NULL
                DO UPDATE SET
                    "LinkId" = EXCLUDED."LinkId",
                    "FetchItemId" = EXCLUDED."FetchItemId",
                    "DocumentId" = EXCLUDED."DocumentId",
                    "Title" = EXCLUDED."Title",
                    "Content" = EXCLUDED."Content",
                    "ContentHash" = EXCLUDED."ContentHash",
                    "Status" = EXCLUDED."Status",
                    "ProcessingStage" = EXCLUDED."ProcessingStage",
                    "Metadata" = EXCLUDED."Metadata",
                    "UpdatedAt" = EXCLUDED."UpdatedAt",
                    "UpdatedBy" = EXCLUDED."UpdatedBy"
                """;

            var parameters = new object[]
            {
                new NpgsqlParameter("@Id", doc.Id),
                new NpgsqlParameter("@LinkId", doc.LinkId),
                new NpgsqlParameter("@FetchItemId", doc.FetchItemId ?? (object)DBNull.Value),
                new NpgsqlParameter("@SourceId", doc.SourceId),
                new NpgsqlParameter("@ExternalId", doc.ExternalId ?? (object)DBNull.Value),
                new NpgsqlParameter("@DocumentId", doc.DocumentId ?? (object)DBNull.Value),
                new NpgsqlParameter("@Title", doc.Title ?? (object)DBNull.Value),
                new NpgsqlParameter("@Content", doc.Content ?? (object)DBNull.Value),
                new NpgsqlParameter("@ContentHash", doc.ContentHash ?? (object)DBNull.Value),
                new NpgsqlParameter("@Status", doc.Status),
                new NpgsqlParameter("@ProcessingStage", doc.ProcessingStage ?? (object)DBNull.Value),
                new NpgsqlParameter("@Metadata", doc.Metadata ?? "{}"),
                new NpgsqlParameter("@CreatedAt", doc.CreatedAt),
                new NpgsqlParameter("@UpdatedAt", doc.UpdatedAt),
                new NpgsqlParameter("@CreatedBy", doc.CreatedBy ?? "system"),
                new NpgsqlParameter("@UpdatedBy", doc.UpdatedBy ?? "system")
            };

            await _context.Database.ExecuteSqlRawAsync(sql, (IEnumerable<object>)parameters, ct);
        }

        _logger.LogDebug("Batch of {Count} documents upserted via raw SQL", batch.Count);
    }

    public async Task<IReadOnlyList<FetchItemEntity>> ClaimNextBatchWithRetryAsync(
        string sourceId,
        int limit,
        string[] statuses,
        Guid fetchRunId,
        string updatedBy,
        CancellationToken ct)
    {
        for (var attempt = 1; attempt <= ClaimBatchRetryAttempts; attempt++)
        {
            try
            {
                return await _fetchItemRepository.ClaimNextBatchAsync(
                    sourceId,
                    limit,
                    statuses,
                    fetchRunId,
                    updatedBy,
                    ct);
            }
            catch (Exception ex) when (IsTransientConnectionCapacity(ex) && attempt < ClaimBatchRetryAttempts)
            {
                var backoffMs = 250 * attempt;
                _logger.LogWarning(
                    ex,
                    "Transient DB capacity while claiming fetch batch for {SourceId} (attempt {Attempt}/{MaxAttempts}). Retrying in {BackoffMs}ms.",
                    sourceId,
                    attempt,
                    ClaimBatchRetryAttempts,
                    backoffMs);
                await Task.Delay(backoffMs, ct);
            }
        }

        return await _fetchItemRepository.ClaimNextBatchAsync(
            sourceId,
            limit,
            statuses,
            fetchRunId,
            updatedBy,
            ct);
    }

    public async Task SaveChangesWithRetryAsync(CancellationToken ct)
    {
        const int maxAttempts = 3;
        for (var attempt = 1; attempt <= maxAttempts; attempt++)
        {
            try
            {
                await _context.SaveChangesAsync(ct);
                return;
            }
            catch (Exception ex) when (IsTransientConnectionCapacity(ex) && attempt < maxAttempts)
            {
                var backoffMs = 200 * attempt;
                _logger.LogWarning(
                    ex,
                    "Transient DB capacity while saving fetch progress (attempt {Attempt}/{MaxAttempts}). Retrying in {BackoffMs}ms.",
                    attempt,
                    maxAttempts,
                    backoffMs);
                await Task.Delay(backoffMs, ct);
            }
        }

        await _context.SaveChangesAsync(ct);
    }

    public static bool IsTransientConnectionCapacity(Exception ex)
    {
        if (ex is NpgsqlException npgsql && npgsql.SqlState == "53300")
            return true;

        return ex.InnerException != null && IsTransientConnectionCapacity(ex.InnerException);
    }

    /// <summary>
    /// Resets fetch items stuck in "processing" status from previous interrupted runs.
    /// Items are considered stuck if they've been in "processing" for more than 10 minutes
    /// without recent updates.
    /// </summary>
    public async Task<int> ResetStuckProcessingItemsAsync(string sourceId, CancellationToken ct)
    {
        try
        {
            var cutoffTime = DateTime.UtcNow.AddMinutes(-10);

            // Reset only stale "processing" items from previous interrupted runs.
            // Recent rows may belong to an active retry and must not be reclaimed.
            var stuckItems = await _context.FetchItems
                .Where(i => i.SourceId == sourceId
                    && i.Status == "processing"
                    && (i.UpdatedAt == null || i.UpdatedAt < cutoffTime))
                .ToListAsync(ct);

            if (stuckItems.Count == 0)
                return 0;

            foreach (var item in stuckItems)
            {
                item.Status = "pending";
                item.FetchRunId = null;
                item.LastError = "Reset processing item at fetch start";
                item.UpdatedAt = DateTime.UtcNow;
            }

            await _context.SaveChangesAsync(ct);
            return stuckItems.Count;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to reset stuck processing items for source {SourceId}", sourceId);
            return 0;
        }
    }

    public async Task<int> ReleaseCappedProcessingItemsAsync(string sourceId, Guid fetchRunId, CancellationToken ct)
    {
        var updatedAt = DateTime.UtcNow;
        return await _context.Database.ExecuteSqlInterpolatedAsync($"""
            UPDATE fetch_items
            SET "Status" = 'pending',
                "FetchRunId" = NULL,
                "LastError" = 'deferred_due_to_max_docs_cap',
                "CompletedAt" = NULL,
                "UpdatedAt" = {updatedAt}
            WHERE "SourceId" = {sourceId}
              AND "Status" = 'processing'
              AND "FetchRunId" = {fetchRunId}
            """, ct);
    }

    public static void MarkDeferredByCap(FetchItemEntity item)
    {
        item.Status = "pending";
        item.FetchRunId = null;
        item.LastError = "deferred_due_to_max_docs_cap";
        item.CompletedAt = null;
        item.UpdatedAt = DateTime.UtcNow;
    }
}
