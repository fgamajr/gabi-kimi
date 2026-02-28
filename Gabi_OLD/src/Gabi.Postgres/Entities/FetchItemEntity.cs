using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Item unitário da fase fetch, derivado de um link descoberto.
/// </summary>
[Table("fetch_items")]
[Index(nameof(SourceId), nameof(Status))]
[Index(nameof(DiscoveredLinkId))]
[Index(nameof(FetchRunId))]
public class FetchItemEntity : AuditableEntity
{
    [Key]
    public long Id { get; set; }

    [Required]
    public long DiscoveredLinkId { get; set; }

    [ForeignKey(nameof(DiscoveredLinkId))]
    public DiscoveredLinkEntity DiscoveredLink { get; set; } = null!;

    public Guid? FetchRunId { get; set; }

    [ForeignKey(nameof(FetchRunId))]
    public FetchRunEntity? FetchRun { get; set; }

    [Required]
    [MaxLength(100)]
    public string SourceId { get; set; } = string.Empty;

    [Required]
    public string Url { get; set; } = string.Empty;

    [Required]
    [MaxLength(64)]
    public string UrlHash { get; set; } = string.Empty;

    [Required]
    [MaxLength(20)]
    public string Status { get; set; } = "pending";

    public int Attempts { get; set; }
    public int MaxAttempts { get; set; } = 3;

    [MaxLength(2000)]
    public string? LastError { get; set; }

    public DateTime? StartedAt { get; set; }
    public DateTime? CompletedAt { get; set; }
}

