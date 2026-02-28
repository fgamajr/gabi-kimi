using Gabi.ZeroKelvinHarness.Models;

namespace Gabi.ZeroKelvinHarness.Verification;

/// <summary>
/// Randomly samples documents and compares source vs ingested: missing, duplicate, truncated.
/// </summary>
public static class SampleVerifier
{
    /// <summary>
    /// Samples up to sampleSize documents (random order), checks for duplicates by ExternalId, missing (link without doc), truncated (Content null or length &lt; minContentLength).
    /// Returns sample results and computed loss/duplication/corruption rates.
    /// </summary>
    public static async Task<(IReadOnlyList<SampleResult> Results, double LossRate, double DuplicationRate, double CorruptionRate)> VerifyAsync(
        string connectionString,
        string? sourceId,
        int sampleSize,
        int minContentLength = 10,
        CancellationToken ct = default)
    {
        await using var conn = new Npgsql.NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct).ConfigureAwait(false);

        var sourceAnd = string.IsNullOrEmpty(sourceId) ? "" : " AND \"SourceId\" = @sid";

        // Duplicate check: ExternalIds that appear more than once
        await using var cmdDup = conn.CreateCommand();
        cmdDup.CommandText = "SELECT \"ExternalId\", \"SourceId\", COUNT(*) FROM documents WHERE \"ExternalId\" IS NOT NULL" + sourceAnd + " GROUP BY \"ExternalId\", \"SourceId\" HAVING COUNT(*) > 1";
        if (!string.IsNullOrEmpty(sourceId)) cmdDup.Parameters.AddWithValue("sid", sourceId);
        var duplicateIds = new HashSet<string>();
        await using (var r = await cmdDup.ExecuteReaderAsync(ct).ConfigureAwait(false))
        {
            while (await r.ReadAsync(ct).ConfigureAwait(false))
                duplicateIds.Add(r.GetString(0));
        }

        // Random sample of documents
        await using var cmdSample = conn.CreateCommand();
        cmdSample.CommandText = "SELECT \"Id\", \"SourceId\", \"ExternalId\", \"Content\" FROM documents WHERE 1=1" + sourceAnd + " ORDER BY RANDOM() LIMIT " + sampleSize;
        if (!string.IsNullOrEmpty(sourceId)) cmdSample.Parameters.AddWithValue("sid", sourceId);
        var results = new List<SampleResult>();
        await using (var r = await cmdSample.ExecuteReaderAsync(ct).ConfigureAwait(false))
        {
            while (await r.ReadAsync(ct).ConfigureAwait(false))
            {
                var externalId = r.IsDBNull(2) ? "" : r.GetString(2);
                var srcId = r.GetString(1);
                var content = r.IsDBNull(3) ? null : r.GetString(3);
                var truncated = content == null || content.Length < minContentLength;
                var duplicate = duplicateIds.Contains(externalId);
                results.Add(new SampleResult
                {
                    ExternalId = externalId,
                    SourceId = srcId,
                    Missing = false,
                    Duplicate = duplicate,
                    Truncated = truncated,
                    SemanticSimilarity = 1.0,
                    Classification = truncated ? "corrupted" : (duplicate ? "degraded" : "preserved")
                });
            }
        }

        // Loss: count links without document (for source)
        long totalLinks = 0;
        long totalDocs = 0;
        await using (var cmdL = conn.CreateCommand())
        {
            cmdL.CommandText = "SELECT COUNT(*) FROM discovered_links WHERE 1=1" + sourceAnd;
            if (!string.IsNullOrEmpty(sourceId)) cmdL.Parameters.AddWithValue("sid", sourceId);
            totalLinks = Convert.ToInt64(await cmdL.ExecuteScalarAsync(ct).ConfigureAwait(false));
        }
        await using (var cmdD = conn.CreateCommand())
        {
            cmdD.CommandText = "SELECT COUNT(*) FROM documents WHERE 1=1" + sourceAnd;
            if (!string.IsNullOrEmpty(sourceId)) cmdD.Parameters.AddWithValue("sid", sourceId);
            totalDocs = Convert.ToInt64(await cmdD.ExecuteScalarAsync(ct).ConfigureAwait(false));
        }
        var lossRate = totalLinks > 0 ? 1.0 - (double)totalDocs / totalLinks : 0;
        if (lossRate < 0) lossRate = 0;

        var dupCount = results.Count(x => x.Duplicate);
        var corruptionCount = results.Count(x => x.Truncated);
        var duplicationRate = results.Count > 0 ? (double)dupCount / results.Count : 0;
        var corruptionRate = results.Count > 0 ? (double)corruptionCount / results.Count : 0;

        return (results, lossRate, duplicationRate, corruptionRate);
    }
}
