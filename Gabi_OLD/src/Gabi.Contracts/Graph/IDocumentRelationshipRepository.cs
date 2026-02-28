namespace Gabi.Contracts.Graph;

public interface IDocumentRelationshipRepository
{
    Task<int> UpsertRelationshipsAsync(Guid sourceDocId,
        IReadOnlyList<DocumentRelation> relations, CancellationToken ct = default);
    Task<IReadOnlyList<DocumentRelation>> GetRelationshipsAsync(
        Guid documentId, CancellationToken ct = default);
    Task<IReadOnlyList<GraphSearchResult>> SearchByRefAsync(
        string refPattern, int topK, CancellationToken ct = default);
    Task<int> ReconcileTargetRefsAsync(CancellationToken ct = default);
}

public record DocumentRelation(string TargetRef, string RelationType,
    float Confidence, string ExtractedFrom, Guid? TargetDocumentId = null);

public record GraphSearchResult(Guid SourceDocumentId, Guid? TargetDocumentId,
    string TargetRef, string RelationType);
