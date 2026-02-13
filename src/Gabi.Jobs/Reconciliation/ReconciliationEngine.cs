using Gabi.Contracts.Reconciliation;

namespace Gabi.Jobs.Reconciliation;

/// <summary>
/// Implementation of the reconciliation engine.
/// Compares snapshot with existing documents and generates insert/update/delete operations.
/// </summary>
public class ReconciliationEngine : IReconciliationEngine
{
    public Task<ReconciliationResult> ReconcileAsync(
        DocumentSnapshot snapshot,
        IReadOnlyList<ExistingDocument> existingDocuments,
        CancellationToken cancellationToken = default)
    {
        var toInsert = new List<InsertOperation>();
        var toUpdate = new List<UpdateOperation>();
        var unchanged = 0;

        // Index existing documents by ExternalId for O(1) lookup
        var existingById = existingDocuments.ToDictionary(e => e.ExternalId);

        // Process each document in the snapshot
        foreach (var snapshotDoc in snapshot.Documents)
        {
            cancellationToken.ThrowIfCancellationRequested();

            if (existingById.TryGetValue(snapshotDoc.ExternalId, out var existing))
            {
                // Document exists - check if content changed
                if (existing.ContentHash != snapshotDoc.ContentHash)
                {
                    toUpdate.Add(new UpdateOperation
                    {
                        ExternalId = snapshotDoc.ExternalId,
                        Url = snapshotDoc.Url,
                        Title = snapshotDoc.Title,
                        NewContentHash = snapshotDoc.ContentHash,
                        PreviousContentHash = existing.ContentHash
                    });
                }
                else
                {
                    unchanged++;
                }

                // Remove from dictionary to track what's left for deletion
                existingById.Remove(snapshotDoc.ExternalId);
            }
            else
            {
                // New document - needs insert
                toInsert.Add(new InsertOperation
                {
                    ExternalId = snapshotDoc.ExternalId,
                    Url = snapshotDoc.Url,
                    Title = snapshotDoc.Title,
                    ContentHash = snapshotDoc.ContentHash
                });
            }
        }

        // Remaining documents in existingById are no longer in the source - need delete
        var toDelete = existingById.Values.Select(e => new DeleteOperation
        {
            ExternalId = e.ExternalId,
            LastSyncedAt = e.LastSyncedAt
        }).ToList();

        var result = new ReconciliationResult
        {
            SourceId = snapshot.SourceId,
            ReconciledAt = DateTime.UtcNow,
            DocumentsToInsert = toInsert,
            DocumentsToUpdate = toUpdate,
            DocumentsToDelete = toDelete,
            Statistics = new ReconciliationStatistics
            {
                TotalCount = snapshot.Documents.Count,
                AddedCount = toInsert.Count,
                UpdatedCount = toUpdate.Count,
                RemovedCount = toDelete.Count,
                UnchangedCount = unchanged
            }
        };

        return Task.FromResult(result);
    }
}
