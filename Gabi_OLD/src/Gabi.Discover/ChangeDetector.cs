using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text;
using Gabi.Contracts.Discovery;

namespace Gabi.Discover;

/// <summary>
/// Detector de mudanças que compara recursos com cache.
/// </summary>
public class ChangeDetector
{
    /// <summary>
    /// Verifica se um recurso mudou comparando com cache.
    /// </summary>
    public Task<ChangeDetectionVerdict> CheckAsync(
        DiscoveredSource discovered,
        ChangeDetectionCache? cache)
    {
        // New URL (not in cache)
        if (cache == null)
        {
            return Task.FromResult(new ChangeDetectionVerdict
            {
                Url = discovered.Url,
                SourceId = discovered.SourceId,
                Changed = true,
                Reason = "new",
                CachedEtag = null,
                CachedLastModified = null,
                CachedContentHash = null
            });
        }

        // Check ETag first (most reliable)
        if (!string.IsNullOrEmpty(discovered.Etag) && !string.IsNullOrEmpty(cache.Etag))
        {
            if (discovered.Etag != cache.Etag)
            {
                return Task.FromResult(new ChangeDetectionVerdict
                {
                    Url = discovered.Url,
                    SourceId = discovered.SourceId,
                    Changed = true,
                    Reason = "etag_changed",
                    CachedEtag = cache.Etag
                });
            }
            
            return Task.FromResult(new ChangeDetectionVerdict
            {
                Url = discovered.Url,
                SourceId = discovered.SourceId,
                Changed = false,
                Reason = "etag_unchanged",
                CachedEtag = cache.Etag
            });
        }

        // Check Last-Modified
        if (!string.IsNullOrEmpty(discovered.LastModified) && !string.IsNullOrEmpty(cache.LastModified))
        {
            if (discovered.LastModified != cache.LastModified)
            {
                return Task.FromResult(new ChangeDetectionVerdict
                {
                    Url = discovered.Url,
                    SourceId = discovered.SourceId,
                    Changed = true,
                    Reason = "last_modified_changed",
                    CachedLastModified = cache.LastModified
                });
            }
            
            return Task.FromResult(new ChangeDetectionVerdict
            {
                Url = discovered.Url,
                SourceId = discovered.SourceId,
                Changed = false,
                Reason = "last_modified_unchanged",
                CachedLastModified = cache.LastModified
            });
        }

        // Check Content Hash
        if (!string.IsNullOrEmpty(discovered.Metadata["content_hash"]?.ToString()) && !string.IsNullOrEmpty(cache.ContentHash))
        {
            var currentHash = discovered.Metadata["content_hash"]?.ToString();
            if (currentHash != cache.ContentHash)
            {
                return Task.FromResult(new ChangeDetectionVerdict
                {
                    Url = discovered.Url,
                    SourceId = discovered.SourceId,
                    Changed = true,
                    Reason = "content_hash_changed",
                    CachedContentHash = cache.ContentHash
                });
            }
            
            return Task.FromResult(new ChangeDetectionVerdict
            {
                Url = discovered.Url,
                SourceId = discovered.SourceId,
                Changed = false,
                Reason = "content_hash_unchanged",
                CachedContentHash = cache.ContentHash
            });
        }

        // No comparison possible, assume changed
        return Task.FromResult(new ChangeDetectionVerdict
        {
            Url = discovered.Url,
            SourceId = discovered.SourceId,
            Changed = true,
            Reason = "unknown"
        });
    }

    /// <summary>
    /// Verifica múltiplos recursos em batch.
    /// </summary>
    public async Task<ChangeDetectionBatch> CheckBatchAsync(
        IEnumerable<DiscoveredSource> sources,
        IAsyncEnumerable<ChangeDetectionCache?> caches)
    {
        var toProcess = new List<ChangeDetectionVerdict>();
        var skipped = new List<ChangeDetectionVerdict>();
        var errors = new List<Dictionary<string, string>>();
        
        var cacheDict = new Dictionary<string, ChangeDetectionCache?>();
        await foreach (var cache in caches)
        {
            if (cache != null)
                cacheDict[cache.Url] = cache;
        }

        foreach (var source in sources)
        {
            try
            {
                cacheDict.TryGetValue(source.Url, out var cache);
                var verdict = await CheckAsync(source, cache);
                
                if (verdict.Changed)
                    toProcess.Add(verdict);
                else
                    skipped.Add(verdict);
            }
            catch (Exception ex)
            {
                errors.Add(new Dictionary<string, string>
                {
                    ["url"] = source.Url,
                    ["error"] = ex.Message
                });
            }
        }

        return new ChangeDetectionBatch
        {
            ToProcess = toProcess,
            Skipped = skipped,
            Errors = errors
        };
    }

    /// <summary>
    /// Computa hash SHA-256 do conteúdo.
    /// </summary>
    public string ComputeContentHash(byte[] content)
    {
        using var sha256 = SHA256.Create();
        var hash = sha256.ComputeHash(content);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }
}
