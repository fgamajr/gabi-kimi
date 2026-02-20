using System.Security.Claims;
using System.Text;
using System.Text.Json;
using Gabi.Contracts.Jobs;
using Gabi.Contracts.Media;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.AspNetCore.WebUtilities;
using Microsoft.EntityFrameworkCore;
using Microsoft.Net.Http.Headers;

namespace Gabi.Api.Endpoints;

public static class MediaEndpoints
{
    private const int MaxMetadataChars = 32_000;
    private const int MaxSummaryChars = 262_144;
    private const int MaxTranscriptChars = 1_048_576;

    public static IEndpointRouteBuilder MapMediaEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapPost("/api/v1/media/upload", UploadAsync)
            .RequireAuthorization("RequireOperator")
            .RequireRateLimiting("write");

        app.MapPost("/api/v1/media/local-file", LocalFileAsync)
            .RequireAuthorization("RequireOperator")
            .RequireRateLimiting("write");

        app.MapGet("/api/v1/media/{id:long}", GetStatusAsync)
            .RequireAuthorization("RequireViewer")
            .RequireRateLimiting("read");

        app.MapPost("/api/v1/media/{id:long}/requeue", RequeueAsync)
            .RequireAuthorization("RequireOperator")
            .RequireRateLimiting("write");

        return app;
    }

    private static async Task<IResult> UploadAsync(
        HttpContext httpContext,
        GabiDbContext db,
        IJobQueueRepository jobQueue,
        CancellationToken ct)
    {
        if (!MediaTypeHeaderValue.TryParse(httpContext.Request.ContentType, out var mediaType) ||
            string.IsNullOrWhiteSpace(mediaType.Boundary.Value))
        {
            return Results.BadRequest(new { error = "Expected multipart/form-data request." });
        }

        var sourceId = string.Empty;
        var externalId = string.Empty;
        var mediaUrl = string.Empty;
        var title = string.Empty;
        var sessionType = string.Empty;
        var chamber = string.Empty;
        var metadataJson = "{}";
        var durationSeconds = default(int?);
        var providedTranscript = default(string);
        var providedSummary = default(string);
        var rejectedBinaryUpload = false;

        var boundary = HeaderUtilities.RemoveQuotes(mediaType.Boundary).Value;
        var reader = new MultipartReader(boundary!, httpContext.Request.Body);
        MultipartSection? section;
        while ((section = await reader.ReadNextSectionAsync(ct)) != null)
        {
            if (!ContentDispositionHeaderValue.TryParse(section.ContentDisposition, out var disposition))
                continue;

            if (disposition.DispositionType.Equals("form-data") && !string.IsNullOrEmpty(disposition.FileName.Value))
            {
                // Always reject binary upload to keep behavior aligned with diskless production.
                await section.Body.CopyToAsync(Stream.Null, ct);
                rejectedBinaryUpload = true;
                continue;
            }

            if (disposition.DispositionType.Equals("form-data"))
            {
                var name = HeaderUtilities.RemoveQuotes(disposition.Name).Value;
                using var sr = new StreamReader(section.Body, Encoding.UTF8, leaveOpen: false);
                var value = await sr.ReadToEndAsync(ct);
                switch (name)
                {
                    case "source_id":
                        sourceId = value.Trim();
                        break;
                    case "external_id":
                        externalId = value.Trim();
                        break;
                    case "media_url":
                        mediaUrl = value.Trim();
                        break;
                    case "title":
                        title = value.Trim();
                        break;
                    case "session_type":
                        sessionType = value.Trim();
                        break;
                    case "chamber":
                        chamber = value.Trim();
                        break;
                    case "duration_seconds":
                        if (int.TryParse(value.Trim(), out var parsed))
                            durationSeconds = parsed;
                        break;
                    case "metadata":
                        metadataJson = string.IsNullOrWhiteSpace(value) ? "{}" : value.Trim();
                        break;
                    case "transcript_text":
                        providedTranscript = value;
                        break;
                    case "summary_text":
                        providedSummary = value;
                        break;
                }
            }
        }

        if (rejectedBinaryUpload)
        {
            return Results.BadRequest(new
            {
                error = "Binary file upload is disabled in this environment. Use media_url, transcript_text or summary_text."
            });
        }

        if (string.IsNullOrWhiteSpace(sourceId))
            return Results.BadRequest(new { error = "source_id is required." });
        if (string.IsNullOrWhiteSpace(externalId))
            externalId = Guid.NewGuid().ToString("N");
        if (string.IsNullOrWhiteSpace(mediaUrl))
            return Results.BadRequest(new { error = "media_url is required." });
        if (!IsValidJson(metadataJson))
            return Results.BadRequest(new { error = "metadata must be valid JSON." });
        if (metadataJson.Length > MaxMetadataChars)
            return Results.BadRequest(new { error = $"metadata exceeds max length ({MaxMetadataChars} chars)." });
        if (!string.IsNullOrWhiteSpace(providedSummary) && providedSummary.Length > MaxSummaryChars)
            return Results.BadRequest(new { error = $"summary_text exceeds max length ({MaxSummaryChars} chars)." });
        if (!string.IsNullOrWhiteSpace(providedTranscript) && providedTranscript.Length > MaxTranscriptChars)
            return Results.BadRequest(new { error = $"transcript_text exceeds max length ({MaxTranscriptChars} chars)." });

        var actor = httpContext.User.FindFirstValue(ClaimTypes.Name) ?? "operator";

        var sourceExists = await db.SourceRegistries.AnyAsync(s => s.Id == sourceId, ct);
        if (!sourceExists)
            return Results.NotFound(new { error = $"source_id '{sourceId}' not found in source_registry." });

        var existing = await db.MediaItems
            .FirstOrDefaultAsync(x => x.SourceId == sourceId && x.ExternalId == externalId, ct);

        MediaItemEntity entity;
        if (existing == null)
        {
            entity = new MediaItemEntity
            {
                SourceId = sourceId,
                ExternalId = externalId,
                MediaUrl = string.IsNullOrWhiteSpace(mediaUrl) ? null : mediaUrl,
                Title = string.IsNullOrWhiteSpace(title) ? null : title,
                SessionType = string.IsNullOrWhiteSpace(sessionType) ? null : sessionType,
                Chamber = string.IsNullOrWhiteSpace(chamber) ? null : chamber,
                DurationSeconds = durationSeconds,
                TranscriptText = string.IsNullOrWhiteSpace(providedTranscript) ? null : providedTranscript,
                SummaryText = string.IsNullOrWhiteSpace(providedSummary) ? null : providedSummary,
                TranscriptStatus = "pending",
                Metadata = metadataJson,
                CreatedAt = DateTime.UtcNow,
                UpdatedAt = DateTime.UtcNow,
                CreatedBy = actor,
                UpdatedBy = actor
            };
            db.MediaItems.Add(entity);
        }
        else
        {
            entity = existing;
            if (!string.IsNullOrWhiteSpace(mediaUrl))
                entity.MediaUrl = mediaUrl;
            if (!string.IsNullOrWhiteSpace(title))
                entity.Title = title;
            if (!string.IsNullOrWhiteSpace(sessionType))
                entity.SessionType = sessionType;
            if (!string.IsNullOrWhiteSpace(chamber))
                entity.Chamber = chamber;
            if (durationSeconds.HasValue)
                entity.DurationSeconds = durationSeconds;
            if (!string.IsNullOrWhiteSpace(providedTranscript))
                entity.TranscriptText = providedTranscript;
            if (!string.IsNullOrWhiteSpace(providedSummary))
                entity.SummaryText = providedSummary;
            entity.Metadata = metadataJson;
            entity.TranscriptStatus = "pending";
            entity.LastError = null;
            entity.UpdatedAt = DateTime.UtcNow;
            entity.UpdatedBy = actor;
        }

        await db.SaveChangesAsync(ct);

        var job = new IngestJob
        {
            Id = Guid.NewGuid(),
            JobType = "media_transcribe",
            SourceId = sourceId,
            Payload = new Dictionary<string, object>
            {
                ["media_item_id"] = entity.Id
            },
            Status = JobStatus.Pending,
            Priority = JobPriority.Normal,
            ScheduledAt = DateTime.UtcNow,
            MaxRetries = 2,
            IdempotencyKey = Guid.NewGuid().ToString("N")
        };

        var jobId = await jobQueue.EnqueueAsync(job, ct);

        var response = new MediaUploadResponse(
            entity.Id,
            jobId,
            "accepted",
            "Upload received and media_transcribe job enqueued.");

        return Results.Accepted($"/api/v1/media/{entity.Id}", response);
    }

    private static async Task<IResult> LocalFileAsync(
        MediaLocalFileRequest request,
        HttpContext httpContext,
        GabiDbContext db,
        IJobQueueRepository jobQueue,
        CancellationToken ct)
    {
        var enabled = string.Equals(
            Environment.GetEnvironmentVariable("GABI_MEDIA_ALLOW_LOCAL_FILE"),
            "true",
            StringComparison.OrdinalIgnoreCase);
        if (!enabled)
        {
            return Results.BadRequest(new { error = "Local file transcribe is disabled. Enable GABI_MEDIA_ALLOW_LOCAL_FILE=true." });
        }

        if (string.IsNullOrWhiteSpace(request.SourceId) ||
            string.IsNullOrWhiteSpace(request.ExternalId) ||
            string.IsNullOrWhiteSpace(request.FilePath))
        {
            return Results.BadRequest(new { error = "sourceId, externalId and filePath are required." });
        }

        if (!request.FilePath.StartsWith("/workspace/", StringComparison.Ordinal))
            return Results.BadRequest(new { error = "filePath must be under /workspace/." });

        if (!File.Exists(request.FilePath))
            return Results.BadRequest(new { error = $"filePath not found: {request.FilePath}" });

        var sourceExists = await db.SourceRegistries.AnyAsync(s => s.Id == request.SourceId, ct);
        if (!sourceExists)
            return Results.NotFound(new { error = $"source_id '{request.SourceId}' not found in source_registry." });

        var actor = httpContext.User.FindFirstValue(ClaimTypes.Name) ?? "operator";
        var metadataJson = string.IsNullOrWhiteSpace(request.Metadata) ? "{}" : request.Metadata!;
        if (!IsValidJson(metadataJson))
            return Results.BadRequest(new { error = "metadata must be valid JSON." });

        var existing = await db.MediaItems
            .FirstOrDefaultAsync(x => x.SourceId == request.SourceId && x.ExternalId == request.ExternalId, ct);

        MediaItemEntity entity;
        if (existing == null)
        {
            entity = new MediaItemEntity
            {
                SourceId = request.SourceId,
                ExternalId = request.ExternalId,
                TempFilePath = request.FilePath,
                MediaUrl = $"local://{request.FilePath}",
                Title = request.Title,
                SessionType = request.SessionType,
                Chamber = request.Chamber,
                TranscriptStatus = "pending",
                Metadata = metadataJson,
                CreatedAt = DateTime.UtcNow,
                UpdatedAt = DateTime.UtcNow,
                CreatedBy = actor,
                UpdatedBy = actor
            };
            db.MediaItems.Add(entity);
        }
        else
        {
            entity = existing;
            entity.TempFilePath = request.FilePath;
            entity.MediaUrl = $"local://{request.FilePath}";
            if (!string.IsNullOrWhiteSpace(request.Title))
                entity.Title = request.Title;
            if (!string.IsNullOrWhiteSpace(request.SessionType))
                entity.SessionType = request.SessionType;
            if (!string.IsNullOrWhiteSpace(request.Chamber))
                entity.Chamber = request.Chamber;
            entity.Metadata = metadataJson;
            entity.TranscriptStatus = "pending";
            entity.LastError = null;
            entity.UpdatedAt = DateTime.UtcNow;
            entity.UpdatedBy = actor;
        }

        await db.SaveChangesAsync(ct);

        var job = new IngestJob
        {
            Id = Guid.NewGuid(),
            JobType = "media_transcribe",
            SourceId = request.SourceId,
            Payload = new Dictionary<string, object>
            {
                ["media_item_id"] = entity.Id
            },
            Status = JobStatus.Pending,
            Priority = JobPriority.Normal,
            ScheduledAt = DateTime.UtcNow,
            MaxRetries = 2,
            IdempotencyKey = Guid.NewGuid().ToString("N")
        };

        var jobId = await jobQueue.EnqueueAsync(job, ct);
        return Results.Accepted(
            $"/api/v1/media/{entity.Id}",
            new MediaUploadResponse(entity.Id, jobId, "accepted", "Local file queued for transcribe."));
    }

    private static async Task<IResult> GetStatusAsync(long id, GabiDbContext db, CancellationToken ct)
    {
        var media = await db.MediaItems.AsNoTracking().FirstOrDefaultAsync(m => m.Id == id, ct);
        if (media == null)
            return Results.NotFound();

        return Results.Ok(new MediaItemStatusResponse(
            media.Id,
            media.SourceId,
            media.ExternalId,
            media.TranscriptStatus,
            media.LastError,
            media.CreatedAt,
            media.UpdatedAt));
    }

    private static async Task<IResult> RequeueAsync(
        long id,
        HttpContext httpContext,
        GabiDbContext db,
        IJobQueueRepository jobQueue,
        CancellationToken ct)
    {
        var media = await db.MediaItems.FirstOrDefaultAsync(m => m.Id == id, ct);
        if (media == null)
            return Results.NotFound();

        var actor = httpContext.User.FindFirstValue(ClaimTypes.Name) ?? "operator";
        media.TranscriptStatus = "pending";
        media.LastError = null;
        media.UpdatedAt = DateTime.UtcNow;
        media.UpdatedBy = actor;
        await db.SaveChangesAsync(ct);

        var job = new IngestJob
        {
            Id = Guid.NewGuid(),
            JobType = "media_transcribe",
            SourceId = media.SourceId,
            Payload = new Dictionary<string, object>
            {
                ["media_item_id"] = media.Id
            },
            Status = JobStatus.Pending,
            Priority = JobPriority.Normal,
            ScheduledAt = DateTime.UtcNow,
            MaxRetries = 2,
            IdempotencyKey = Guid.NewGuid().ToString("N")
        };

        var jobId = await jobQueue.EnqueueAsync(job, ct);

        return Results.Accepted(
            $"/api/v1/media/{media.Id}",
            new MediaRequeueResponse(
                media.Id,
                jobId,
                "accepted",
                "Media item requeued for transcribe."));
    }

    private static bool IsValidJson(string raw)
    {
        try
        {
            using var _ = JsonDocument.Parse(raw);
            return true;
        }
        catch
        {
            return false;
        }
    }
}
