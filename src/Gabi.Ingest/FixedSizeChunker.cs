using System.Diagnostics;
using Gabi.Contracts.Chunk;

namespace Gabi.Ingest;

public sealed class FixedSizeChunker : IChunker
{
    public ChunkResult Chunk(string text, ChunkConfig config, IReadOnlyDictionary<string, object>? metadata = null)
    {
        var stopwatch = Stopwatch.StartNew();

        if (string.IsNullOrWhiteSpace(text))
        {
            return new ChunkResult
            {
                Chunks = Array.Empty<Chunk>(),
                TotalTokens = 0,
                TotalChars = 0,
                DurationMs = stopwatch.Elapsed.TotalMilliseconds
            };
        }

        var maxChunkSize = Math.Max(32, config.MaxChunkSize);
        var overlap = Math.Max(0, Math.Min(config.Overlap, maxChunkSize - 1));
        var step = Math.Max(1, maxChunkSize - overlap);

        var tokens = text.Split(
            new[] { ' ', '\n', '\r', '\t' },
            StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var chunks = new List<Chunk>(Math.Max(1, (tokens.Length / step) + 1));

        for (var i = 0; i < tokens.Length; i += step)
        {
            var length = Math.Min(maxChunkSize, tokens.Length - i);
            if (length <= 0)
                break;

            var slice = tokens.AsSpan(i, length).ToArray();
            var chunkText = string.Join(' ', slice);

            var chunkMetadata = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase)
            {
                ["start_token"] = i,
                ["end_token"] = i + length - 1
            };

            if (metadata is not null)
            {
                foreach (var item in metadata)
                {
                    if (!chunkMetadata.ContainsKey(item.Key))
                        chunkMetadata[item.Key] = item.Value;
                }
            }

            chunks.Add(new Chunk(
                Index: chunks.Count,
                Text: chunkText,
                TokenCount: length,
                Type: ChunkType.Content,
                SectionType: "content",
                Metadata: chunkMetadata));
        }

        return new ChunkResult
        {
            Chunks = chunks,
            TotalTokens = tokens.Length,
            TotalChars = text.Length,
            DurationMs = stopwatch.Elapsed.TotalMilliseconds
        };
    }
}
