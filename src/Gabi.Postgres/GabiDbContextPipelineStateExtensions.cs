using Gabi.Contracts.Common;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Postgres;

/// <summary>
/// Extension methods for pipeline state checks (pause/stop) used by job executors.
/// </summary>
public static class GabiDbContextPipelineStateExtensions
{
    /// <summary>
    /// Returns true if the source is paused or stopped; jobs should exit gracefully.
    /// </summary>
    public static async Task<bool> IsSourcePausedOrStoppedAsync(
        this GabiDbContext context,
        string sourceId,
        CancellationToken ct = default)
    {
        if (string.IsNullOrEmpty(sourceId))
            return false;

        var state = await context.SourcePipelineStates
            .AsNoTracking()
            .Where(s => s.SourceId == sourceId)
            .Select(s => s.State)
            .FirstOrDefaultAsync(ct);

        return state is Status.Paused or Status.Stopped;
    }
}
