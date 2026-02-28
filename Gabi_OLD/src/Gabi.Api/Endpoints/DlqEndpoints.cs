using Gabi.Api.Services;
using Microsoft.AspNetCore.Mvc;

namespace Gabi.Api.Endpoints;

/// <summary>
/// API endpoints for Dead Letter Queue management.
/// </summary>
public static class DlqEndpoints
{
    public static IEndpointRouteBuilder MapDlqEndpoints(this IEndpointRouteBuilder app)
    {
        var group = app.MapGroup("/api/v1/dlq")
            .WithName("DLQ")
            .WithOpenApi()
            .RequireAuthorization(policy => policy.RequireRole("admin", "operator"));

        // List entries with filtering
        group.MapGet("/entries", async (
            [AsParameters] DlqListRequest request,
            IEnhancedDlqService service,
            CancellationToken ct) =>
        {
            var queryRequest = new DlqQueryRequest(
                request.Page,
                request.PageSize,
                request.Status,
                request.Category,
                request.SourceId,
                request.ErrorCode,
                request.FromDate,
                request.ToDate,
                request.IsRecoverable);

            var result = await service.GetEntriesAsync(queryRequest, ct);
            return Results.Ok(result);
        })
        .WithName("GetDlqEntries")
        .WithDescription("Get DLQ entries with optional filtering");

        // Get single entry
        group.MapGet("/entries/{id:guid}", async (
            Guid id,
            IEnhancedDlqService service,
            CancellationToken ct) =>
        {
            var entry = await service.GetEntryAsync(id, ct);
            return entry == null ? Results.NotFound() : Results.Ok(entry);
        })
        .WithName("GetDlqEntry")
        .WithDescription("Get a single DLQ entry by ID");

        // Get stats
        group.MapGet("/stats", async (
            IEnhancedDlqService service,
            CancellationToken ct) =>
        {
            var stats = await service.GetStatsAsync(ct);
            return Results.Ok(stats);
        })
        .WithName("GetDlqStats")
        .WithDescription("Get DLQ statistics");

        // Get failure patterns
        group.MapGet("/patterns", async (
            IEnhancedDlqService service,
            CancellationToken ct) =>
        {
            var patterns = await service.GetFailurePatternsAsync(ct);
            return Results.Ok(patterns);
        })
        .WithName("GetFailurePatterns")
        .WithDescription("Get grouped failure patterns for bulk operations");

        // Get health report
        group.MapGet("/health", async (
            IEnhancedDlqService service,
            CancellationToken ct) =>
        {
            var report = await service.GetHealthReportAsync(ct);
            return Results.Ok(report);
        })
        .WithName("GetDlqHealth")
        .WithDescription("Get DLQ health report with active alerts");

        // Replay single entry
        group.MapPost("/entries/{id:guid}/replay", async (
            Guid id,
            [FromBody(EmptyBodyBehavior = Microsoft.AspNetCore.Mvc.ModelBinding.EmptyBodyBehavior.Allow)]
            ReplayRequest? request,
            IEnhancedDlqService service,
            CancellationToken ct) =>
        {
            var result = await service.ReplayAsync(id, request?.Notes, ct);
            return result.Success 
                ? Results.Ok(result) 
                : Results.BadRequest(new { error = result.Message });
        })
        .WithName("ReplayDlqEntry")
        .WithDescription("Replay a single DLQ entry");

        // Replay by pattern
        group.MapPost("/patterns/{signature}/replay", async (
            string signature,
            [FromBody(EmptyBodyBehavior = Microsoft.AspNetCore.Mvc.ModelBinding.EmptyBodyBehavior.Allow)]
            ReplayRequest? request,
            IEnhancedDlqService service,
            CancellationToken ct) =>
        {
            var result = await service.ReplayByPatternAsync(signature, request?.Notes, ct);
            return Results.Ok(result);
        })
        .WithName("ReplayByPattern")
        .WithDescription("Replay all DLQ entries matching a failure pattern");

        // Replay by category
        group.MapPost("/categories/{category}/replay", async (
            string category,
            [FromBody(EmptyBodyBehavior = Microsoft.AspNetCore.Mvc.ModelBinding.EmptyBodyBehavior.Allow)]
            ReplayRequest? request,
            IEnhancedDlqService service,
            CancellationToken ct) =>
        {
            var result = await service.ReplayByCategoryAsync(category, request?.Notes, ct);
            return Results.Ok(result);
        })
        .WithName("ReplayByCategory")
        .WithDescription("Replay all DLQ entries in a category");

        // Archive single entry
        group.MapPost("/entries/{id:guid}/archive", async (
            Guid id,
            [FromBody] ArchiveRequest request,
            IEnhancedDlqService service,
            CancellationToken ct) =>
        {
            var result = await service.ArchiveAsync(id, request.Reason, ct);
            return result.Success
                ? Results.Ok(result)
                : Results.BadRequest(new { error = result.Message });
        })
        .WithName("ArchiveDlqEntry")
        .WithDescription("Archive a DLQ entry (mark as resolved without replay)");

        // Archive by pattern
        group.MapPost("/patterns/{signature}/archive", async (
            string signature,
            [FromBody] ArchiveRequest request,
            IEnhancedDlqService service,
            CancellationToken ct) =>
        {
            var result = await service.ArchiveByPatternAsync(signature, request.Reason, ct);
            return Results.Ok(result);
        })
        .WithName("ArchiveByPattern")
        .WithDescription("Archive all DLQ entries matching a failure pattern");

        return app;
    }
}

// Request records
public record DlqListRequest(
    int Page = 1,
    int PageSize = 20,
    string? Status = null,
    string? Category = null,
    string? SourceId = null,
    string? ErrorCode = null,
    DateTime? FromDate = null,
    DateTime? ToDate = null,
    bool? IsRecoverable = null);

public record ReplayRequest(string? Notes);
public record ArchiveRequest(string Reason);
