using System.Security.Cryptography;
using System.Text;
using Gabi.Contracts.Fetch;
using Microsoft.Extensions.Logging;

namespace Gabi.Fetch;

/// <summary>
/// Content fetcher with ETag/Last-Modified support and streaming.
/// No internal retry - Hangfire handles retries at job level.
/// </summary>
public class ContentFetcher : IContentFetcher
{
    private readonly HttpClient _httpClient;
    private readonly ILogger<ContentFetcher>? _logger;

    public ContentFetcher(HttpClient httpClient, ILogger<ContentFetcher>? logger = null)
    {
        _httpClient = httpClient ?? throw new ArgumentNullException(nameof(httpClient));
        _logger = logger;
    }

    public async Task<FetchedContent> FetchAsync(
        string url,
        FetchConfig config,
        CancellationToken ct = default)
    {
        ArgumentException.ThrowIfNullOrEmpty(url);

        var response = await SendRequestAsync(url, config, null, null, ct);
        
        if (response.StatusCode == System.Net.HttpStatusCode.NotModified)
        {
            return new FetchedContent
            {
                Url = url,
                HttpStatus = 304,
                ContentType = "",
                Content = Array.Empty<byte>()
            };
        }

        response.EnsureSuccessStatusCode();

        var content = await response.Content.ReadAsByteArrayAsync(ct);
        var contentType = response.Content.Headers.ContentType?.MediaType ?? "application/octet-stream";
        var etag = response.Headers.ETag?.Tag?.Trim('"');
        var lastModified = response.Content.Headers.LastModified?.ToString("R");
        var contentHash = ComputeHash(content);

        return new FetchedContent
        {
            Url = url,
            Content = content,
            SizeBytes = content.Length,
            ContentType = contentType,
            DetectedFormat = DetectFormat(content, contentType),
            HttpStatus = (int)response.StatusCode,
            Etag = etag,
            LastModified = lastModified,
            ContentHash = contentHash,
            Headers = ExtractHeaders(response)
        };
    }

    public async Task<StreamingFetchedContent> FetchStreamingAsync(
        string url,
        FetchConfig config,
        CancellationToken ct = default)
    {
        ArgumentException.ThrowIfNullOrEmpty(url);

        var response = await SendRequestAsync(url, config, null, null, ct);
        
        response.EnsureSuccessStatusCode();

        var stream = await response.Content.ReadAsStreamAsync(ct);
        var contentType = response.Content.Headers.ContentType?.MediaType ?? "application/octet-stream";
        var etag = response.Headers.ETag?.Tag?.Trim('"');
        var lastModified = response.Content.Headers.LastModified?.ToString("R");
        var encoding = response.Content.Headers.ContentType?.CharSet ?? "utf-8";

        return new StreamingFetchedContent
        {
            Url = url,
            TextChunks = StreamToTextChunksAsync(stream, config.Streaming, encoding, ct),
            EstimatedSizeBytes = response.Content.Headers.ContentLength,
            ContentType = contentType,
            DetectedFormat = DetectFormatFromContentType(contentType),
            Encoding = encoding,
            HttpStatus = (int)response.StatusCode,
            Etag = etag,
            LastModified = lastModified,
            Headers = ExtractHeaders(response)
        };
    }

    public async Task<StreamingFetchedContent> FetchStreamingAsync(
        string url,
        FetchConfig config,
        string? etag,
        string? lastModified,
        CancellationToken ct = default)
    {
        ArgumentException.ThrowIfNullOrEmpty(url);

        var response = await SendRequestAsync(url, config, etag, lastModified, ct);
        
        if (response.StatusCode == System.Net.HttpStatusCode.NotModified)
        {
            return new StreamingFetchedContent
            {
                Url = url,
                HttpStatus = 304,
                ContentType = "",
                DetectedFormat = ""
            };
        }

        response.EnsureSuccessStatusCode();

        var stream = await response.Content.ReadAsStreamAsync(ct);
        var contentType = response.Content.Headers.ContentType?.MediaType ?? "application/octet-stream";
        var responseEtag = response.Headers.ETag?.Tag?.Trim('"');
        var responseLastModified = response.Content.Headers.LastModified?.ToString("R");
        var encoding = response.Content.Headers.ContentType?.CharSet ?? "utf-8";

        return new StreamingFetchedContent
        {
            Url = url,
            TextChunks = StreamToTextChunksAsync(stream, config.Streaming, encoding, ct),
            EstimatedSizeBytes = response.Content.Headers.ContentLength,
            ContentType = contentType,
            DetectedFormat = DetectFormatFromContentType(contentType),
            Encoding = encoding,
            HttpStatus = (int)response.StatusCode,
            Etag = responseEtag,
            LastModified = responseLastModified,
            Headers = ExtractHeaders(response)
        };
    }

    public async Task<FetchMetadata> HeadAsync(string url, CancellationToken ct = default)
    {
        ArgumentException.ThrowIfNullOrEmpty(url);

        var response = await _httpClient.SendAsync(
            new HttpRequestMessage(HttpMethod.Head, url),
            HttpCompletionOption.ResponseHeadersRead,
            ct);

        return new FetchMetadata
        {
            Url = url,
            ContentType = response.Content.Headers.ContentType?.MediaType ?? "",
            ContentLength = response.Content.Headers.ContentLength,
            ETag = response.Headers.ETag?.Tag?.Trim('"'),
            LastModified = response.Content.Headers.LastModified?.DateTime,
            StatusCode = (int)response.StatusCode,
            Headers = ExtractHeaders(response)
        };
    }

    private async Task<HttpResponseMessage> SendRequestAsync(
        string url,
        FetchConfig config,
        string? etag,
        string? lastModified,
        CancellationToken ct)
    {
        var request = new HttpRequestMessage(HttpMethod.Get, url);

        if (!string.IsNullOrEmpty(etag))
        {
            request.Headers.IfNoneMatch.Add(new System.Net.Http.Headers.EntityTagHeaderValue($"\"{etag}\""));
        }

        if (!string.IsNullOrEmpty(lastModified))
        {
            if (DateTimeOffset.TryParse(lastModified, out var date))
            {
                request.Headers.IfModifiedSince = date;
            }
        }

        foreach (var header in config.Headers)
        {
            request.Headers.TryAddWithoutValidation(header.Key, header.Value);
        }

        var timeout = ParseTimeout(config.Timeout);
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(timeout);

        return await _httpClient.SendAsync(
            request,
            HttpCompletionOption.ResponseHeadersRead,
            cts.Token);
    }

    private static async IAsyncEnumerable<string> StreamToTextChunksAsync(
        Stream stream,
        StreamingConfig config,
        string encoding,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct)
    {
        using var reader = new StreamReader(stream, Encoding.GetEncoding(encoding));
        var buffer = new char[config.ChunkSize / 2];

        while (!ct.IsCancellationRequested)
        {
            var read = await reader.ReadAsync(buffer, 0, buffer.Length);
            if (read == 0) break;

            yield return new string(buffer, 0, read);
        }
    }

    private static string ComputeHash(byte[] content)
    {
        var hash = SHA256.HashData(content);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    private static string DetectFormat(byte[] content, string contentType)
    {
        if (content.Length >= 4)
        {
            if (content[0] == 0x25 && content[1] == 0x50 && content[2] == 0x44 && content[3] == 0x46)
                return "pdf";
        }

        return DetectFormatFromContentType(contentType);
    }

    private static string DetectFormatFromContentType(string contentType)
    {
        return contentType.ToLowerInvariant() switch
        {
            var ct when ct.Contains("csv") => "csv",
            var ct when ct.Contains("json") => "json",
            var ct when ct.Contains("xml") => "xml",
            var ct when ct.Contains("html") => "html",
            var ct when ct.Contains("pdf") => "pdf",
            var ct when ct.Contains("text/plain") => "text",
            _ => "binary"
        };
    }

    private static Dictionary<string, string> ExtractHeaders(HttpResponseMessage response)
    {
        var headers = new Dictionary<string, string>();
        
        foreach (var header in response.Headers)
        {
            headers[header.Key] = string.Join(", ", header.Value);
        }
        
        foreach (var header in response.Content.Headers)
        {
            headers[header.Key] = string.Join(", ", header.Value);
        }

        return headers;
    }

    private static TimeSpan ParseTimeout(string timeout)
    {
        if (string.IsNullOrEmpty(timeout))
            return TimeSpan.FromMinutes(5);

        if (timeout.EndsWith('s'))
            return TimeSpan.FromSeconds(int.Parse(timeout[..^1]));
        if (timeout.EndsWith('m'))
            return TimeSpan.FromMinutes(int.Parse(timeout[..^1]));
        if (timeout.EndsWith('h'))
            return TimeSpan.FromHours(int.Parse(timeout[..^1]));

        return TimeSpan.Parse(timeout);
    }
}
