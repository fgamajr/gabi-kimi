using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Gabi.Fetch;

namespace Gabi.Worker.Jobs.Fetch;

internal static class FetchContentConverter
{
    private static readonly Regex HtmlScriptStyleRegex = new(@"<(script|style)\b[^>]*>.*?</\1>", RegexOptions.Compiled | RegexOptions.IgnoreCase | RegexOptions.Singleline);
    private static readonly Regex HtmlTitleRegex = new(@"<title\b[^>]*>(?<title>.*?)</title>", RegexOptions.Compiled | RegexOptions.IgnoreCase | RegexOptions.Singleline);
    private static readonly Regex PdfLiteralTextRegex = new(@"\((?<text>(?:\\.|[^\\)])+)\)\s*Tj", RegexOptions.Compiled);
    private static readonly Regex PdfArrayTextRegex = new(@"\[(?<body>.*?)\]\s*TJ", RegexOptions.Compiled | RegexOptions.Singleline);
    private static readonly Regex PdfArrayLiteralRegex = new(@"\((?<text>(?:\\.|[^\\)])+)\)", RegexOptions.Compiled);
    private static readonly Regex PrintableSequenceRegex = new(@"[A-Za-zÀ-ÖØ-öø-ÿ0-9][A-Za-zÀ-ÖØ-öø-ÿ0-9\s,.;:()/%\-]{30,}", RegexOptions.Compiled);

    private const int DefaultMaxConvertedTextChars = 100_000;

    internal static LinkOnlyConversionResult ConvertLinkOnlyPayload(
        byte[] bytes,
        string strategy,
        string? contentType,
        string url)
    {
        return strategy switch
        {
            "html_to_text" => ConvertHtml(bytes, contentType),
            "json_to_text" => ConvertJson(bytes),
            "pdf_to_text_heuristic" => ConvertPdfHeuristic(bytes),
            "plain_text" => ConvertPlainText(bytes, contentType),
            _ => new LinkOnlyConversionResult(false, null, null, new Dictionary<string, object>(), $"unsupported_converter={strategy}")
        };
    }

    internal static LinkOnlyConversionResult ConvertPlainText(byte[] bytes, string? contentType)
    {
        var text = DecodeBytesToString(bytes, contentType);
        text = TruncateText(Transforms.NormalizeWhitespace(text));
        return new LinkOnlyConversionResult(
            true,
            BuildTitleFromText(text),
            text,
            new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase));
    }

    internal static LinkOnlyConversionResult ConvertHtml(byte[] bytes, string? contentType)
    {
        var html = DecodeBytesToString(bytes, contentType);
        var titleMatch = HtmlTitleRegex.Match(html);
        var title = titleMatch.Success
            ? Transforms.NormalizeWhitespace(Transforms.StripHtml(WebUtility.HtmlDecode(titleMatch.Groups["title"].Value)))
            : null;

        var cleaned = HtmlScriptStyleRegex.Replace(html, " ");
        var text = Transforms.NormalizeWhitespace(Transforms.StripHtml(cleaned));
        text = TruncateText(text);

        return new LinkOnlyConversionResult(
            true,
            string.IsNullOrWhiteSpace(title) ? BuildTitleFromText(text) : title,
            text,
            new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase));
    }

    internal static LinkOnlyConversionResult ConvertJson(byte[] bytes)
    {
        try
        {
            using var doc = JsonDocument.Parse(bytes);
            var lines = new List<string>(512);
            var metadata = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            string? title = null;

            CollectJsonText(doc.RootElement, "$", lines, metadata, ref title, maxLines: 2000);
            var text = TruncateText(string.Join("\n", lines));
            title = FirstNonEmpty(
                title,
                metadata.TryGetValue("title", out var titleObj) ? titleObj?.ToString() : null,
                BuildTitleFromText(text));

            return new LinkOnlyConversionResult(true, title, text, metadata);
        }
        catch (Exception ex)
        {
            var raw = DecodeBytesToString(bytes, "application/json");
            if (raw.Contains("<html", StringComparison.OrdinalIgnoreCase)
                || raw.Contains("<!doctype", StringComparison.OrdinalIgnoreCase))
            {
                var fallback = ConvertHtml(bytes, "text/html; charset=utf-8");
                var metadata = new Dictionary<string, object>(fallback.Metadata, StringComparer.OrdinalIgnoreCase)
                {
                    ["json_parse_fallback"] = ex.GetType().Name
                };
                return fallback with { Metadata = metadata };
            }

            var fallbackText = TruncateText(Transforms.NormalizeWhitespace(raw));
            return new LinkOnlyConversionResult(
                true,
                BuildTitleFromText(fallbackText),
                fallbackText,
                new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase)
                {
                    ["json_parse_fallback"] = ex.GetType().Name
                });
        }
    }

    internal static LinkOnlyConversionResult ConvertPdfHeuristic(byte[] bytes)
    {
        try
        {
            var raw = Encoding.Latin1.GetString(bytes);
            var snippets = new List<string>(256);

            foreach (Match match in PdfLiteralTextRegex.Matches(raw))
            {
                var decoded = DecodePdfLiteral(match.Groups["text"].Value);
                var normalized = Transforms.NormalizeWhitespace(decoded);
                if (normalized.Length >= 20)
                    snippets.Add(normalized);
                if (snippets.Count >= 500)
                    break;
            }

            if (snippets.Count < 50)
            {
                foreach (Match match in PdfArrayTextRegex.Matches(raw))
                {
                    foreach (Match literal in PdfArrayLiteralRegex.Matches(match.Groups["body"].Value))
                    {
                        var decoded = DecodePdfLiteral(literal.Groups["text"].Value);
                        var normalized = Transforms.NormalizeWhitespace(decoded);
                        if (normalized.Length >= 20)
                            snippets.Add(normalized);
                        if (snippets.Count >= 500)
                            break;
                    }

                    if (snippets.Count >= 500)
                        break;
                }
            }

            if (snippets.Count == 0)
            {
                foreach (Match match in PrintableSequenceRegex.Matches(raw))
                {
                    var normalized = Transforms.NormalizeWhitespace(match.Value);
                    if (normalized.Length >= 30)
                        snippets.Add(normalized);
                    if (snippets.Count >= 200)
                        break;
                }
            }

            var uniqueSnippets = snippets
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .Take(500)
                .ToList();
            var text = TruncateText(string.Join("\n", uniqueSnippets));

            return new LinkOnlyConversionResult(
                true,
                BuildTitleFromText(text),
                text,
                new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase)
                {
                    ["pdf_extractor"] = "heuristic"
                });
        }
        catch (Exception ex)
        {
            return new LinkOnlyConversionResult(false, null, null, new Dictionary<string, object>(), $"pdf_parse_error={ex.GetType().Name}");
        }
    }

    internal static string DecodePdfLiteral(string value)
    {
        var result = value
            .Replace("\\n", " ")
            .Replace("\\r", " ")
            .Replace("\\t", " ")
            .Replace("\\(", "(")
            .Replace("\\)", ")")
            .Replace("\\\\", "\\");
        return result;
    }

    internal static string DecodeBytesToString(byte[] bytes, string? contentType)
    {
        var charset = TryExtractCharset(contentType);
        if (!string.IsNullOrWhiteSpace(charset))
        {
            try
            {
                return Encoding.GetEncoding(charset!).GetString(bytes);
            }
            catch
            {
                // fallback below
            }
        }

        try
        {
            return Encoding.UTF8.GetString(bytes);
        }
        catch (Exception ex)
        {
            // GEMINI-07: Do not silently decode as Latin1 — that produces mojibake persisted permanently in ES.
            // Reject and let the caller mark the document as failed.
            throw new InvalidOperationException(
                $"Content is not valid UTF-8 and no explicit charset was declared. Rejecting to prevent mojibake. ({bytes.Length} bytes)", ex);
        }
    }

    internal static string? TryExtractCharset(string? contentType)
    {
        if (string.IsNullOrWhiteSpace(contentType))
            return null;

        var marker = "charset=";
        var index = contentType.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
        if (index < 0)
            return null;

        var value = contentType[(index + marker.Length)..].Trim();
        var semicolon = value.IndexOf(';');
        if (semicolon >= 0)
            value = value[..semicolon];
        return value.Trim('"', '\'');
    }

    internal static string TruncateText(string text, int maxChars = DefaultMaxConvertedTextChars)
    {
        if (string.IsNullOrEmpty(text))
            return string.Empty;
        if (text.Length <= maxChars)
            return text;
        return text[..maxChars];
    }

    internal static string? BuildTitleFromText(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return null;
        var firstLine = text.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).FirstOrDefault();
        if (string.IsNullOrWhiteSpace(firstLine))
            return null;
        return firstLine!.Length <= 180 ? firstLine : firstLine[..180];
    }

    internal static void CollectJsonText(
        JsonElement element,
        string path,
        List<string> lines,
        Dictionary<string, object> metadata,
        ref string? title,
        int maxLines)
    {
        if (lines.Count >= maxLines)
            return;

        switch (element.ValueKind)
        {
            case JsonValueKind.Object:
            {
                foreach (var prop in element.EnumerateObject())
                {
                    var nextPath = $"{path}.{prop.Name}";
                    if (prop.Value.ValueKind is JsonValueKind.String or JsonValueKind.Number or JsonValueKind.True or JsonValueKind.False)
                    {
                        var normalized = NormalizeJsonScalar(prop.Value);
                        if (!string.IsNullOrWhiteSpace(normalized))
                        {
                            lines.Add($"{prop.Name}: {normalized}");
                            if (IsTitleKey(prop.Name) && string.IsNullOrWhiteSpace(title))
                                title = normalized;
                        }

                        if (metadata.Count < 100)
                            metadata[prop.Name] = normalized;
                    }
                    else
                    {
                        CollectJsonText(prop.Value, nextPath, lines, metadata, ref title, maxLines);
                    }

                    if (lines.Count >= maxLines)
                        break;
                }
                break;
            }
            case JsonValueKind.Array:
            {
                var index = 0;
                foreach (var item in element.EnumerateArray())
                {
                    CollectJsonText(item, $"{path}[{index}]", lines, metadata, ref title, maxLines);
                    index++;
                    if (lines.Count >= maxLines)
                        break;
                }
                break;
            }
            case JsonValueKind.String:
            case JsonValueKind.Number:
            case JsonValueKind.True:
            case JsonValueKind.False:
            {
                var scalar = NormalizeJsonScalar(element);
                if (!string.IsNullOrWhiteSpace(scalar))
                    lines.Add($"{path}: {scalar}");
                break;
            }
        }
    }

    internal static string NormalizeJsonScalar(JsonElement element)
    {
        var raw = element.ValueKind switch
        {
            JsonValueKind.String => element.GetString() ?? string.Empty,
            JsonValueKind.Number => element.GetRawText(),
            JsonValueKind.True => "true",
            JsonValueKind.False => "false",
            _ => string.Empty
        };
        return TruncateText(Transforms.NormalizeWhitespace(raw), 2000);
    }

    internal static bool IsTitleKey(string key)
    {
        var normalized = key.Trim().ToLowerInvariant();
        return normalized is "title" or "titulo" or "nome" or "ementa" or "normanome";
    }

    internal static string? FirstNonEmpty(params string?[] values)
    {
        foreach (var value in values)
        {
            if (!string.IsNullOrWhiteSpace(value))
                return value;
        }

        return null;
    }
}

internal sealed record LinkOnlyConversionResult(
    bool Success,
    string? Title,
    string? Content,
    IReadOnlyDictionary<string, object> Metadata,
    string? ErrorDetail = null);
