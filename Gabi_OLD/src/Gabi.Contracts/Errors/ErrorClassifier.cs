using System.Net;
using System.Security.Cryptography;
using System.Text;

namespace Gabi.Contracts.Errors;

/// <summary>
/// Classifies exceptions into error categories for retry decisions.
/// </summary>
public static class ErrorClassifier
{
    /// <summary>
    /// Classifies an exception with optional context for smarter decisions.
    /// </summary>
    public static ErrorClassification Classify(Exception exception, ErrorContext? context = null)
    {
        ArgumentNullException.ThrowIfNull(exception);

        if (exception is HttpRequestException http)
        {
            var classification = ClassifyHttpStatus(http.StatusCode, exception.Message);
            
            // Enhance auth errors with context
            if (classification.Category == ErrorCategory.Authentication && context != null)
            {
                return EnhanceAuthClassification(classification, context);
            }
            
            return classification;
        }

        // Check inner exception for wrapped HTTP errors
        if (exception.InnerException is HttpRequestException innerHttp)
        {
            var classification = ClassifyHttpStatus(innerHttp.StatusCode, exception.Message);
            if (classification.Category == ErrorCategory.Authentication && context != null)
            {
                return EnhanceAuthClassification(classification, context);
            }
            return classification;
        }

        // Code defects
        if (exception is NullReferenceException)
            return new ErrorClassification(
                ErrorCategory.Bug, 
                "NULL_REFERENCE", 
                exception.Message,
                false,
                "Report this as a bug");

        if (exception is ArgumentException or ArgumentNullException)
            return new ErrorClassification(
                ErrorCategory.Bug, 
                "ARGUMENT_ERROR", 
                exception.Message,
                false,
                "Check job configuration");

        if (exception is InvalidOperationException)
            return new ErrorClassification(
                ErrorCategory.Bug, 
                "INVALID_OPERATION", 
                exception.Message,
                false,
                "Check system state");

        // Transient errors
        if (exception is TimeoutException or TaskCanceledException)
            return new ErrorClassification(
                ErrorCategory.Transient, 
                "TIMEOUT", 
                exception.Message,
                true,
                "Will retry automatically");

        // Data format errors (permanent)
        if (exception is FormatException or System.Text.Json.JsonException)
            return new ErrorClassification(
                ErrorCategory.Permanent, 
                "FORMAT_ERROR", 
                exception.Message,
                false,
                "Check source data format");

        // SSL/Certificate errors (may be transient)
        if (exception.Message.Contains("SSL", StringComparison.OrdinalIgnoreCase) ||
            exception.Message.Contains("certificate", StringComparison.OrdinalIgnoreCase) ||
            exception is System.Security.Authentication.AuthenticationException)
        {
            return new ErrorClassification(
                ErrorCategory.Transient, 
                "SSL_ERROR", 
                exception.Message,
                true,
                "SSL/TLS error - may be transient");
        }

        // DNS resolution errors (transient)
        if (exception is System.Net.Sockets.SocketException socketEx)
        {
            return socketEx.SocketErrorCode switch
            {
                System.Net.Sockets.SocketError.HostNotFound => new ErrorClassification(
                    ErrorCategory.Transient, 
                    "DNS_ERROR", 
                    exception.Message,
                    true,
                    "DNS resolution failed - will retry"),
                System.Net.Sockets.SocketError.ConnectionRefused => new ErrorClassification(
                    ErrorCategory.Transient, 
                    "CONN_REFUSED", 
                    exception.Message,
                    true,
                    "Connection refused - will retry"),
                System.Net.Sockets.SocketError.TimedOut => new ErrorClassification(
                    ErrorCategory.Transient, 
                    "SOCKET_TIMEOUT", 
                    exception.Message,
                    true,
                    "Socket timeout - will retry"),
                _ => new ErrorClassification(
                    ErrorCategory.Transient, 
                    $"SOCKET_{socketEx.SocketErrorCode}", 
                    exception.Message,
                    true)
            };
        }

        // Default: treat unknown errors as transient
        return new ErrorClassification(
            ErrorCategory.Transient, 
            "UNCLASSIFIED", 
            exception.Message,
            true,
            "Unknown error - will retry");
    }

    /// <summary>
    /// Classifies from persisted error type and message strings.
    /// Used when deserializing DLQ entries.
    /// </summary>
    public static ErrorClassification Classify(string? errorType, string? errorMessage)
    {
        var type = errorType ?? string.Empty;
        var message = errorMessage ?? string.Empty;
        var composite = $"{type} {message}".ToUpperInvariant();

        // Check for auth errors first
        if (composite.Contains("401") || composite.Contains("UNAUTHORIZED"))
            return new ErrorClassification(
                ErrorCategory.Authentication, 
                "HTTP_401", 
                message,
                true,
                "Check authentication credentials");

        if (composite.Contains("403") || composite.Contains("FORBIDDEN"))
            return new ErrorClassification(
                ErrorCategory.Authentication, 
                "HTTP_403", 
                message,
                false,
                "Verify access permissions");

        if (composite.Contains("NULLREFERENCE"))
            return new ErrorClassification(ErrorCategory.Bug, "NULL_REFERENCE", message, false);

        if (composite.Contains("ARGUMENT"))
            return new ErrorClassification(ErrorCategory.Bug, "ARGUMENT_ERROR", message, false);

        if (composite.Contains("TIMEOUT") || composite.Contains("TASKCANCELED"))
            return new ErrorClassification(
                ErrorCategory.Transient, 
                "TIMEOUT", 
                message,
                true,
                "Will retry automatically");

        if (composite.Contains("429") || composite.Contains("TOO MANY REQUESTS"))
            return new ErrorClassification(
                ErrorCategory.Throttled, 
                "HTTP_429", 
                message,
                true,
                "Rate limited - will retry with delay");

        if (composite.Contains("404") || composite.Contains("NOT FOUND"))
            return new ErrorClassification(
                ErrorCategory.Permanent, 
                "HTTP_404", 
                message,
                false,
                "Resource not found - verify URL");

        if (composite.Contains("FORMAT") || composite.Contains("JSON") || composite.Contains("PARSE"))
            return new ErrorClassification(
                ErrorCategory.Permanent, 
                "PARSE_ERROR", 
                message,
                false,
                "Check data format");

        // Check for HTTP status codes in message
        foreach (var (status, category, code, recoverable, action) in HttpPatterns)
        {
            if (composite.Contains(status))
            {
                return new ErrorClassification(category, code, message, recoverable, action);
            }
        }

        return new ErrorClassification(
            ErrorCategory.Transient, 
            "UNCLASSIFIED", 
            message,
            true);
    }

    /// <summary>
    /// Computes a failure signature for grouping similar errors.
    /// </summary>
    public static string ComputeFailureSignature(ErrorClassification classification, string? url)
    {
        var signature = $"{classification.Category}:{classification.Code}:{url?.GetHashCode()}";
        using var sha = SHA256.Create();
        var hash = sha.ComputeHash(Encoding.UTF8.GetBytes(signature));
        return Convert.ToHexString(hash)[..16].ToLowerInvariant();
    }

    private static ErrorClassification ClassifyHttpStatus(HttpStatusCode? statusCode, string message)
    {
        if (!statusCode.HasValue)
            return new ErrorClassification(
                ErrorCategory.Transient, 
                "HTTP_UNKNOWN", 
                message,
                true,
                "Unknown HTTP error - will retry");

        var code = (int)statusCode.Value;

        return code switch
        {
            401 => new ErrorClassification(
                ErrorCategory.Authentication, 
                "HTTP_401", 
                "Unauthorized - check credentials",
                true,
                "Verify authentication token"),
            
            403 => new ErrorClassification(
                ErrorCategory.Authentication, 
                "HTTP_403", 
                "Forbidden - verify access rights",
                false,
                "Check source access permissions"),
            
            404 => new ErrorClassification(
                ErrorCategory.Permanent, 
                "HTTP_404", 
                "Not found",
                false,
                "URL may be invalid or resource removed"),
            
            408 => new ErrorClassification(
                ErrorCategory.Transient, 
                "HTTP_408", 
                "Request timeout",
                true,
                "Server timeout - will retry"),
            
            429 => new ErrorClassification(
                ErrorCategory.Throttled, 
                "HTTP_429", 
                "Rate limited",
                true,
                "Rate limit hit - will retry with backoff"),
            
            >= 500 and < 600 => new ErrorClassification(
                ErrorCategory.Transient, 
                $"HTTP_{code}", 
                message,
                true,
                "Server error - will retry"),
            
            >= 400 and < 500 => new ErrorClassification(
                ErrorCategory.Permanent, 
                $"HTTP_{code}", 
                message,
                false,
                "Client error - review request"),
            
            _ => new ErrorClassification(
                ErrorCategory.Transient, 
                $"HTTP_{code}", 
                message,
                true)
        };
    }

    private static ErrorClassification EnhanceAuthClassification(
        ErrorClassification classification, 
        ErrorContext context)
    {
        // Auth errors are potentially recoverable if it's the first failure
        // or if the error happened recently (token might just be expired)
        bool isRecoverable;
        string suggestedAction;

        if (context.RetryCount == 0)
        {
            isRecoverable = true;
            suggestedAction = "First auth failure - will retry";
        }
        else if (context.FirstFailedAt == null)
        {
            isRecoverable = true;
            suggestedAction = "Auth error - checking credentials";
        }
        else
        {
            var timeSinceFirstFailure = DateTime.UtcNow - context.FirstFailedAt.Value;
            if (timeSinceFirstFailure < TimeSpan.FromMinutes(30))
            {
                isRecoverable = true;
                suggestedAction = "Recent auth failure - will retry";
            }
            else
            {
                isRecoverable = classification.Code == "HTTP_401"; // 401 might be expired token
                suggestedAction = isRecoverable 
                    ? "Token may be expired - check credentials" 
                    : "Persistent auth error - verify permissions";
            }
        }

        return classification with 
        { 
            IsRecoverable = isRecoverable, 
            SuggestedAction = suggestedAction 
        };
    }

    private static readonly List<(string Pattern, ErrorCategory Category, string Code, bool Recoverable, string Action)> HttpPatterns = new()
    {
        ("500", ErrorCategory.Transient, "HTTP_500", true, "Server error - will retry"),
        ("502", ErrorCategory.Transient, "HTTP_502", true, "Bad gateway - will retry"),
        ("503", ErrorCategory.Transient, "HTTP_503", true, "Service unavailable - will retry"),
        ("504", ErrorCategory.Transient, "HTTP_504", true, "Gateway timeout - will retry"),
    };
}
