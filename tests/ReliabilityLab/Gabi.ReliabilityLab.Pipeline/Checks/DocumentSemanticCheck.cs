using Gabi.ReliabilityLab.Environment;
using Gabi.ReliabilityLab.Verification;

namespace Gabi.ReliabilityLab.Pipeline.Checks;

public sealed class DocumentSemanticCheck : ISemanticCheck
{
    private readonly string? _sourceId;
    private readonly int _sampleSize;

    public DocumentSemanticCheck(string? sourceId, int sampleSize) { _sourceId = sourceId; _sampleSize = sampleSize; }
    public string Name => "DocumentSemantic";

    public async Task<VerificationResult> CheckAsync(EnvironmentConnectionInfo env, CancellationToken ct = default)
    {
        await using var conn = new Npgsql.NpgsqlConnection(env.PostgreSqlConnectionString);
        await conn.OpenAsync(ct).ConfigureAwait(false);
        var sourceAnd = string.IsNullOrEmpty(_sourceId) ? "" : " AND \"SourceId\" = @sid";
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = "SELECT \"Content\" FROM documents WHERE \"Content\" IS NOT NULL" + sourceAnd + " ORDER BY RANDOM() LIMIT " + _sampleSize;
        if (!string.IsNullOrEmpty(_sourceId)) cmd.Parameters.AddWithValue("sid", _sourceId);
        var count = 0;
        var truncated = 0;
        await using (var r = await cmd.ExecuteReaderAsync(ct).ConfigureAwait(false))
            while (await r.ReadAsync(ct).ConfigureAwait(false)) { count++; if (!r.IsDBNull(0) && r.GetString(0).Length < 10) truncated++; }
        var corruptionRate = count > 0 ? (double)truncated / count : 0;
        var passed = corruptionRate < 0.05;
        return new VerificationResult { CheckName = Name, Passed = passed, Severity = passed ? VerificationSeverity.Info : VerificationSeverity.Error, Message = $"CorruptionRate={corruptionRate:F4}" };
    }
}
