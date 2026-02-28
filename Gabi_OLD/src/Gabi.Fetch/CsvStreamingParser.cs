using System.Text;
using Gabi.Contracts.Fetch;
using Microsoft.Extensions.Logging;

namespace Gabi.Fetch;

/// <summary>
/// Streaming CSV parser that processes row-by-row without loading entire file in memory.
/// Handles pipe-delimited format (TCU standard: | delimiter, " quotes).
/// </summary>
public class CsvStreamingParser
{
    private readonly ILogger<CsvStreamingParser>? _logger;
    private readonly int _maxFieldLength;

    public CsvStreamingParser(ILogger<CsvStreamingParser>? logger = null, int maxFieldLength = 262_144)
    {
        _logger = logger;
        _maxFieldLength = maxFieldLength > 0 ? maxFieldLength : 262_144;
    }

    /// <summary>
    /// Parse CSV stream row-by-row.
    /// </summary>
    public async IAsyncEnumerable<CsvRow> ParseRowsAsync(
        Stream stream,
        CsvFormatConfig config,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct = default)
    {
        var encoding = Encoding.GetEncoding(config.Encoding ?? "utf-8");
        // Read fixed-size chunks and parse in-place to avoid unbounded line allocations.
        using var reader = new StreamReader(stream, encoding, detectEncodingFromByteOrderMarks: true, bufferSize: 4096, leaveOpen: true);

        var delimiter = config.Delimiter?.FirstOrDefault() ?? '|';
        var quoteChar = config.QuoteChar?.FirstOrDefault() ?? '"';
        var rowNumber = 0;
        string[]? headers = null;
        var warnings = new List<string>();
        var currentFields = new List<string>(32);
        var currentField = new StringBuilder();
        var inQuotes = false;
        var pendingQuoteInQuotedField = false;
        var fieldWasTruncated = false;
        var charBuffer = new char[4096];

        void AppendToCurrentField(char ch)
        {
            if (currentField.Length < _maxFieldLength)
            {
                currentField.Append(ch);
                return;
            }

            if (fieldWasTruncated)
                return;

            fieldWasTruncated = true;
            warnings.Add($"Field truncated at {_maxFieldLength} characters");
        }

        while (true)
        {
            var charsRead = await reader.ReadAsync(charBuffer.AsMemory(0, charBuffer.Length), ct);
            if (charsRead == 0)
                break;

            for (var i = 0; i < charsRead; i++)
            {
                var c = charBuffer[i];

                if (inQuotes)
                {
                    if (pendingQuoteInQuotedField)
                    {
                        if (c == quoteChar)
                        {
                            AppendToCurrentField(quoteChar);
                            pendingQuoteInQuotedField = false;
                            continue;
                        }

                        inQuotes = false;
                        pendingQuoteInQuotedField = false;
                        // Fall through and re-process current char outside quotes.
                    }

                    if (inQuotes)
                    {
                        if (c == quoteChar)
                        {
                            pendingQuoteInQuotedField = true;
                        }
                        else
                        {
                            AppendToCurrentField(c);
                        }
                        continue;
                    }
                }

                if (c == delimiter)
                {
                    currentFields.Add(currentField.ToString());
                    currentField.Clear();
                    fieldWasTruncated = false;
                    continue;
                }

                if (c == quoteChar)
                {
                    inQuotes = true;
                    continue;
                }

                if (c == '\r')
                    continue;

                if (c == '\n')
                {
                    currentFields.Add(currentField.ToString());
                    currentField.Clear();
                    fieldWasTruncated = false;
                    rowNumber++;

                    if (currentFields.Count == 1 && string.IsNullOrWhiteSpace(currentFields[0]))
                    {
                        currentFields.Clear();
                        continue;
                    }

                    var fields = currentFields.ToArray();
                    currentFields.Clear();

                    if (headers == null)
                    {
                        headers = fields;
                        _logger?.LogDebug("CSV headers: {Headers}", string.Join(", ", headers));
                        continue;
                    }

                    if (fields.Length != headers.Length)
                    {
                        warnings.Add($"Row {rowNumber}: field count mismatch ({fields.Length} vs {headers.Length} headers)");
                        _logger?.LogWarning(
                            "CSV row {RowNumber}: field count mismatch ({Actual} vs {Expected} headers)",
                            rowNumber, fields.Length, headers.Length);
                        continue;
                    }

                    var fieldDict = new Dictionary<string, string>(headers.Length);
                    for (var headerIndex = 0; headerIndex < headers.Length; headerIndex++)
                    {
                        fieldDict[headers[headerIndex]] = fields[headerIndex] ?? string.Empty;
                    }

                    yield return new CsvRow(rowNumber, fieldDict, new List<string>(warnings));
                    warnings.Clear();
                    continue;
                }

                AppendToCurrentField(c);
            }
        }

        if (pendingQuoteInQuotedField)
        {
            inQuotes = false;
            pendingQuoteInQuotedField = false;
        }

        if (currentField.Length > 0 || currentFields.Count > 0)
        {
            currentFields.Add(currentField.ToString());
            currentField.Clear();
            fieldWasTruncated = false;
            rowNumber++;

            var fields = currentFields.ToArray();

            if (headers == null)
            {
                headers = fields;
                _logger?.LogDebug("CSV headers: {Headers}", string.Join(", ", headers));
                yield break;
            }

            if (fields.Length != headers.Length)
            {
                warnings.Add($"Row {rowNumber}: field count mismatch ({fields.Length} vs {headers.Length} headers)");
                _logger?.LogWarning(
                    "CSV row {RowNumber}: field count mismatch ({Actual} vs {Expected} headers)",
                    rowNumber, fields.Length, headers.Length);
                yield break;
            }

            var fieldDict = new Dictionary<string, string>(headers.Length);
            for (var headerIndex = 0; headerIndex < headers.Length; headerIndex++)
            {
                fieldDict[headers[headerIndex]] = fields[headerIndex] ?? string.Empty;
            }

            yield return new CsvRow(rowNumber, fieldDict, new List<string>(warnings));
        }
    }
}

/// <summary>
/// Represents a parsed CSV row.
/// </summary>
public record CsvRow(
    int RowNumber,
    Dictionary<string, string> Fields,
    List<string> Warnings
);
