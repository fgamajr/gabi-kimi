using Gabi.Contracts.Enums;
using Gabi.Postgres.Repositories;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Postgres;

/// <summary>
/// DbContext principal do GABI-SYNC.
/// </summary>
public class GabiDbContext : DbContext
{
    public GabiDbContext(DbContextOptions<GabiDbContext> options) : base(options)
    {
    }

    public DbSet<DocumentEntity> Documents => Set<DocumentEntity>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<DocumentEntity>(entity =>
        {
            entity.ToTable("documents");
            entity.HasKey(e => e.Id);
            entity.HasIndex(e => e.DocumentId).IsUnique();
            entity.HasIndex(e => e.Fingerprint).IsUnique();
            entity.HasIndex(e => e.SourceId);
            
            entity.Property(e => e.Id).ValueGeneratedOnAdd();
            entity.Property(e => e.SourceId).HasMaxLength(100).IsRequired();
            entity.Property(e => e.DocumentId).HasMaxLength(255).IsRequired();
            entity.Property(e => e.Title).HasMaxLength(1000);
            entity.Property(e => e.Fingerprint).HasMaxLength(64).IsRequired();
            entity.Property(e => e.Status).HasConversion<string>().HasMaxLength(20);
        });
    }
}
