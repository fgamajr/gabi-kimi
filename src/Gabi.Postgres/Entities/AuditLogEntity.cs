using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;
using System.Net;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage.ValueConversion;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Generic audit log entry.
/// </summary>
[Table("audit_log")]
[Index(nameof(EntityType), nameof(EntityId), nameof(OccurredAt))]
[Index(nameof(ActorType), nameof(ActorId), nameof(OccurredAt))]
[Index(nameof(EventType), nameof(OccurredAt))]
public class AuditLogEntity
{
    [Key]
    public long Id { get; set; }

    [Required]
    [MaxLength(50)]
    public string EventType { get; set; } = string.Empty;

    [Required]
    [MaxLength(50)]
    public string EntityType { get; set; } = string.Empty;

    [Required]
    [MaxLength(100)]
    public string EntityId { get; set; } = string.Empty;

    [Required]
    [MaxLength(20)]
    public string ActorType { get; set; } = string.Empty;

    [MaxLength(100)]
    public string? ActorId { get; set; }

    [Required]
    [MaxLength(20)]
    public string Action { get; set; } = string.Empty;

    [Column(TypeName = "jsonb")]
    public string? OldValues { get; set; }

    [Column(TypeName = "jsonb")]
    public string? NewValues { get; set; }

    public string? ChangeSummary { get; set; }

    public DateTime OccurredAt { get; set; } = DateTime.UtcNow;

    [MaxLength(100)]
    public string? RequestId { get; set; }

    public IPAddress? SourceIp { get; set; }

    public string? UserAgent { get; set; }

    [Column(TypeName = "jsonb")]
    public string Metadata { get; set; } = "{}";
}
