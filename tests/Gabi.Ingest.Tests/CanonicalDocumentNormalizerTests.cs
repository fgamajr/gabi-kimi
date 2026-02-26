using Gabi.Contracts.Ingest;
using Xunit;

namespace Gabi.Ingest.Tests;

public class CanonicalDocumentNormalizerTests
{
    [Fact]
    public void Normalize_PreservesMetadata()
    {
        var normalizer = new CanonicalDocumentNormalizer();
        var metadata = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase)
        {
            ["normative_force"] = "binding",
            ["senado_norma"] = "12345"
        };
        var doc = new CanonicalTextDocument
        {
            SourceId = "source1",
            ExternalId = "ext1",
            Title = "Title",
            Content = "Content",
            Metadata = metadata
        };

        var result = normalizer.Normalize(doc);

        Assert.NotNull(result.Metadata);
        Assert.Equal("binding", result.Metadata["normative_force"]);
        Assert.Equal("12345", result.Metadata["senado_norma"]);
        Assert.True(result.Metadata.ContainsKey("canonical_version"));
        Assert.Equal("v1", result.Metadata["canonical_version"]);
    }

    [Fact]
    public void Normalize_NormalizesNewlinesAndSpaces()
    {
        var normalizer = new CanonicalDocumentNormalizer();
        var doc = new CanonicalTextDocument
        {
            SourceId = "s",
            ExternalId = "e",
            Title = "  Title  ",
            Content = "Line1\r\nLine2\rLine3\n\n\nLine4",
            Metadata = new Dictionary<string, object>()
        };

        var result = normalizer.Normalize(doc);

        Assert.Equal("Title", result.Title);
        Assert.Contains("\n", result.Content);
        Assert.DoesNotContain("\r", result.Content ?? "");
    }

    [Fact]
    public void Normalize_EmptyContent_UsesTitleWhenProvided()
    {
        var normalizer = new CanonicalDocumentNormalizer();
        var doc = new CanonicalTextDocument
        {
            SourceId = "s",
            ExternalId = "e",
            Title = "Only title",
            Content = "   ",
            Metadata = new Dictionary<string, object>()
        };

        var result = normalizer.Normalize(doc);

        Assert.Equal("Only title", result.Content);
    }
}
