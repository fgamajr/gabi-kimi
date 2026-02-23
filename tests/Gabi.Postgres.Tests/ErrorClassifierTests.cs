using System.Net;
using Gabi.Contracts.Common;

namespace Gabi.Postgres.Tests;

public class ErrorClassifierTests
{
    [Fact]
    public void Classify_Http404_ShouldBePermanent()
    {
        var ex = new HttpRequestException("not found", null, HttpStatusCode.NotFound);

        var result = ErrorClassifier.Classify(ex);

        Assert.Equal(ErrorCategory.Permanent, result.Category);
        Assert.Equal("HTTP_404", result.Code);
    }

    [Fact]
    public void Classify_Http429_ShouldBeThrottled()
    {
        var ex = new HttpRequestException("too many", null, (HttpStatusCode)429);

        var result = ErrorClassifier.Classify(ex);

        Assert.Equal(ErrorCategory.Throttled, result.Category);
        Assert.Equal("HTTP_429", result.Code);
    }

    [Fact]
    public void Classify_NullReference_ShouldBeBug()
    {
        var ex = new NullReferenceException("boom");

        var result = ErrorClassifier.Classify(ex);

        Assert.Equal(ErrorCategory.Bug, result.Category);
        Assert.Equal("NULL_REFERENCE", result.Code);
    }

    [Theory]
    [InlineData("HttpRequestException", "404 Not Found", ErrorCategory.Permanent)]
    [InlineData("HttpRequestException", "429 Too Many Requests", ErrorCategory.Throttled)]
    [InlineData("TimeoutException", "timeout", ErrorCategory.Transient)]
    [InlineData("NullReferenceException", "Object reference", ErrorCategory.Bug)]
    public void Classify_FromPersistedError_ShouldMapExpectedCategory(string? errorType, string? errorMessage, ErrorCategory expected)
    {
        var result = ErrorClassifier.Classify(errorType, errorMessage);

        Assert.Equal(expected, result.Category);
    }
}
