using System.Xml.Linq;
using Xunit;
using Xunit.Abstractions;

namespace Gabi.Discover.Tests.Integration;

/// <summary>
/// Contract tests for LexML SRU API (Gate P0.5).
/// Validates availability and schema before enabling it as a source.
/// </summary>
public class LexmlContractTests
{
    private readonly ITestOutputHelper _output;
    private readonly HttpClient _client;
    private const string BaseUrl = "https://www.lexml.gov.br/busca/SRU";
    private static bool ExternalTestsEnabled =>
        string.Equals(Environment.GetEnvironmentVariable("GABI_RUN_EXTERNAL_TESTS"), "true", StringComparison.OrdinalIgnoreCase);

    public LexmlContractTests(ITestOutputHelper output)
    {
        _output = output;
        _client = new HttpClient();
        // Identify as a respectful bot
        _client.DefaultRequestHeaders.UserAgent.ParseAdd("Gabi-ZeroKelvin-Bot/1.0 (+http://github.com/fgamajr/gabi-kimi)");
    }

    [Fact]
    [Trait("Category", "Integration")]
    [Trait("Category", "External")]
    public async Task Operation_Explain_ReturnsUsingValidXml()
    {
        if (!await CanRunExternalDependencyAsync())
            return;

        // Act
        var response = await _client.GetAsync($"{BaseUrl}?operation=explain");
        var content = await response.Content.ReadAsStringAsync();

        // Assert
        Assert.True(response.IsSuccessStatusCode, $"Expected 200 OK, got {response.StatusCode}");
        
        var doc = XDocument.Parse(content);
        var root = doc.Root;
        
        Assert.NotNull(root);
        // SRU 1.1 explainResponse usually in this namespace or similar
        // We'll just check if it's valid XML and has some expected content
        _output.WriteLine($"Explain root name: {root.Name}");
        Assert.True(root.Name.LocalName.Contains("explain") || root.Name.LocalName.Contains("Explain"), 
            $"Root element should contain 'explain', got '{root.Name.LocalName}'");
    }

    [Fact]
    [Trait("Category", "Integration")]
    [Trait("Category", "External")]
    public async Task Operation_SearchRetrieve_ReturnsResults()
    {
        if (!await CanRunExternalDependencyAsync())
            return;

        // Query for a robust URN (Constitution 1988)
        var query = "urn:lex:br:federal:constituicao:1988";
        var url = $"{BaseUrl}?operation=searchRetrieve&query={query}&maximumRecords=1&recordSchema=lexml";
        
        // Act
        var response = await _client.GetAsync(url);
        var content = await response.Content.ReadAsStringAsync();
        
        // Assert
        Assert.True(response.IsSuccessStatusCode, $"Expected 200 OK, got {response.StatusCode}");
        
        var doc = XDocument.Parse(content);
        XNamespace srw = "http://www.loc.gov/zing/srw/";
        
        var searchRetrieveResponse = doc.Element(srw + "searchRetrieveResponse");
        if (searchRetrieveResponse == null)
        {
            // Fallback: try without namespace or check root
            searchRetrieveResponse = doc.Root;
        }

        Assert.NotNull(searchRetrieveResponse);
        
        var numberOfRecords = searchRetrieveResponse.Element(srw + "numberOfRecords")?.Value;
        _output.WriteLine($"numberOfRecords: {numberOfRecords}");
        
        Assert.NotNull(numberOfRecords);
        Assert.True(int.Parse(numberOfRecords) > 0, "Should find at least one record for CF88");
    }

    [Fact]
    [Trait("Category", "Integration")]
    [Trait("Category", "External")]
    public async Task Pagination_StartRecord_ChangesResultSet()
    {
        if (!await CanRunExternalDependencyAsync())
            return;

        // Query generic "lei" to get many results
        var query = "lei";
        
        // Page 1
        var url1 = $"{BaseUrl}?operation=searchRetrieve&query={query}&startRecord=1&maximumRecords=1&recordSchema=lexml";
        var content1 = await _client.GetStringAsync(url1);
        var doc1 = XDocument.Parse(content1);
        var record1 = ExtractFirstRecordId(doc1);
        
        // Page 2
        var url2 = $"{BaseUrl}?operation=searchRetrieve&query={query}&startRecord=2&maximumRecords=1&recordSchema=lexml";
        var content2 = await _client.GetStringAsync(url2);
        var doc2 = XDocument.Parse(content2);
        var record2 = ExtractFirstRecordId(doc2);
        
        _output.WriteLine($"Record 1: {record1}");
        _output.WriteLine($"Record 2: {record2}");
        
        Assert.NotNull(record1);
        Assert.NotNull(record2);
        Assert.NotEqual(record1, record2);
    }

    [Fact]
    [Trait("Category", "Integration")]
    [Trait("Category", "External")]
    public async Task Schema_ValidateEssentialFields()
    {
        if (!await CanRunExternalDependencyAsync())
            return;

        var query = "urn:lex:br:federal:lei:2023";
        var url = $"{BaseUrl}?operation=searchRetrieve&query={query}&maximumRecords=1&recordSchema=lexml";
        
        var content = await _client.GetStringAsync(url);
        var doc = XDocument.Parse(content);
        XNamespace srw = "http://www.loc.gov/zing/srw/";
        
        var records = doc.Descendants(srw + "record");
        Assert.NotEmpty(records);
        
        var firstRecord = records.First();
        var recordSchema = firstRecord.Element(srw + "recordSchema")?.Value;
        var recordPacking = firstRecord.Element(srw + "recordPacking")?.Value;
        var recordData = firstRecord.Element(srw + "recordData");
        
        Assert.Equal("lexml", recordSchema);
        Assert.Equal("xml", recordPacking);
        Assert.NotNull(recordData);
        
        // Check for URN inside recordData (LexML schema)
        var recordDataString = recordData.ToString();
        Assert.Contains("urn:lex:br", recordDataString);
    }

    private string? ExtractFirstRecordId(XDocument doc)
    {
        // Try to find a specific identifier or just the full record content hash
        XNamespace srw = "http://www.loc.gov/zing/srw/";
        var record = doc.Descendants(srw + "record").FirstOrDefault();
        return record?.ToString();
    }

    private async Task<bool> CanRunExternalDependencyAsync()
    {
        if (!ExternalTestsEnabled)
        {
            _output.WriteLine("Skipping LexML external test: set GABI_RUN_EXTERNAL_TESTS=true to enable.");
            return false;
        }

        try
        {
            var probe = await _client.GetAsync($"{BaseUrl}?operation=explain");
            if (!probe.IsSuccessStatusCode)
            {
                _output.WriteLine($"Skipping LexML external test: SRU unavailable (HTTP {(int)probe.StatusCode}).");
                return false;
            }
        }
        catch (Exception ex)
        {
            _output.WriteLine($"Skipping LexML external test: SRU unavailable ({ex.GetType().Name}).");
            return false;
        }

        return true;
    }
}
