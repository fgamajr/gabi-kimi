using Gabi.ReliabilityLab.Environment;
using Gabi.ReliabilityLab.Verification;

namespace Gabi.ReliabilityLab.Pipeline.Checks;

public sealed class PipelineIntegrityCheck : IIntegrityCheck
{
    private readonly string? _sourceId;
    private readonly int _sampleSize;

    public PipelineIntegrityCheck(string? sourceId, int sampleSize) { _sourceId = sourceId; _sampleSize = sampleSize; }
    public string Name => "PipelineIntegrity";

    public async Task<VerificationResult> CheckAsync(EnvironmentConnectionInfo env, CancellationToken ct = default)
    {
        await using var conn = new Npgsql.NpgsqlConnection(env.PostgreSqlConnectionString);
        await conn.OpenAsync(ct).ConfigureAwait(false);
        var sourceAnd = string.IsNullOrEmpty(_sourceId) ? "" : " AND \"SourceId\" = @sid";
        long totalLinks = 0, totalDocs = 0;
        await using (var cmd = conn.CreateCommand())
        {
            cmd.CommandText = "SELECT COUNT(*) FROM discovered_links WHERE 1=1" + sourceAnd;
            if (!string.IsNullOrEmpty(_sourceId)) cmd.Parameters.AddWithValue("sid", _sourceId);
            totalLinks = Convert.ToInt64(await cmd.ExecuteScalarAsync(ct).ConfigureAwait(false));
        }
        await using (var cmd2 = conn.CreateCommand())
        {
            cmd2.CommandText = "SELECT COUNT(*) FROM documents WHERE 1=1" + sourceAnd;
            if (!string.IsNullOrEmpty(_sourceId)) cmd2.Parameters.AddWithValue("sid", _sourceId);
            totalDocs = Convert.ToInt64(await cmd2.ExecuteScalarAsync(ct).ConfigureAwait(false));
        }
        var lossRate = totalLinks > 0 ? 1.0 - (double)totalDocs / totalLinks : 0;
        var passed = lossRate < 0.01;
        return new VerificationResult { CheckName = Name, Passed = passed, Severity = passed ? VerificationSeverity.Info : VerificationSeverity.Error, Message = "LossRate " + lossRate.ToString("F4") };
    }
}
