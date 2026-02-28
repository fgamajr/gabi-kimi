using Gabi.Postgres;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace Gabi.Worker.Projection;

/// <summary>
/// Reads the lag between the current WAL LSN and the projection checkpoint.
/// Used by DriftAuditorJobExecutor to defer repairs when WAL is catching up.
/// </summary>
public class ProjectionLagMonitor
{
    private readonly GabiDbContext _context;
    private readonly ILogger<ProjectionLagMonitor> _logger;

    private const long CatchUpThresholdBytes = 50_000_000L; // 50 MB

    public ProjectionLagMonitor(GabiDbContext context, ILogger<ProjectionLagMonitor> logger)
    {
        _context = context;
        _logger = logger;
    }

    /// <summary>
    /// Returns the WAL lag in bytes (current LSN - checkpoint LSN).
    /// Returns 0 if the checkpoint row doesn't exist or on error.
    /// </summary>
    public async Task<long> GetLagBytesAsync(CancellationToken ct)
    {
        try
        {
            var result = await _context.Database
                .SqlQueryRaw<long>(
                    """
                    SELECT (pg_current_wal_lsn() - "Lsn"::pg_lsn)::bigint AS "Value"
                    FROM projection_checkpoint
                    WHERE "SlotName" = 'gabi_projection'
                    """)
                .FirstOrDefaultAsync(ct);
            return result;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "ProjectionLagMonitor.GetLagBytesAsync failed; assuming no lag");
            return 0;
        }
    }

    public bool IsCatchingUp(long lagBytes) => lagBytes > CatchUpThresholdBytes;
}
