using System.Net.Http.Headers;
using System.Text.Json;
using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Worker.Jobs;

public class MediaTranscribeJobExecutor : IJobExecutor
{
    public string JobType => "media_transcribe";

    private readonly GabiDbContext _context;
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly ILogger<MediaTranscribeJobExecutor> _logger;

    public MediaTranscribeJobExecutor(
        GabiDbContext context,
        IHttpClientFactory httpClientFactory,
        ILogger<MediaTranscribeJobExecutor> logger)
    {
        _context = context;
        _httpClientFactory = httpClientFactory;
        _logger = logger;
    }

    public async Task<JobResult> ExecuteAsync(IngestJob job, IProgress<JobProgress> progress, CancellationToken ct)
    {
        if (!TryReadMediaItemId(job, out var mediaItemId))
        {
            return new JobResult { Success = false, ErrorMessage = "payload.media_item_id is required" };
        }

        var media = await _context.MediaItems.FirstOrDefaultAsync(m => m.Id == mediaItemId, ct);
        if (media == null)
        {
            return new JobResult { Success = false, ErrorMessage = $"media item {mediaItemId} not found" };
        }

        media.TranscriptStatus = "processing";
        media.LastError = null;
        media.UpdatedAt = DateTime.UtcNow;
        await _context.SaveChangesAsync(ct);

        progress.Report(new JobProgress { PercentComplete = 20, Message = $"media {mediaItemId} processing" });

        try
        {
            string? transcript = null;

            if (!string.IsNullOrWhiteSpace(media.TranscriptText))
            {
                transcript = media.TranscriptText;
            }
            else if (!string.IsNullOrWhiteSpace(media.SummaryText))
            {
                transcript = media.SummaryText;
                media.TranscriptConfidence = "low";
            }
            else if (!string.IsNullOrWhiteSpace(media.TempFilePath))
            {
                transcript = await TranscribeFileAsync(media.TempFilePath!, ct);
            }
            else
            {
                throw new InvalidOperationException("No transcript_text provided and no temp file to transcribe.");
            }

            media.TranscriptText = transcript;
            media.TranscriptStatus = "completed";
            media.TranscriptConfidence ??= "medium";
            media.LastError = null;
            media.UpdatedAt = DateTime.UtcNow;

            if (!string.IsNullOrWhiteSpace(media.TempFilePath) && File.Exists(media.TempFilePath))
            {
                File.Delete(media.TempFilePath);
                media.TempFilePath = null;
            }

            await _context.SaveChangesAsync(ct);
            progress.Report(new JobProgress { PercentComplete = 100, Message = $"media {mediaItemId} completed" });

            return new JobResult
            {
                Success = true,
                Metadata = new Dictionary<string, object> { ["media_item_id"] = mediaItemId }
            };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "media_transcribe failed for media item {MediaItemId}", mediaItemId);
            media.TranscriptStatus = "failed";
            media.LastError = ex.Message.Length > 1900 ? ex.Message[..1900] : ex.Message;
            media.UpdatedAt = DateTime.UtcNow;
            await _context.SaveChangesAsync(ct);
            return new JobResult { Success = false, ErrorMessage = ex.Message };
        }
    }

    private static bool TryReadMediaItemId(IngestJob job, out long mediaItemId)
    {
        mediaItemId = 0;
        if (!job.Payload.TryGetValue("media_item_id", out var raw) || raw == null)
            return false;

        if (raw is long l)
        {
            mediaItemId = l;
            return true;
        }

        if (raw is int i)
        {
            mediaItemId = i;
            return true;
        }

        if (long.TryParse(raw.ToString(), out var parsed))
        {
            mediaItemId = parsed;
            return true;
        }

        return false;
    }

    private async Task<string> TranscribeFileAsync(string tempFilePath, CancellationToken ct)
    {
        if (!File.Exists(tempFilePath))
            throw new FileNotFoundException("Media temp file not found", tempFilePath);

        var apiKey = Environment.GetEnvironmentVariable("OPENAI_API_KEY");
        if (string.IsNullOrWhiteSpace(apiKey))
            throw new InvalidOperationException("OPENAI_API_KEY is required to transcribe uploaded media.");

        var client = _httpClientFactory.CreateClient(nameof(MediaTranscribeJobExecutor));
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", apiKey);

        await using var stream = File.OpenRead(tempFilePath);
        using var form = new MultipartFormDataContent();

        var fileContent = new StreamContent(stream);
        fileContent.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
        form.Add(fileContent, "file", Path.GetFileName(tempFilePath));
        form.Add(new StringContent("whisper-1"), "model");

        using var response = await client.PostAsync("https://api.openai.com/v1/audio/transcriptions", form, ct);
        var payload = await response.Content.ReadAsStringAsync(ct);
        if (!response.IsSuccessStatusCode)
            throw new InvalidOperationException($"Transcription API error {(int)response.StatusCode}: {payload}");

        using var doc = JsonDocument.Parse(payload);
        if (!doc.RootElement.TryGetProperty("text", out var textEl) || textEl.ValueKind != JsonValueKind.String)
            throw new InvalidOperationException("Transcription API returned no text.");

        return textEl.GetString() ?? string.Empty;
    }
}
