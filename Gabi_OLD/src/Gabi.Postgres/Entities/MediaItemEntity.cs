using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Postgres.Entities;

[Table("media_items")]
[Index(nameof(SourceId), nameof(ExternalId), IsUnique = true)]
[Index(nameof(TranscriptStatus))]
[Index(nameof(CreatedAt))]
public class MediaItemEntity : AuditableEntity
{
    [Key]
    public long Id { get; set; }

    [Required]
    [MaxLength(100)]
    public string SourceId { get; set; } = string.Empty;

    [Required]
    [MaxLength(255)]
    public string ExternalId { get; set; } = string.Empty;

    [MaxLength(2048)]
    public string? MediaUrl { get; set; }

    [MaxLength(2048)]
    public string? TempFilePath { get; set; }

    [MaxLength(500)]
    public string? Title { get; set; }

    public int? DurationSeconds { get; set; }

    [MaxLength(100)]
    public string? SessionType { get; set; }

    [MaxLength(100)]
    public string? Chamber { get; set; }

    public string? TranscriptText { get; set; }
    public string? SummaryText { get; set; }

    [Required]
    [MaxLength(20)]
    public string TranscriptStatus { get; set; } = "pending";

    [MaxLength(20)]
    public string? TranscriptConfidence { get; set; }

    [MaxLength(2000)]
    public string? LastError { get; set; }

    [Column(TypeName = "jsonb")]
    public string Metadata { get; set; } = "{}";
}
