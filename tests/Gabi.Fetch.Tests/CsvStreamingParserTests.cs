using System.Text;
using Gabi.Contracts.Fetch;
using Gabi.Fetch;
using Xunit;

namespace Gabi.Fetch.Tests;

public class CsvStreamingParserTests
{
    [Fact]
    public async Task ParseRowsAsync_QuotedMultilineField_ParsesSingleLogicalRow()
    {
        var csv = string.Join("\n", new[]
        {
            "id|title|content",
            "1|\"Doc\"|\"line1",
            "line2\"",
        });

        using var stream = new MemoryStream(Encoding.UTF8.GetBytes(csv));
        var parser = new CsvStreamingParser();

        var rows = new List<CsvRow>();
        await foreach (var row in parser.ParseRowsAsync(stream, new CsvFormatConfig()))
        {
            rows.Add(row);
        }

        Assert.Single(rows);
        Assert.Equal("1", rows[0].Fields["id"]);
        Assert.Equal("Doc", rows[0].Fields["title"]);
        Assert.Equal("line1\nline2", rows[0].Fields["content"]);
    }

    [Fact]
    public async Task ParseRowsAsync_VeryLargeSingleFieldAcrossInternalBuffers_ParsesRow()
    {
        var largeField = new string('x', 20_000);
        var csv = $"id|content\n1|\"{largeField}\"\n";

        using var stream = new MemoryStream(Encoding.UTF8.GetBytes(csv));
        var parser = new CsvStreamingParser();

        var rows = new List<CsvRow>();
        await foreach (var row in parser.ParseRowsAsync(stream, new CsvFormatConfig()))
        {
            rows.Add(row);
        }

        Assert.Single(rows);
        Assert.Equal("1", rows[0].Fields["id"]);
        Assert.Equal(largeField, rows[0].Fields["content"]);
    }

    [Fact]
    public async Task ParseRowsAsync_FieldExceedsLimit_TruncatesAndAddsWarning()
    {
        var csv = "id|content\n1|abcdefghijklmnopqrstuvwxyz\n";

        using var stream = new MemoryStream(Encoding.UTF8.GetBytes(csv));
        var parser = new CsvStreamingParser(maxFieldLength: 10);

        var rows = new List<CsvRow>();
        await foreach (var row in parser.ParseRowsAsync(stream, new CsvFormatConfig()))
        {
            rows.Add(row);
        }

        Assert.Single(rows);
        Assert.Equal("abcdefghij", rows[0].Fields["content"]);
        Assert.Contains(rows[0].Warnings, warning => warning.Contains("truncated", StringComparison.OrdinalIgnoreCase));
    }
}
