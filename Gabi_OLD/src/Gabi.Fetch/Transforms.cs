using System.Globalization;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;

namespace Gabi.Fetch;

/// <summary>
/// Transform functions for field mapping.
/// Each transform takes a string and returns a transformed string.
/// </summary>
public static class Transforms
{
    private static readonly Regex HtmlTagRegex = new(@"<[^>]+>", RegexOptions.Compiled);
    private static readonly Regex WhitespaceRegex = new(@"\s+", RegexOptions.Compiled);

    /// <summary>
    /// Strip surrounding quotes from a string.
    /// "text" → text
    /// </summary>
    public static string StripQuotes(string? value)
    {
        if (string.IsNullOrEmpty(value))
            return string.Empty;

        var trimmed = value.Trim();
        
        if (trimmed.Length >= 2 && 
            trimmed[0] == '"' && trimmed[^1] == '"')
        {
            return trimmed[1..^1];
        }

        return trimmed;
    }

    /// <summary>
    /// Strip HTML tags from a string.
    /// &lt;p&gt;text&lt;/p&gt; → text
    /// </summary>
    public static string StripHtml(string? value)
    {
        if (string.IsNullOrEmpty(value))
            return string.Empty;

        var decoded = WebUtility.HtmlDecode(value);
        return HtmlTagRegex.Replace(decoded, string.Empty);
    }

    /// <summary>
    /// Strip quotes and then HTML tags.
    /// </summary>
    public static string StripQuotesAndHtml(string? value)
    {
        return StripHtml(StripQuotes(value));
    }

    /// <summary>
    /// Normalize whitespace (collapse multiple spaces/newlines to single space).
    /// "a   b\n\nc" → "a b c"
    /// </summary>
    public static string NormalizeWhitespace(string? value)
    {
        if (string.IsNullOrEmpty(value))
            return string.Empty;

        return WhitespaceRegex.Replace(value, " ").Trim();
    }

    /// <summary>
    /// Convert to integer (preserves original if not parseable).
    /// "123" → "123" (stored as string for metadata)
    /// </summary>
    public static string ToInteger(string? value)
    {
        if (string.IsNullOrEmpty(value))
            return string.Empty;

        var trimmed = value.Trim();
        
        if (int.TryParse(trimmed, out var result))
            return result.ToString(CultureInfo.InvariantCulture);

        return trimmed;
    }

    /// <summary>
    /// Convert to float (preserves original if not parseable).
    /// </summary>
    public static string ToFloat(string? value)
    {
        if (string.IsNullOrEmpty(value))
            return string.Empty;

        var trimmed = value.Trim();
        
        if (double.TryParse(trimmed, NumberStyles.Any, CultureInfo.InvariantCulture, out var result))
            return result.ToString(CultureInfo.InvariantCulture);

        return trimmed;
    }

    /// <summary>
    /// Convert to ISO date format.
    /// "2024-01-15" → "2024-01-15"
    /// "15/01/2024" → "2024-01-15" (DD/MM/YYYY)
    /// </summary>
    public static string ToDate(string? value)
    {
        if (string.IsNullOrEmpty(value))
            return string.Empty;

        var trimmed = value.Trim();

        if (DateTime.TryParseExact(trimmed, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out _))
            return trimmed;

        if (DateTime.TryParseExact(trimmed, "dd/MM/yyyy", CultureInfo.InvariantCulture, DateTimeStyles.None, out var brDate))
            return brDate.ToString("yyyy-MM-dd");

        if (DateTime.TryParse(trimmed, CultureInfo.InvariantCulture, DateTimeStyles.None, out var parsedDate))
            return parsedDate.ToString("yyyy-MM-dd");

        return trimmed;
    }

    /// <summary>
    /// Convert to uppercase.
    /// </summary>
    public static string Uppercase(string? value)
    {
        if (string.IsNullOrEmpty(value))
            return string.Empty;

        return value.ToUpperInvariant();
    }

    /// <summary>
    /// Convert to lowercase.
    /// </summary>
    public static string Lowercase(string? value)
    {
        if (string.IsNullOrEmpty(value))
            return string.Empty;

        return value.ToLowerInvariant();
    }

    /// <summary>
    /// Convert URL to slug (for document IDs).
    /// </summary>
    public static string UrlToSlug(string? value)
    {
        if (string.IsNullOrEmpty(value))
            return string.Empty;

        var slug = value.ToLowerInvariant();
        slug = Regex.Replace(slug, @"[^a-z0-9\-_]", "-");
        slug = Regex.Replace(slug, @"-+", "-");
        return slug.Trim('-');
    }

    /// <summary>
    /// Apply a transform by name.
    /// </summary>
    public static string Apply(string? value, string transformName)
    {
        if (string.IsNullOrEmpty(value))
            return string.Empty;

        return transformName.ToLowerInvariant() switch
        {
            "strip_quotes" => StripQuotes(value),
            "strip_html" => StripHtml(value),
            "strip_quotes_and_html" => StripQuotesAndHtml(value),
            "normalize_whitespace" => NormalizeWhitespace(value),
            "to_integer" => ToInteger(value),
            "to_float" => ToFloat(value),
            "to_date" => ToDate(value),
            "uppercase" => Uppercase(value),
            "lowercase" => Lowercase(value),
            "url_to_slug" => UrlToSlug(value),
            _ => value
        };
    }

    /// <summary>
    /// Apply multiple transforms in sequence.
    /// </summary>
    public static string ApplyChain(string? value, IEnumerable<string> transformNames)
    {
        var result = value ?? string.Empty;
        
        foreach (var transform in transformNames)
        {
            result = Apply(result, transform);
        }

        return result;
    }
}
