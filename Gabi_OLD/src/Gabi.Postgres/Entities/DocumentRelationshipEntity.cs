namespace Gabi.Postgres.Entities;

public class DocumentRelationshipEntity
{
    public long Id { get; set; }
    public Guid SourceDocumentId { get; set; }
    public Guid? TargetDocumentId { get; set; }
    public string TargetRef { get; set; } = string.Empty;
    public string RelationType { get; set; } = string.Empty;
    public float Confidence { get; set; } = 1.0f;
    public string ExtractedFrom { get; set; } = string.Empty;
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    public DocumentEntity? SourceDocument { get; set; }
    public DocumentEntity? TargetDocument { get; set; }
}
