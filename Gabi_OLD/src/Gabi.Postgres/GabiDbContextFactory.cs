using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Design;

namespace Gabi.Postgres;

/// <summary>
/// Design-time factory for EF Core migrations.
/// </summary>
public class GabiDbContextFactory : IDesignTimeDbContextFactory<GabiDbContext>
{
    public GabiDbContext CreateDbContext(string[] args)
    {
        var optionsBuilder = new DbContextOptionsBuilder<GabiDbContext>();
        
        // Default connection string for design-time
        var connectionString = Environment.GetEnvironmentVariable("ConnectionStrings__Default") 
            ?? "Host=localhost;Port=5433;Database=gabi;Username=gabi;Password=gabi_dev_password";
        
        optionsBuilder.UseNpgsql(connectionString);
        
        return new GabiDbContext(optionsBuilder.Options);
    }
}
