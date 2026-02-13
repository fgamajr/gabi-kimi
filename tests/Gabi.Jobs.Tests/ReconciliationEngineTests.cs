using Gabi.Contracts.Reconciliation;
using Gabi.Jobs.Reconciliation;
using Xunit;

namespace Gabi.Jobs.Tests;

/// <summary>
/// Tests for ReconciliationEngine following TDD principles.
/// Red-Green-Refactor cycle.
/// </summary>
public class ReconciliationEngineTests
{
    private readonly ReconciliationEngine _engine;

    public ReconciliationEngineTests()
    {
        _engine = new ReconciliationEngine();
    }

    [Fact]
    public void ReconcileAsync_NewDocumentsInSnapshot_ReturnsInsertOperations()
    {
        // Arrange - snapshot has 2 new documents not in database
        var sourceId = "tcu_acordaos";
        var snapshot = new DocumentSnapshot
        {
            SourceId = sourceId,
            Documents = new List<SnapshotDocument>
            {
                new("doc-001", "https://example.com/1.pdf", "Doc 1", "hash-001"),
                new("doc-002", "https://example.com/2.pdf", "Doc 2", "hash-002")
            }
        };
        var existingDocuments = new List<ExistingDocument>(); // Empty database

        // Act
        var result = _engine.ReconcileAsync(snapshot, existingDocuments, CancellationToken.None).Result;

        // Assert
        Assert.Equal(2, result.DocumentsToInsert.Count);
        Assert.Empty(result.DocumentsToUpdate);
        Assert.Empty(result.DocumentsToDelete);
        Assert.Equal("doc-001", result.DocumentsToInsert[0].ExternalId);
        Assert.Equal("doc-002", result.DocumentsToInsert[1].ExternalId);
    }

    [Fact]
    public void ReconcileAsync_ExistingDocumentsUnchanged_ReturnsNoOperations()
    {
        // Arrange - snapshot matches database exactly
        var sourceId = "tcu_acordaos";
        var snapshot = new DocumentSnapshot
        {
            SourceId = sourceId,
            Documents = new List<SnapshotDocument>
            {
                new("doc-001", "https://example.com/1.pdf", "Doc 1", "hash-001")
            }
        };
        var existingDocuments = new List<ExistingDocument>
        {
            new("doc-001", "hash-001", DateTime.UtcNow.AddDays(-1))
        };

        // Act
        var result = _engine.ReconcileAsync(snapshot, existingDocuments, CancellationToken.None).Result;

        // Assert
        Assert.Empty(result.DocumentsToInsert);
        Assert.Empty(result.DocumentsToUpdate);
        Assert.Empty(result.DocumentsToDelete);
        Assert.Equal(1, result.Statistics.UnchangedCount);
    }

    [Fact]
    public void ReconcileAsync_ModifiedDocuments_ReturnsUpdateOperations()
    {
        // Arrange - document exists but hash changed (content modified)
        var sourceId = "tcu_acordaos";
        var snapshot = new DocumentSnapshot
        {
            SourceId = sourceId,
            Documents = new List<SnapshotDocument>
            {
                new("doc-001", "https://example.com/1.pdf", "Doc 1 Updated", "hash-NEW")
            }
        };
        var existingDocuments = new List<ExistingDocument>
        {
            new("doc-001", "hash-OLD", DateTime.UtcNow.AddDays(-1))
        };

        // Act
        var result = _engine.ReconcileAsync(snapshot, existingDocuments, CancellationToken.None).Result;

        // Assert
        Assert.Empty(result.DocumentsToInsert);
        Assert.Single(result.DocumentsToUpdate);
        Assert.Empty(result.DocumentsToDelete);
        Assert.Equal("doc-001", result.DocumentsToUpdate[0].ExternalId);
        Assert.Equal("hash-NEW", result.DocumentsToUpdate[0].NewContentHash);
    }

    [Fact]
    public void ReconcileAsync_RemovedDocuments_ReturnsDeleteOperations()
    {
        // Arrange - document exists in DB but not in snapshot (removed from source)
        var sourceId = "tcu_acordaos";
        var snapshot = new DocumentSnapshot
        {
            SourceId = sourceId,
            Documents = new List<SnapshotDocument>() // Empty snapshot
        };
        var existingDocuments = new List<ExistingDocument>
        {
            new("doc-001", "hash-001", DateTime.UtcNow.AddDays(-1))
        };

        // Act
        var result = _engine.ReconcileAsync(snapshot, existingDocuments, CancellationToken.None).Result;

        // Assert
        Assert.Empty(result.DocumentsToInsert);
        Assert.Empty(result.DocumentsToUpdate);
        Assert.Single(result.DocumentsToDelete);
        Assert.Equal("doc-001", result.DocumentsToDelete[0].ExternalId);
    }

    [Fact]
    public void ReconcileAsync_MixedOperations_ReturnsAllTypes()
    {
        // Arrange - combination of insert, update, delete, and unchanged
        var sourceId = "tcu_acordaos";
        var snapshot = new DocumentSnapshot
        {
            SourceId = sourceId,
            Documents = new List<SnapshotDocument>
            {
                new("doc-001", "https://example.com/1.pdf", "Doc 1", "hash-001"), // unchanged
                new("doc-002", "https://example.com/2.pdf", "Doc 2 Updated", "hash-NEW"), // updated
                new("doc-003", "https://example.com/3.pdf", "Doc 3", "hash-003") // new
            }
        };
        var existingDocuments = new List<ExistingDocument>
        {
            new("doc-001", "hash-001", DateTime.UtcNow.AddDays(-2)), // unchanged
            new("doc-002", "hash-OLD", DateTime.UtcNow.AddDays(-2)), // will be updated
            new("doc-004", "hash-004", DateTime.UtcNow.AddDays(-2))  // will be deleted (not in snapshot)
        };

        // Act
        var result = _engine.ReconcileAsync(snapshot, existingDocuments, CancellationToken.None).Result;

        // Assert
        Assert.Single(result.DocumentsToInsert);
        Assert.Equal("doc-003", result.DocumentsToInsert[0].ExternalId);
        
        Assert.Single(result.DocumentsToUpdate);
        Assert.Equal("doc-002", result.DocumentsToUpdate[0].ExternalId);
        
        Assert.Single(result.DocumentsToDelete);
        Assert.Equal("doc-004", result.DocumentsToDelete[0].ExternalId);
        
        Assert.Equal(1, result.Statistics.UnchangedCount);
        Assert.Equal(1, result.Statistics.AddedCount);
        Assert.Equal(1, result.Statistics.UpdatedCount);
        Assert.Equal(1, result.Statistics.RemovedCount);
    }

    [Fact]
    public void ReconcileAsync_EmptySnapshotAndDatabase_ReturnsEmptyResult()
    {
        // Arrange
        var snapshot = new DocumentSnapshot
        {
            SourceId = "tcu_acordaos",
            Documents = new List<SnapshotDocument>()
        };
        var existingDocuments = new List<ExistingDocument>();

        // Act
        var result = _engine.ReconcileAsync(snapshot, existingDocuments, CancellationToken.None).Result;

        // Assert
        Assert.Empty(result.DocumentsToInsert);
        Assert.Empty(result.DocumentsToUpdate);
        Assert.Empty(result.DocumentsToDelete);
        Assert.Equal(0, result.Statistics.TotalCount);
    }

    [Fact]
    public void ReconcileAsync_SetsSourceIdOnResult()
    {
        // Arrange
        var sourceId = "camara_proposicoes";
        var snapshot = new DocumentSnapshot
        {
            SourceId = sourceId,
            Documents = new List<SnapshotDocument>()
        };
        var existingDocuments = new List<ExistingDocument>();

        // Act
        var result = _engine.ReconcileAsync(snapshot, existingDocuments, CancellationToken.None).Result;

        // Assert
        Assert.Equal(sourceId, result.SourceId);
    }

    [Fact]
    public void ReconcileAsync_SetsTimestampOnResult()
    {
        // Arrange
        var beforeTest = DateTime.UtcNow.AddSeconds(-1);
        var snapshot = new DocumentSnapshot
        {
            SourceId = "tcu_acordaos",
            Documents = new List<SnapshotDocument>()
        };
        var existingDocuments = new List<ExistingDocument>();

        // Act
        var result = _engine.ReconcileAsync(snapshot, existingDocuments, CancellationToken.None).Result;
        var afterTest = DateTime.UtcNow.AddSeconds(1);

        // Assert
        Assert.True(result.ReconciledAt >= beforeTest);
        Assert.True(result.ReconciledAt <= afterTest);
    }
}
