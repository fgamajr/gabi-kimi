using System.Text.Json;

namespace Gabi.Api.Middleware;

/// <summary>
/// Global exception handling middleware - nunca expõe stack trace em produção.
/// </summary>
public class ExceptionHandlingMiddleware
{
    private readonly RequestDelegate _next;
    private readonly ILogger<ExceptionHandlingMiddleware> _logger;
    private readonly IHostEnvironment _environment;

    public ExceptionHandlingMiddleware(
        RequestDelegate next,
        ILogger<ExceptionHandlingMiddleware> logger,
        IHostEnvironment environment)
    {
        _next = next;
        _logger = logger;
        _environment = environment;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        try
        {
            await _next(context);
        }
        catch (KeyNotFoundException ex)
        {
            await HandleExceptionAsync(context, ex, StatusCodes.Status404NotFound, "Resource not found");
        }
        catch (UnauthorizedAccessException ex)
        {
            await HandleExceptionAsync(context, ex, StatusCodes.Status403Forbidden, "Access denied");
        }
        catch (InvalidOperationException ex)
        {
            await HandleExceptionAsync(context, ex, StatusCodes.Status400BadRequest, "Invalid operation");
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Unhandled exception occurred");
            await HandleExceptionAsync(context, ex, StatusCodes.Status500InternalServerError, 
                "An error occurred while processing your request");
        }
    }

    private async Task HandleExceptionAsync(
        HttpContext context, 
        Exception exception, 
        int statusCode, 
        string message)
    {
        context.Response.StatusCode = statusCode;
        context.Response.ContentType = "application/json";

        // Em desenvolvimento, incluir detalhes da exceção
        var includeDetails = _environment.IsDevelopment();
        
        var response = new ErrorResponse
        {
            StatusCode = statusCode,
            Message = message,
            RequestId = context.TraceIdentifier,
            Detail = includeDetails ? exception.Message : null,
            StackTrace = includeDetails ? exception.StackTrace : null
        };

        await context.Response.WriteAsJsonAsync(response);
    }
}

public record ErrorResponse
{
    public int StatusCode { get; init; }
    public string Message { get; init; } = string.Empty;
    public string RequestId { get; init; } = string.Empty;
    public string? Detail { get; init; }
    public string? StackTrace { get; init; }
}

// Extension method
public static class ExceptionHandlingMiddlewareExtensions
{
    public static IApplicationBuilder UseGlobalExceptionHandler(this IApplicationBuilder app)
    {
        return app.UseMiddleware<ExceptionHandlingMiddleware>();
    }
}
