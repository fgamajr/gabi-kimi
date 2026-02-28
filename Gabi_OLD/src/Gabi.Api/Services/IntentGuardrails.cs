using System.Text.Json;

namespace Gabi.Api.Services;

public static class IntentGuardrails
{
    public const string NormaVigente = "norma_vigente";
    public const string HistoricoLegislativo = "historico_legislativo";
    public const string Proposicao = "proposicao";
    public const string NormaEspecifica = "norma_especifica";

    public static bool IsKnownIntent(string? intent)
    {
        if (string.IsNullOrWhiteSpace(intent))
            return false;

        return intent.Equals(NormaVigente, StringComparison.OrdinalIgnoreCase)
            || intent.Equals(HistoricoLegislativo, StringComparison.OrdinalIgnoreCase)
            || intent.Equals(Proposicao, StringComparison.OrdinalIgnoreCase)
            || intent.Equals(NormaEspecifica, StringComparison.OrdinalIgnoreCase);
    }

    public static bool Allows(string? intent, Dictionary<string, object>? metadata)
    {
        if (string.IsNullOrWhiteSpace(intent) || !IsKnownIntent(intent))
            return true;

        var documentKind = ReadMetadataString(metadata, "document_kind");
        var normativeForce = ReadMetadataString(metadata, "normative_force");

        if (intent.Equals(NormaVigente, StringComparison.OrdinalIgnoreCase))
        {
            return string.Equals(documentKind, "norma", StringComparison.OrdinalIgnoreCase)
                && !string.Equals(normativeForce, "revogada", StringComparison.OrdinalIgnoreCase);
        }

        if (intent.Equals(HistoricoLegislativo, StringComparison.OrdinalIgnoreCase)
            || intent.Equals(Proposicao, StringComparison.OrdinalIgnoreCase))
        {
            return string.Equals(documentKind, "proposicao", StringComparison.OrdinalIgnoreCase);
        }

        if (intent.Equals(NormaEspecifica, StringComparison.OrdinalIgnoreCase))
            return string.Equals(documentKind, "norma", StringComparison.OrdinalIgnoreCase);

        return true;
    }

    private static string? ReadMetadataString(Dictionary<string, object>? metadata, string key)
    {
        if (metadata == null || !metadata.TryGetValue(key, out var value) || value == null)
            return null;

        if (value is string s)
            return s;

        if (value is JsonElement element)
        {
            return element.ValueKind switch
            {
                JsonValueKind.String => element.GetString(),
                JsonValueKind.Number => element.GetRawText(),
                JsonValueKind.True => "true",
                JsonValueKind.False => "false",
                _ => null
            };
        }

        return value.ToString();
    }
}
