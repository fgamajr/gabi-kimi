namespace Gabi.Postgres.Entities;

public class DocumentEmbeddingEntity
{
    public long Id { get; set; }
    public Guid DocumentId { get; set; }
    public string SourceId { get; set; } = string.Empty;
    public int ChunkIndex { get; set; }
    public string ChunkText { get; set; } = string.Empty;
    public Pgvector.Vector Embedding { get; set; } = null!;
    public string ModelName { get; set; } = string.Empty;
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    public DocumentEntity? Document { get; set; }
}
