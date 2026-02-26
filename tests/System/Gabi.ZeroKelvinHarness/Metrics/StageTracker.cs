using Gabi.ZeroKelvinHarness.Models;

namespace Gabi.ZeroKelvinHarness.Metrics;

/// <summary>
/// Counts documents per stage via direct SQL. No EF overhead.
/// </summary>
public static class StageTracker
{
    /// <summary>
    /// Returns stage name -> count. Keys: sources_seeded, discovered_links, fetch_items_pending, fetch_items_completed, documents_pending, documents_completed, embed_jobs.
    /// </summary>
    public static async Task<Dictionary<string, int>> GetStageCountsAsync(string connectionString, string? sourceId, CancellationToken ct = default)
    {
        // source_registry uses "Id" for the source key; other tables use "SourceId"
        var sourceRegistryFilter = string.IsNullOrEmpty(sourceId) ? "" : " WHERE \"Id\" = @sid";
        var sourceFilter = string.IsNullOrEmpty(sourceId) ? "" : " WHERE \"SourceId\" = @sid";
        var sourceAnd = string.IsNullOrEmpty(sourceId) ? "" : " AND \"SourceId\" = @sid";

        await using var conn = new Npgsql.NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct).ConfigureAwait(false);

        var result = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);

        async Task<int> ScalarAsync(string sql, CancellationToken t)
        {
            await using var cmd = conn.CreateCommand();
            cmd.CommandText = sql;
            if (!string.IsNullOrEmpty(sourceId))
                cmd.Parameters.AddWithValue("sid", sourceId);
            var o = await cmd.ExecuteScalarAsync(t).ConfigureAwait(false);
            return o is DBNull || o == null ? 0 : Convert.ToInt32(o);
        }

        result["sources_seeded"] = await ScalarAsync("SELECT COUNT(*) FROM source_registry" + sourceRegistryFilter, ct).ConfigureAwait(false);
        result["discovered_links"] = await ScalarAsync("SELECT COUNT(*) FROM discovered_links" + sourceFilter, ct).ConfigureAwait(false);
        result["fetch_items_pending"] = await ScalarAsync("SELECT COUNT(*) FROM fetch_items WHERE \"Status\" = 'pending'" + sourceAnd, ct).ConfigureAwait(false);
        result["fetch_items_completed"] = await ScalarAsync("SELECT COUNT(*) FROM fetch_items WHERE \"Status\" IN ('completed','skipped_format','skipped_unchanged','capped','failed')" + sourceAnd, ct).ConfigureAwait(false);
        result["documents_pending"] = await ScalarAsync("SELECT COUNT(*) FROM documents WHERE \"Status\" = 'pending'" + sourceAnd, ct).ConfigureAwait(false);
        result["documents_completed"] = await ScalarAsync("SELECT COUNT(*) FROM documents WHERE \"Status\" = 'completed'" + sourceAnd, ct).ConfigureAwait(false);
        result["embed_jobs"] = await ScalarAsync("SELECT COUNT(*) FROM job_registry WHERE \"JobType\" = 'embed_and_index'" + sourceAnd, ct).ConfigureAwait(false);

        return result;
    }
}
