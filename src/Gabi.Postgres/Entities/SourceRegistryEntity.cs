using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Postgres.Entities;

/// <summary>
/// Static source configuration from sources_v2.yaml.
/// </summary>
[Table("source_registry")]
[Index(nameof(Enabled))]
[Index(nameof(Provider))]
[Index(nameof(Category))]
public class SourceRegistryEntity : AuditableEntity
{
    [Key]
    [MaxLength(100)]
    public string Id { get; set; } = string.Empty;

    [Required]
    [MaxLength(255)]
    public string Name { get; set; } = string.Empty;

    public string? Description { get; set; }

    [Required]
    [MaxLength(100)]
    public string Provider { get; set; } = string.Empty;

    [MaxLength(100)]
    public string? Domain { get; set; }

    [MaxLength(10)]
    public string? Jurisdiction { get; set; }

    [MaxLength(50)]
    public string? Category { get; set; }

    [MaxLength(50)]
    public string? CanonicalType { get; set; }

    [Required]
    [MaxLength(50)]
    public string DiscoveryStrategy { get; set; } = string.Empty;

    /// <summary>
    /// Discovery configuration as JSONB.
    /// </summary>
    [Required]
    [Column(TypeName = "jsonb")]
    public string DiscoveryConfig { get; set; } = "{}";

    [MaxLength(20)]
    public string FetchProtocol { get; set; } = "https";

    /// <summary>
    /// Fetch configuration as JSONB.
    /// </summary>
    [Column(TypeName = "jsonb")]
    public string? FetchConfig { get; set; }

    /// <summary>
    /// Pipeline configuration as JSONB.
    /// </summary>
    [Column(TypeName = "jsonb")]
    public string? PipelineConfig { get; set; }

    public bool Enabled { get; set; } = true;

    public DateTime? LastRefresh { get; set; }

    public int TotalLinks { get; set; }

    // Navigation
    public ICollection<DiscoveredLinkEntity> DiscoveredLinks { get; set; } = new List<DiscoveredLinkEntity>();
    public ICollection<SourceRefreshEntity> Refreshes { get; set; } = new List<SourceRefreshEntity>();
}
