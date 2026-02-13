using System.Globalization;
using System.Net;
using Gabi.Contracts.Metadata;

namespace Gabi.Fetch;

/// <summary>
/// Extracts metadata from URLs via HEAD requests
/// </summary>
public class MetadataExtractor : IMetadataExtractor
{
    private readonly HttpClient _httpClient;
    private const int BytesPerCsvRow = 200; // Heuristic average row size

    public MetadataExtractor(HttpClient httpClient)
    {
        _httpClient = httpClient ?? throw new ArgumentNullException(nameof(httpClient));
    }

    /// <inheritdoc />
    public async Task<ResourceMetadata> ExtractMetadataAsync(string url, CancellationToken ct = default)
    {
        ArgumentException.ThrowIfNullOrEmpty(url);

        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Head, url);
            using var response = await _httpClient.SendAsync(request, ct);

            var metadata = new ResourceMetadata
            {
                Url = url,
                StatusCode = (int)response.StatusCode,
                Filename = ExtractFilenameFromUrl(url),
                ContentLength = ExtractContentLength(response),
                ContentType = ExtractContentType(response),
                ETag = ExtractETag(response),
                LastModified = ExtractLastModified(response)
            };

            // Update filename from Content-Disposition if available
            var contentDispositionFilename = ExtractFilenameFromContentDisposition(response);
            if (!string.IsNullOrEmpty(contentDispositionFilename))
            {
                metadata = metadata with { Filename = contentDispositionFilename };
            }

            // Handle error responses
            if (!response.IsSuccessStatusCode)
            {
                metadata = metadata with 
                { 
                    ErrorMessage = $"HTTP {(int)response.StatusCode}: {response.ReasonPhrase}" 
                };
            }

            return metadata;
        }
        catch (OperationCanceledException)
        {
            return new ResourceMetadata
            {
                Url = url,
                Filename = ExtractFilenameFromUrl(url),
                ErrorMessage = "Request timed out"
            };
        }
        catch (HttpRequestException ex)
        {
            return new ResourceMetadata
            {
                Url = url,
                Filename = ExtractFilenameFromUrl(url),
                ErrorMessage = ex.Message
            };
        }
    }

    /// <inheritdoc />
    public Task<MetadataComparisonResult> CompareAsync(ResourceMetadata current, ResourceMetadata? previous)
    {
        ArgumentNullException.ThrowIfNull(current);

        // New resource - no previous metadata
        if (previous == null)
        {
            return Task.FromResult(new MetadataComparisonResult
            {
                HasChanged = true,
                ChangeReason = "new_resource",
                PreviousMetadata = null,
                CurrentMetadata = current
            });
        }

        // Check for changes
        string? changeReason = null;

        if (current.ContentLength != previous.ContentLength)
        {
            changeReason = "size_changed";
        }
        else if (!string.Equals(current.ETag, previous.ETag, StringComparison.Ordinal))
        {
            changeReason = "etag_changed";
        }
        else if (current.LastModified != previous.LastModified)
        {
            changeReason = "lastmodified_changed";
        }

        return Task.FromResult(new MetadataComparisonResult
        {
            HasChanged = changeReason != null,
            ChangeReason = changeReason,
            PreviousMetadata = previous,
            CurrentMetadata = current
        });
    }

    /// <inheritdoc />
    public int? EstimateDocumentCount(ResourceMetadata metadata, string fileType)
    {
        ArgumentNullException.ThrowIfNull(metadata);
        ArgumentException.ThrowIfNullOrEmpty(fileType);

        if (!metadata.ContentLength.HasValue)
        {
            return null;
        }

        return fileType.ToLowerInvariant() switch
        {
            "csv" => (int)(metadata.ContentLength.Value / BytesPerCsvRow),
            _ => null
        };
    }

    /// <summary>
    /// Extracts filename from URL path
    /// </summary>
    public string ExtractFilenameFromUrl(string url)
    {
        ArgumentException.ThrowIfNullOrEmpty(url);

        try
        {
            var uri = new Uri(url);
            var path = uri.AbsolutePath;
            var lastSlash = path.LastIndexOf('/');
            
            if (lastSlash >= 0 && lastSlash < path.Length - 1)
            {
                return path[(lastSlash + 1)..];
            }
            
            return path.TrimStart('/');
        }
        catch (UriFormatException)
        {
            // Fallback for relative URLs or invalid URLs
            var lastSlash = url.LastIndexOf('/');
            if (lastSlash >= 0 && lastSlash < url.Length - 1)
            {
                return url[(lastSlash + 1)..];
            }
            return url;
        }
    }

    private static long? ExtractContentLength(HttpResponseMessage response)
    {
        if (response.Content.Headers.ContentLength.HasValue)
        {
            return response.Content.Headers.ContentLength.Value;
        }

        // Try to parse from Content-Range header for partial content
        if (response.Headers.TryGetValues("Content-Range", out var contentRanges))
        {
            var range = contentRanges.FirstOrDefault();
            if (!string.IsNullOrEmpty(range))
            {
                // Format: "bytes 0-999/1000" - we want the total size (1000)
                var parts = range.Split('/');
                if (parts.Length == 2 && long.TryParse(parts[1], out var totalSize))
                {
                    return totalSize;
                }
            }
        }

        return null;
    }

    private static string? ExtractContentType(HttpResponseMessage response)
    {
        return response.Content.Headers.ContentType?.ToString();
    }

    private static string? ExtractETag(HttpResponseMessage response)
    {
        if (response.Headers.ETag != null)
        {
            return response.Headers.ETag.ToString();
        }

        // Try alternate header names
        if (response.Headers.TryGetValues("ETag", out var etagValues))
        {
            return etagValues.FirstOrDefault();
        }

        return null;
    }

    private static DateTime? ExtractLastModified(HttpResponseMessage response)
    {
        if (response.Content.Headers.LastModified.HasValue)
        {
            return response.Content.Headers.LastModified.Value.UtcDateTime;
        }

        // Try manual parsing from header
        if (response.Headers.TryGetValues("Last-Modified", out var lastModifiedValues))
        {
            var value = lastModifiedValues.FirstOrDefault();
            if (!string.IsNullOrEmpty(value) && 
                DateTime.TryParseExact(value, "R", CultureInfo.InvariantCulture, 
                    DateTimeStyles.AssumeUniversal, out var parsedDate))
            {
                return parsedDate.ToUniversalTime();
            }
        }

        return null;
    }

    private static string? ExtractFilenameFromContentDisposition(HttpResponseMessage response)
    {
        if (response.Content.Headers.ContentDisposition != null)
        {
            var fileName = response.Content.Headers.ContentDisposition.FileNameStar 
                ?? response.Content.Headers.ContentDisposition.FileName;
            
            if (!string.IsNullOrEmpty(fileName))
            {
                // Remove quotes if present
                return fileName.Trim('"', '\'');
            }
        }

        return null;
    }
}
