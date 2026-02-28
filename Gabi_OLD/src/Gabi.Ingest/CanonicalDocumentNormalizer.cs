using System.Text.RegularExpressions;
using Gabi.Contracts.Ingest;

namespace Gabi.Ingest;

public sealed partial class CanonicalDocumentNormalizer : ICanonicalDocumentNormalizer
{
    [GeneratedRegex(@"\r\n?", RegexOptions.Compiled)]
    private static partial Regex NewlineRegex();

    [GeneratedRegex(@"[ \t]{2,}", RegexOptions.Compiled)]
    private static partial Regex MultiSpaceRegex();

    [GeneratedRegex(@"\n{3,}", RegexOptions.Compiled)]
    private static partial Regex MultiBlankRegex();

    public CanonicalTextDocument Normalize(CanonicalTextDocument document)
    {
        ArgumentNullException.ThrowIfNull(document);

        var normalizedTitle = NormalizeText(document.Title);
        var normalizedContent = NormalizeText(document.Content);
        if (string.IsNullOrWhiteSpace(normalizedContent) && !string.IsNullOrWhiteSpace(normalizedTitle))
            normalizedContent = normalizedTitle;

        var metadata = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
        foreach (var item in document.Metadata)
            metadata[item.Key] = item.Value;

        metadata["canonical_version"] = "v1";
        metadata["canonical_normalized_at"] = DateTime.UtcNow.ToString("O");
        metadata["canonical_content_type"] = string.IsNullOrWhiteSpace(document.ContentType) ? "text/plain" : document.ContentType;
        metadata["canonical_language"] = string.IsNullOrWhiteSpace(document.Language) ? "pt-BR" : document.Language;

        return document with
        {
            Title = string.IsNullOrWhiteSpace(normalizedTitle) ? null : normalizedTitle,
            Content = normalizedContent,
            ContentType = string.IsNullOrWhiteSpace(document.ContentType) ? "text/plain" : document.ContentType,
            Language = string.IsNullOrWhiteSpace(document.Language) ? "pt-BR" : document.Language,
            Metadata = metadata
        };
    }

    private static string NormalizeText(string? input)
    {
        if (string.IsNullOrWhiteSpace(input))
            return string.Empty;

        var text = NewlineRegex().Replace(input, "\n");
        text = MultiSpaceRegex().Replace(text, " ");
        text = MultiBlankRegex().Replace(text, "\n\n");
        return text.Trim();
    }
}
