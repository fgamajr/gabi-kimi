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
    private const long MaxUploadBytes = 512L * 1024L * 1024L; // 512MB hard-limit for stream copy

    public static IEndpointRouteBuilder MapMediaEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapPost("/api/v1/media/upload", UploadAsync)
            .RequireAuthorization("RequireOperator")
            .RequireRateLimiting("write");

        app.MapGet("/api/v1/media/{id:long}", GetStatusAsync)
            .RequireAuthorization("RequireViewer")
            .RequireRateLimiting("read");

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
        string? tempFilePath = null;

        var mediaRoot = Environment.GetEnvironmentVariable("GABI_MEDIA_TMP_DIR");
        mediaRoot = string.IsNullOrWhiteSpace(mediaRoot) ? "/tmp/gabi-media" : mediaRoot;
        Directory.CreateDirectory(mediaRoot);

        var boundary = HeaderUtilities.RemoveQuotes(mediaType.Boundary).Value;
        var reader = new MultipartReader(boundary!, httpContext.Request.Body);
        MultipartSection? section;
        while ((section = await reader.ReadNextSectionAsync(ct)) != null)
        {
            if (!ContentDispositionHeaderValue.TryParse(section.ContentDisposition, out var disposition))
                continue;

            if (disposition.DispositionType.Equals("form-data") && !string.IsNullOrEmpty(disposition.FileName.Value))
            {
                var originalFileName = disposition.FileName.Value ?? disposition.FileNameStar.Value ?? "media.bin";
                var extension = Path.GetExtension(originalFileName);
                var safeExtension = extension.Length > 10 ? ".bin" : extension;
                tempFilePath = Path.Combine(mediaRoot, $"{Guid.NewGuid():N}{safeExtension}");
                await using var fs = new FileStream(tempFilePath, FileMode.CreateNew, FileAccess.Write, FileShare.None, 81920, useAsync: true);
                await CopyWithLimitAsync(section.Body, fs, MaxUploadBytes, ct);
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

        if (string.IsNullOrWhiteSpace(sourceId))
            return Results.BadRequest(new { error = "source_id is required." });
        if (string.IsNullOrWhiteSpace(externalId))
            externalId = Guid.NewGuid().ToString("N");
        if (string.IsNullOrWhiteSpace(mediaUrl) && string.IsNullOrWhiteSpace(tempFilePath))
            return Results.BadRequest(new { error = "Provide media_url or file in multipart body." });
        if (!IsValidJson(metadataJson))
            return Results.BadRequest(new { error = "metadata must be valid JSON." });

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
                TempFilePath = tempFilePath,
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
            if (!string.IsNullOrWhiteSpace(tempFilePath))
                entity.TempFilePath = tempFilePath;
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

    private static async Task CopyWithLimitAsync(Stream source, Stream destination, long maxBytes, CancellationToken ct)
    {
        var buffer = new byte[81920];
        long total = 0;
        int read;
        while ((read = await source.ReadAsync(buffer.AsMemory(0, buffer.Length), ct)) > 0)
        {
            total += read;
            if (total > maxBytes)
                throw new InvalidOperationException($"Uploaded file exceeds max size of {maxBytes} bytes.");
            await destination.WriteAsync(buffer.AsMemory(0, read), ct);
        }
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
