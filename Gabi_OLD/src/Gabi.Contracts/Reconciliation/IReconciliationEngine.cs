namespace Gabi.Contracts.Reconciliation;

/// <summary>
/// Engine for reconciling document snapshots with the database.
/// Implements the Snapshot + Diff + Reconcile pattern.
/// </summary>
public interface IReconciliationEngine
{
    /// <summary>
    /// Reconciles a document snapshot with existing documents in the database.
    /// </summary>
    /// <param name="snapshot">Current snapshot from the source.</param>
    /// <param name="existingDocuments">Documents currently in the database for this source.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>Reconciliation result with operations to apply.</returns>
    Task<ReconciliationResult> ReconcileAsync(
        DocumentSnapshot snapshot,
        IReadOnlyList<ExistingDocument> existingDocuments,
        CancellationToken cancellationToken = default);
}
