using System.Text.Json;
using Gabi.Contracts.Discovery;

namespace Gabi.Discover.Drivers;

internal static class YouTubeDiscoveryDriver
{
    internal static async IAsyncEnumerable<DiscoveredSource> DiscoverYouTubeChannelAsync(
        HttpClient httpClient,
        string sourceId,
        string strategyKey,
        DiscoveryConfig config,
        DiscoveryHttpRequestPolicy httpPolicy,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct)
    {
        var apiKey = Environment.GetEnvironmentVariable("YOUTUBE_API_KEY");
        if (string.IsNullOrWhiteSpace(apiKey))
            throw new ArgumentException("youtube_channel_v1 requires YOUTUBE_API_KEY env var", nameof(config));

        var channelId = ResolveYouTubeChannelId(config);
        var uploadsPlaylistId = await ResolveYouTubeUploadsPlaylistIdAsync(httpClient, channelId, apiKey!, httpPolicy, ct);
        if (string.IsNullOrWhiteSpace(uploadsPlaylistId))
            yield break;

        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        string? nextPageToken = null;

        do
        {
            ct.ThrowIfCancellationRequested();
            var endpoint = BuildYouTubePlaylistItemsEndpoint(uploadsPlaylistId, apiKey!, nextPageToken);

            using var resp = await DiscoveryAdapterHelpers.SendWithRetryAsync(httpClient, endpoint, httpPolicy, ct);
            if (resp == null || !resp.IsSuccessStatusCode)
                yield break;

            await using var stream = await resp.Content.ReadAsStreamAsync(ct);
            using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: ct);
            var root = doc.RootElement;

            if (root.TryGetProperty("items", out var items) && items.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in items.EnumerateArray())
                {
                    var videoId = ExtractYouTubeVideoId(item);
                    if (string.IsNullOrWhiteSpace(videoId) || !seen.Add(videoId))
                        continue;

                    var snippet = item.TryGetProperty("snippet", out var snippetEl) && snippetEl.ValueKind == JsonValueKind.Object
                        ? snippetEl
                        : default;

                    var metadata = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase)
                    {
                        ["strategy"] = strategyKey,
                        ["driver"] = "youtube_channel_v1",
                        ["source_family"] = "youtube",
                        ["document_kind"] = "multimedia_record",
                        ["media_kind"] = "video",
                        ["video_id"] = videoId,
                        ["channel_id"] = channelId,
                        ["title"] = snippet.ValueKind == JsonValueKind.Object ? DiscoveryAdapterHelpers.GetJsonString(snippet, "title") : string.Empty,
                        ["description"] = snippet.ValueKind == JsonValueKind.Object ? DiscoveryAdapterHelpers.GetJsonString(snippet, "description") : string.Empty,
                        ["published_at"] = snippet.ValueKind == JsonValueKind.Object ? DiscoveryAdapterHelpers.GetJsonString(snippet, "publishedAt") : string.Empty,
                        ["channel_title"] = snippet.ValueKind == JsonValueKind.Object ? DiscoveryAdapterHelpers.GetJsonString(snippet, "channelTitle") : string.Empty,
                        ["thumbnail_url"] = snippet.ValueKind == JsonValueKind.Object ? ExtractYouTubeThumbnailUrl(snippet) : string.Empty
                    };

                    yield return new DiscoveredSource(
                        $"https://www.youtube.com/watch?v={videoId}",
                        sourceId,
                        metadata,
                        DateTime.UtcNow);
                }
            }

            nextPageToken = root.TryGetProperty("nextPageToken", out var tokenEl) && tokenEl.ValueKind == JsonValueKind.String
                ? tokenEl.GetString()
                : null;

            if (!string.IsNullOrWhiteSpace(nextPageToken) && httpPolicy.RequestDelayMs > 0)
                await Task.Delay(httpPolicy.RequestDelayMs, ct);
        } while (!string.IsNullOrWhiteSpace(nextPageToken));
    }

    internal static string ResolveYouTubeChannelId(DiscoveryConfig config)
    {
        var channelIdFromEnv = Environment.GetEnvironmentVariable("YOUTUBE_CHANNEL_ID");
        if (!string.IsNullOrWhiteSpace(channelIdFromEnv))
            return channelIdFromEnv!;

        if (config.Extra != null
            && config.Extra.TryGetValue("channel_id", out var channelIdEl)
            && channelIdEl.ValueKind == JsonValueKind.String
            && !string.IsNullOrWhiteSpace(channelIdEl.GetString()))
        {
            return channelIdEl.GetString()!;
        }

        throw new ArgumentException("youtube_channel_v1 requires YOUTUBE_CHANNEL_ID env var or 'channel_id' in discovery config", nameof(config));
    }

    internal static async Task<string?> ResolveYouTubeUploadsPlaylistIdAsync(
        HttpClient httpClient,
        string channelId,
        string apiKey,
        DiscoveryHttpRequestPolicy httpPolicy,
        CancellationToken ct)
    {
        var endpoint =
            $"https://www.googleapis.com/youtube/v3/channels?part=contentDetails&id={Uri.EscapeDataString(channelId)}&key={Uri.EscapeDataString(apiKey)}";
        using var resp = await DiscoveryAdapterHelpers.SendWithRetryAsync(httpClient, endpoint, httpPolicy, ct);
        if (resp == null || !resp.IsSuccessStatusCode)
            return null;

        await using var stream = await resp.Content.ReadAsStreamAsync(ct);
        using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: ct);
        var root = doc.RootElement;
        if (!root.TryGetProperty("items", out var items) || items.ValueKind != JsonValueKind.Array)
            return null;

        foreach (var item in items.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object
                || !item.TryGetProperty("contentDetails", out var contentDetails)
                || contentDetails.ValueKind != JsonValueKind.Object
                || !contentDetails.TryGetProperty("relatedPlaylists", out var related)
                || related.ValueKind != JsonValueKind.Object
                || !related.TryGetProperty("uploads", out var uploads)
                || uploads.ValueKind != JsonValueKind.String)
            {
                continue;
            }

            var uploadsId = uploads.GetString();
            if (!string.IsNullOrWhiteSpace(uploadsId))
                return uploadsId;
        }

        return null;
    }

    internal static string BuildYouTubePlaylistItemsEndpoint(string playlistId, string apiKey, string? nextPageToken)
    {
        var endpoint =
            $"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet,contentDetails&playlistId={Uri.EscapeDataString(playlistId)}&maxResults=50&key={Uri.EscapeDataString(apiKey)}";
        if (!string.IsNullOrWhiteSpace(nextPageToken))
            endpoint += $"&pageToken={Uri.EscapeDataString(nextPageToken)}";
        return endpoint;
    }

    internal static string? ExtractYouTubeVideoId(JsonElement item)
    {
        if (item.ValueKind != JsonValueKind.Object)
            return null;

        if (item.TryGetProperty("contentDetails", out var contentDetails)
            && contentDetails.ValueKind == JsonValueKind.Object
            && contentDetails.TryGetProperty("videoId", out var videoIdEl)
            && videoIdEl.ValueKind == JsonValueKind.String)
        {
            return videoIdEl.GetString();
        }

        if (item.TryGetProperty("snippet", out var snippet)
            && snippet.ValueKind == JsonValueKind.Object
            && snippet.TryGetProperty("resourceId", out var resourceId)
            && resourceId.ValueKind == JsonValueKind.Object
            && resourceId.TryGetProperty("videoId", out var snippetVideoIdEl)
            && snippetVideoIdEl.ValueKind == JsonValueKind.String)
        {
            return snippetVideoIdEl.GetString();
        }

        return null;
    }

    internal static string ExtractYouTubeThumbnailUrl(JsonElement snippet)
    {
        if (!snippet.TryGetProperty("thumbnails", out var thumbs) || thumbs.ValueKind != JsonValueKind.Object)
            return string.Empty;

        var preferredOrder = new[] { "maxres", "standard", "high", "medium", "default" };
        foreach (var key in preferredOrder)
        {
            if (!thumbs.TryGetProperty(key, out var thumb) || thumb.ValueKind != JsonValueKind.Object)
                continue;
            if (!thumb.TryGetProperty("url", out var urlEl) || urlEl.ValueKind != JsonValueKind.String)
                continue;
            var url = urlEl.GetString();
            if (!string.IsNullOrWhiteSpace(url))
                return url!;
        }

        return string.Empty;
    }
}
