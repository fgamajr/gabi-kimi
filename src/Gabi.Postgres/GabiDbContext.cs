using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage.ValueConversion;
using System.Net;

namespace Gabi.Postgres;

/// <summary>
/// Main database context for GABI-SYNC persistence layer.
/// </summary>
public class GabiDbContext : DbContext
{
    public GabiDbContext(DbContextOptions<GabiDbContext> options) : base(options)
    {
    }

    // Discovery/Ingest Pipeline Tables
    public DbSet<SourceRegistryEntity> SourceRegistries => Set<SourceRegistryEntity>();
    public DbSet<DiscoveredLinkEntity> DiscoveredLinks => Set<DiscoveredLinkEntity>();
    public DbSet<IngestJobEntity> IngestJobs => Set<IngestJobEntity>();
    public DbSet<AuditLogEntity> AuditLogs => Set<AuditLogEntity>();

    // Documents (extracted from links for future ingest phase)
    public DbSet<DocumentEntity> Documents => Set<DocumentEntity>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);

        // Apply configurations
        ConfigureSourceRegistry(modelBuilder);
        ConfigureDiscoveredLinks(modelBuilder);
        ConfigureIngestJobs(modelBuilder);
        ConfigureAuditLog(modelBuilder);
        ConfigureDocumentEntity(modelBuilder);
    }

    private static void ConfigureSourceRegistry(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<SourceRegistryEntity>(entity =>
        {
            entity.ToTable("source_registry");
            entity.HasKey(e => e.Id);

            entity.Property(e => e.Id).HasMaxLength(100);
            entity.Property(e => e.Name).HasMaxLength(255).IsRequired();
            entity.Property(e => e.Provider).HasMaxLength(100).IsRequired();
            entity.Property(e => e.Domain).HasMaxLength(100);
            entity.Property(e => e.Jurisdiction).HasMaxLength(10);
            entity.Property(e => e.Category).HasMaxLength(50);
            entity.Property(e => e.CanonicalType).HasMaxLength(50);
            entity.Property(e => e.DiscoveryStrategy).HasMaxLength(50).IsRequired();
            entity.Property(e => e.FetchProtocol).HasMaxLength(20).HasDefaultValue("https");

            // JSONB columns
            entity.Property(e => e.DiscoveryConfig).HasColumnType("jsonb").IsRequired();
            entity.Property(e => e.FetchConfig).HasColumnType("jsonb");
            entity.Property(e => e.PipelineConfig).HasColumnType("jsonb");

            // Concurrency using PostgreSQL xmin
            entity.Property(e => e.Version)
                .IsRowVersion()
                .HasColumnName("xmin")
                .HasColumnType("xid");

            // Indexes
            entity.HasIndex(e => e.Enabled);
            entity.HasIndex(e => e.Provider);
            entity.HasIndex(e => e.Category);
        });
    }

    private static void ConfigureDiscoveredLinks(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<DiscoveredLinkEntity>(entity =>
        {
            entity.ToTable("discovered_links");
            entity.HasKey(e => e.Id);

            entity.Property(e => e.SourceId).HasMaxLength(100).IsRequired();
            entity.Property(e => e.Url).IsRequired();
            entity.Property(e => e.UrlHash).HasMaxLength(64).IsRequired();
            entity.Property(e => e.Etag).HasMaxLength(255);
            entity.Property(e => e.Status).HasMaxLength(20);
            entity.Property(e => e.ContentHash).HasMaxLength(64);
            entity.Property(e => e.LastContentHash).HasMaxLength(64);

            // JSONB column for flexible metadata
            entity.Property(e => e.Metadata).HasColumnType("jsonb").IsRequired();

            // Concurrency using PostgreSQL xmin
            entity.Property(e => e.Version)
                .IsRowVersion()
                .HasColumnName("xmin")
                .HasColumnType("xid");

            // Unique constraint: one URL per source (using hash for efficiency)
            entity.HasIndex(e => new { e.SourceId, e.UrlHash }).IsUnique();

            // Indexes for performance
            entity.HasIndex(e => new { e.SourceId, e.Status });
            entity.HasIndex(e => e.ContentHash);
            entity.HasIndex(e => e.DiscoveredAt);

            // GIN index for metadata queries
            entity.HasIndex(e => e.Metadata).HasMethod("GIN");

            // Relationships
            entity.HasOne(e => e.Source)
                  .WithMany(s => s.DiscoveredLinks)
                  .HasForeignKey(e => e.SourceId)
                  .OnDelete(DeleteBehavior.Cascade);

            // Relationship with Documents
            entity.HasMany(e => e.Documents)
                  .WithOne(d => d.Link)
                  .HasForeignKey(d => d.LinkId)
                  .OnDelete(DeleteBehavior.Cascade);
        });
    }

    private static void ConfigureIngestJobs(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<IngestJobEntity>(entity =>
        {
            entity.ToTable("ingest_jobs");
            entity.HasKey(e => e.Id);

            entity.Property(e => e.JobType).HasMaxLength(50).IsRequired();
            entity.Property(e => e.Payload).HasColumnType("jsonb").IsRequired();
            entity.Property(e => e.PayloadHash).HasMaxLength(64).IsRequired();
            entity.Property(e => e.SourceId).HasMaxLength(100);
            entity.Property(e => e.Status).HasMaxLength(20);
            entity.Property(e => e.WorkerId).HasMaxLength(100);
            entity.Property(e => e.ErrorDetails).HasColumnType("jsonb");
            entity.Property(e => e.Result).HasColumnType("jsonb");

            // Concurrency using PostgreSQL xmin
            entity.Property(e => e.Version)
                .IsRowVersion()
                .HasColumnName("xmin")
                .HasColumnType("xid");

            // Unique constraint for deduplication
            entity.HasIndex(e => e.PayloadHash).IsUnique();

            // Critical indexes for queue performance
            entity.HasIndex(e => new { e.Status, e.Priority, e.ScheduledAt, e.CreatedAt })
                  .HasDatabaseName("idx_jobs_available");
            entity.HasIndex(e => new { e.Status, e.WorkerId, e.LockedAt });
            entity.HasIndex(e => e.LinkId);
            entity.HasIndex(e => e.SourceId);
            entity.HasIndex(e => e.RetryAt);

            // Relationships
            entity.HasOne(e => e.Link)
                  .WithMany(l => l.Jobs)
                  .HasForeignKey(e => e.LinkId)
                  .OnDelete(DeleteBehavior.SetNull);

            entity.HasOne(e => e.Source)
                  .WithMany()
                  .HasForeignKey(e => e.SourceId)
                  .OnDelete(DeleteBehavior.SetNull);
        });
    }

    private static void ConfigureAuditLog(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<AuditLogEntity>(entity =>
        {
            entity.ToTable("audit_log");
            entity.HasKey(e => e.Id);

            entity.Property(e => e.EventType).HasMaxLength(50).IsRequired();
            entity.Property(e => e.EntityType).HasMaxLength(50).IsRequired();
            entity.Property(e => e.EntityId).HasMaxLength(100).IsRequired();
            entity.Property(e => e.ActorType).HasMaxLength(20).IsRequired();
            entity.Property(e => e.ActorId).HasMaxLength(100);
            entity.Property(e => e.Action).HasMaxLength(20).IsRequired();
            entity.Property(e => e.OldValues).HasColumnType("jsonb");
            entity.Property(e => e.NewValues).HasColumnType("jsonb");
            entity.Property(e => e.RequestId).HasMaxLength(100);
            entity.Property(e => e.Metadata).HasColumnType("jsonb");

            // IP Address conversion
            var ipConverter = new ValueConverter<IPAddress?, string?>(
                v => v != null ? v.ToString() : null,
                v => v != null ? IPAddress.Parse(v) : null);
            entity.Property(e => e.SourceIp).HasConversion(ipConverter);

            // Indexes for audit queries
            entity.HasIndex(e => new { e.EntityType, e.EntityId, e.OccurredAt });
            entity.HasIndex(e => new { e.ActorType, e.ActorId, e.OccurredAt });
            entity.HasIndex(e => new { e.EventType, e.OccurredAt });
            entity.HasIndex(e => e.OccurredAt);
            entity.HasIndex(e => e.RequestId);
        });
    }

    private static void ConfigureDocumentEntity(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<DocumentEntity>(entity =>
        {
            entity.ToTable("documents");
            entity.HasKey(e => e.Id);

            entity.Property(e => e.SourceId).HasMaxLength(100).IsRequired();
            entity.Property(e => e.DocumentId).HasMaxLength(255);
            entity.Property(e => e.ContentHash).HasMaxLength(64);
            entity.Property(e => e.Status).HasMaxLength(20);
            entity.Property(e => e.ProcessingStage).HasMaxLength(50);
            entity.Property(e => e.ContentUrl).HasMaxLength(2048);
            entity.Property(e => e.ElasticsearchId).HasMaxLength(255);

            // JSONB column for flexible metadata
            entity.Property(e => e.Metadata).HasColumnType("jsonb").IsRequired();

            // Concurrency using PostgreSQL xmin
            entity.Property(e => e.Version)
                .IsRowVersion()
                .HasColumnName("xmin")
                .HasColumnType("xid");

            // Indexes
            entity.HasIndex(e => e.LinkId);
            entity.HasIndex(e => e.SourceId);
            entity.HasIndex(e => e.Status);
            entity.HasIndex(e => e.CreatedAt);
            entity.HasIndex(e => e.DocumentId);
            entity.HasIndex(e => e.ContentHash);
        });
    }
}
