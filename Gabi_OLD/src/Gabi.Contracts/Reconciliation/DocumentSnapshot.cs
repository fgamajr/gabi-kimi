namespace Gabi.Contracts.Reconciliation;

/// <summary>
/// Represents a snapshot of documents from a source at a point in time.
/// </summary>
public record DocumentSnapshot
{
    /// <summary>
    /// The source identifier (e.g., "tcu_acordaos").
    /// </summary>
    public required string SourceId { get; init; }

    /// <summary>
    /// List of documents in the snapshot.
    /// </summary>
    public required IReadOnlyList<SnapshotDocument> Documents { get; init; }

    /// <summary>
    /// When the snapshot was captured.
    /// </summary>
    public DateTime CapturedAt { get; init; } = DateTime.UtcNow;
}

/// <summary>
/// Represents a document in a snapshot.
/// </summary>
/// <param name="ExternalId">Stable identifier from the source (e.g., process number, API ID).</param>
/// <param name="Url">URL to access the document.</param>
/// <param name="Title">Document title or summary.</param>
/// <param name="ContentHash">Hash of the content for change detection.</param>
public record SnapshotDocument(
    string ExternalId,
    string Url,
    string Title,
    string ContentHash
);

/// <summary>
/// Represents an existing document in the database for reconciliation.
/// </summary>
/// <param name="ExternalId">Stable identifier from the source.</param>
/// <param name="ContentHash">Hash of the content at last sync.</param>
/// <param name="LastSyncedAt">When the document was last synced.</param>
public record ExistingDocument(
    string ExternalId,
    string ContentHash,
    DateTime LastSyncedAt
);
