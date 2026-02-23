using System.Net;

namespace Gabi.Contracts.Common;

public enum ErrorCategory
{
    Transient,
    Throttled,
    Permanent,
    Bug
}

public readonly record struct ErrorClassification(ErrorCategory Category, string Code, string Message);

public static class ErrorClassifier
{
    public static ErrorClassification Classify(Exception exception)
    {
        ArgumentNullException.ThrowIfNull(exception);

        if (exception is NullReferenceException)
            return new ErrorClassification(ErrorCategory.Bug, "NULL_REFERENCE", exception.Message);

        if (exception is ArgumentException)
            return new ErrorClassification(ErrorCategory.Bug, "ARGUMENT_ERROR", exception.Message);

        if (exception is TimeoutException or TaskCanceledException)
            return new ErrorClassification(ErrorCategory.Transient, "TIMEOUT", exception.Message);

        if (exception is FormatException)
            return new ErrorClassification(ErrorCategory.Permanent, "FORMAT_ERROR", exception.Message);

        if (exception is HttpRequestException http)
            return ClassifyHttpStatus(http.StatusCode, exception.Message);

        return new ErrorClassification(ErrorCategory.Transient, "UNCLASSIFIED", exception.Message);
    }

    public static ErrorClassification Classify(string? errorType, string? errorMessage)
    {
        var type = errorType ?? string.Empty;
        var message = errorMessage ?? string.Empty;
        var composite = $"{type} {message}".ToUpperInvariant();

        if (composite.Contains("NULLREFERENCE"))
            return new ErrorClassification(ErrorCategory.Bug, "NULL_REFERENCE", message);

        if (composite.Contains("ARGUMENT"))
            return new ErrorClassification(ErrorCategory.Bug, "ARGUMENT_ERROR", message);

        if (composite.Contains("TIMEOUT") || composite.Contains("TASKCANCELED"))
            return new ErrorClassification(ErrorCategory.Transient, "TIMEOUT", message);

        if (composite.Contains("429") || composite.Contains("TOO MANY REQUESTS"))
            return new ErrorClassification(ErrorCategory.Throttled, "HTTP_429", message);

        if (composite.Contains("404") || composite.Contains("NOT FOUND") || composite.Contains("FORMAT") || composite.Contains("JSON") || composite.Contains("PARSE"))
            return new ErrorClassification(ErrorCategory.Permanent, composite.Contains("404") ? "HTTP_404" : "PARSE_ERROR", message);

        return new ErrorClassification(ErrorCategory.Transient, "UNCLASSIFIED", message);
    }

    private static ErrorClassification ClassifyHttpStatus(HttpStatusCode? statusCode, string message)
    {
        if (!statusCode.HasValue)
            return new ErrorClassification(ErrorCategory.Transient, "HTTP_UNKNOWN", message);

        var code = (int)statusCode.Value;

        return code switch
        {
            404 => new ErrorClassification(ErrorCategory.Permanent, "HTTP_404", message),
            429 => new ErrorClassification(ErrorCategory.Throttled, "HTTP_429", message),
            >= 500 => new ErrorClassification(ErrorCategory.Transient, $"HTTP_{code}", message),
            >= 400 => new ErrorClassification(ErrorCategory.Permanent, $"HTTP_{code}", message),
            _ => new ErrorClassification(ErrorCategory.Transient, $"HTTP_{code}", message)
        };
    }
}
