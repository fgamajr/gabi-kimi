namespace Gabi.Contracts.Transform;

/// <summary>
/// Transformações disponíveis para campos.
/// Assinatura: (value: string) -> string
/// Se valor de entrada for null, a transform NÃO é chamada.
/// </summary>
public static class AvailableTransforms
{
    /// <summary>Lista de transforms disponíveis.</summary>
    public static readonly IReadOnlySet<string> All = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        "strip_quotes",
        "strip_quotes_and_html",
        "strip_html",
        "to_integer",
        "to_float",
        "to_date",
        "normalize_whitespace",
        "uppercase",
        "lowercase",
        "url_to_slug",
        "parse_boolean"
    };
}
