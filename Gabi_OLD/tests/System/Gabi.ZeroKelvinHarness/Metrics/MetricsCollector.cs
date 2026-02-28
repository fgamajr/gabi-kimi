using System.Diagnostics;

namespace Gabi.ZeroKelvinHarness.Metrics;

/// <summary>
/// Collects runtime metrics: duration, peak memory (process), retries, DLQ entries via SQL.
/// </summary>
public static class MetricsCollector
{
    /// <summary>
    /// Returns current process working set in MB (for in-process Worker).
    /// </summary>
    public static double GetCurrentProcessMemoryMb()
    {
        using var proc = Process.GetCurrentProcess();
        return proc.WorkingSet64 / (1024.0 * 1024.0);
    }

    /// <summary>
    /// Returns count of job_registry rows with status failed (proxy for retries/failures).
    /// Hangfire retry count would require querying hangfire.job.
    /// </summary>
    public static async Task<int> GetRetriesAsync(string connectionString, CancellationToken ct = default)
    {
        await using var conn = new Npgsql.NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct).ConfigureAwait(false);
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = "SELECT COUNT(*) FROM job_registry WHERE \"Status\" = 'failed'";
        var o = await cmd.ExecuteScalarAsync(ct).ConfigureAwait(false);
        return o is DBNull || o == null ? 0 : Convert.ToInt32(o);
    }

    /// <summary>
    /// Returns DLQ entry count.
    /// </summary>
    public static async Task<int> GetDlqEntriesAsync(string connectionString, CancellationToken ct = default)
    {
        await using var conn = new Npgsql.NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct).ConfigureAwait(false);
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = "SELECT COUNT(*) FROM dlq_entries";
        try
        {
            var o = await cmd.ExecuteScalarAsync(ct).ConfigureAwait(false);
            return o is DBNull || o == null ? 0 : Convert.ToInt32(o);
        }
        catch
        {
            return 0;
        }
    }
}
