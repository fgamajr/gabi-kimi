namespace Gabi.Contracts.Reconciliation;

/// <summary>
/// Result of a reconciliation operation between snapshot and database.
/// </summary>
public record ReconciliationResult
{
    /// <summary>
    /// The source identifier.
    /// </summary>
    public required string SourceId { get; init; }

    /// <summary>
    /// When the reconciliation was performed.
    /// </summary>
    public DateTime ReconciledAt { get; init; } = DateTime.UtcNow;

    /// <summary>
    /// Documents that need to be inserted (new in source).
    /// </summary>
    public IReadOnlyList<InsertOperation> DocumentsToInsert { get; init; } = Array.Empty<InsertOperation>();

    /// <summary>
    /// Documents that need to be updated (content changed).
    /// </summary>
    public IReadOnlyList<UpdateOperation> DocumentsToUpdate { get; init; } = Array.Empty<UpdateOperation>();

    /// <summary>
    /// Documents that need to be soft deleted (removed from source).
    /// </summary>
    public IReadOnlyList<DeleteOperation> DocumentsToDelete { get; init; } = Array.Empty<DeleteOperation>();

    /// <summary>
    /// Statistics about the reconciliation.
    /// </summary>
    public ReconciliationStatistics Statistics { get; init; } = new();
}

/// <summary>
/// Statistics about a reconciliation operation.
/// </summary>
public record ReconciliationStatistics
{
    /// <summary>
    /// Total documents in snapshot.
    /// </summary>
    public int TotalCount { get; init; }

    /// <summary>
    /// Documents added (new in source).
    /// </summary>
    public int AddedCount { get; init; }

    /// <summary>
    /// Documents updated (content changed).
    /// </summary>
    public int UpdatedCount { get; init; }

    /// <summary>
    /// Documents removed from source.
    /// </summary>
    public int RemovedCount { get; init; }

    /// <summary>
    /// Documents unchanged (same hash).
    /// </summary>
    public int UnchangedCount { get; init; }
}

/// <summary>
/// Operation to insert a new document.
/// </summary>
public record InsertOperation
{
    /// <summary>
    /// Stable identifier from the source.
    /// </summary>
    public required string ExternalId { get; init; }

    /// <summary>
    /// URL to access the document.
    /// </summary>
    public required string Url { get; init; }

    /// <summary>
    /// Document title.
    /// </summary>
    public required string Title { get; init; }

    /// <summary>
    /// Content hash for deduplication.
    /// </summary>
    public required string ContentHash { get; init; }
}

/// <summary>
/// Operation to update an existing document.
/// </summary>
public record UpdateOperation
{
    /// <summary>
    /// Stable identifier from the source.
    /// </summary>
    public required string ExternalId { get; init; }

    /// <summary>
    /// URL to access the document.
    /// </summary>
    public required string Url { get; init; }

    /// <summary>
    /// Document title.
    /// </summary>
    public required string Title { get; init; }

    /// <summary>
    /// New content hash.
    /// </summary>
    public required string NewContentHash { get; init; }

    /// <summary>
    /// Previous content hash.
    /// </summary>
    public required string PreviousContentHash { get; init; }
}

/// <summary>
/// Operation to soft delete a document (removed from source).
/// </summary>
public record DeleteOperation
{
    /// <summary>
    /// Stable identifier from the source.
    /// </summary>
    public required string ExternalId { get; init; }

    /// <summary>
    /// When the document was last synced before deletion.
    /// </summary>
    public DateTime LastSyncedAt { get; init; }
}
