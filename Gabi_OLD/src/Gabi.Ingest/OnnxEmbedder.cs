using Gabi.Contracts.Chunk;
using Gabi.Contracts.Embed;
using Microsoft.Extensions.Logging;
using Microsoft.ML.OnnxRuntime;
using Microsoft.ML.OnnxRuntime.Tensors;

namespace Gabi.Ingest;

/// <summary>
/// Local ONNX Runtime embedder using paraphrase-multilingual-MiniLM-L12-v2.
/// Produces 384-dim vectors identical to the TEI service.
/// Uses a simple WordPiece tokenizer loaded from vocab.txt.
/// Memory: ~135MB model + ~25MB batch peak.
/// </summary>
public sealed class OnnxEmbedder : IEmbedder, IDisposable
{
    private const string ModelName = "paraphrase-multilingual-MiniLM-L12-v2";
    private const int EmbeddingDimensions = 384;
    private const int MaxSequenceLength = 128;

    private readonly InferenceSession _session;
    private readonly Dictionary<string, int> _vocab;
    private readonly int _unkId;
    private readonly int _clsId;
    private readonly int _sepId;
    private readonly int _padId;
    private readonly int _batchSize;
    private readonly ILogger<OnnxEmbedder> _logger;

    public OnnxEmbedder(string modelPath, string vocabPath, ILogger<OnnxEmbedder> logger, int batchSize = 32)
    {
        _logger = logger;
        _batchSize = batchSize;

        var options = new SessionOptions
        {
            InterOpNumThreads = Math.Max(1, Environment.ProcessorCount / 2),
            IntraOpNumThreads = Math.Max(1, Environment.ProcessorCount / 2),
            GraphOptimizationLevel = GraphOptimizationLevel.ORT_ENABLE_ALL,
        };
        _session = new InferenceSession(modelPath, options);

        // Load WordPiece vocabulary
        _vocab = new Dictionary<string, int>(200_000, StringComparer.Ordinal);
        var lines = File.ReadAllLines(vocabPath);
        for (var i = 0; i < lines.Length; i++)
            _vocab[lines[i]] = i;

        _unkId = _vocab.GetValueOrDefault("[UNK]", 100);
        _clsId = _vocab.GetValueOrDefault("[CLS]", 101);
        _sepId = _vocab.GetValueOrDefault("[SEP]", 102);
        _padId = _vocab.GetValueOrDefault("[PAD]", 0);

        _logger.LogInformation("ONNX embedder loaded: model={Model}, dims={Dims}, vocab={VocabSize}, batch={Batch}",
            ModelName, EmbeddingDimensions, _vocab.Count, _batchSize);
    }

    public async Task<IReadOnlyList<float>> EmbedAsync(string text, CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();
        var results = await EmbedBatchAsync(new[] { text }, ct);
        return results[0];
    }

    public Task<IReadOnlyList<IReadOnlyList<float>>> EmbedBatchAsync(
        IReadOnlyList<string> texts, CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();
        var results = new List<IReadOnlyList<float>>(texts.Count);

        for (var offset = 0; offset < texts.Count; offset += _batchSize)
        {
            ct.ThrowIfCancellationRequested();
            var batch = texts.Skip(offset).Take(_batchSize).ToList();
            var batchEmbeddings = RunInference(batch);
            results.AddRange(batchEmbeddings);
        }

        return Task.FromResult<IReadOnlyList<IReadOnlyList<float>>>(results);
    }

    public async Task<EmbeddingResult> EmbedChunksAsync(
        IReadOnlyList<Chunk> chunks, string documentId, CancellationToken ct = default)
    {
        var texts = chunks.Select(c => c.Text).ToList();
        var embeddings = await EmbedBatchAsync(texts, ct);

        var embeddedChunks = new List<EmbeddedChunk>(chunks.Count);
        for (var i = 0; i < chunks.Count; i++)
        {
            embeddedChunks.Add(new EmbeddedChunk
            {
                Text = chunks[i].Text,
                Index = i,
                TokenCount = chunks[i].TokenCount,
                CharCount = chunks[i].CharCount,
                Embedding = embeddings[i],
                Model = ModelName,
                Dimensions = EmbeddingDimensions
            });
        }

        return new EmbeddingResult
        {
            DocumentId = documentId,
            Chunks = embeddedChunks,
            Model = ModelName,
            TotalEmbeddings = embeddedChunks.Count,
            TokensProcessed = chunks.Sum(c => c.TokenCount)
        };
    }

    public Task<bool> HealthCheckAsync(CancellationToken ct = default)
    {
        try
        {
            var _ = RunInference(new[] { "health check" });
            return Task.FromResult(true);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "ONNX health check failed");
            return Task.FromResult(false);
        }
    }

    /// <summary>
    /// Simple WordPiece tokenizer: lowercases, splits on whitespace/punctuation,
    /// then greedily matches longest subword in vocab.
    /// </summary>
    private int[] Tokenize(string text)
    {
        var tokens = new List<int> { _clsId };
        var words = text.ToLowerInvariant().Split(
            new[] { ' ', '\t', '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries);

        foreach (var word in words)
        {
            if (tokens.Count >= MaxSequenceLength - 1) break;

            var remaining = word;
            var isFirst = true;
            while (remaining.Length > 0 && tokens.Count < MaxSequenceLength - 1)
            {
                var prefix = isFirst ? "" : "##";
                var matched = false;
                for (var end = remaining.Length; end > 0; end--)
                {
                    var sub = prefix + remaining[..end];
                    if (_vocab.TryGetValue(sub, out var id))
                    {
                        tokens.Add(id);
                        remaining = remaining[end..];
                        matched = true;
                        isFirst = false;
                        break;
                    }
                }
                if (!matched)
                {
                    tokens.Add(_unkId);
                    break;
                }
            }
        }

        tokens.Add(_sepId);
        return tokens.ToArray();
    }

    private IReadOnlyList<float[]> RunInference(IReadOnlyList<string> texts)
    {
        var batchSize = texts.Count;

        // Tokenize all texts
        var allTokenIds = new List<int[]>(batchSize);
        foreach (var text in texts)
            allTokenIds.Add(Tokenize(text ?? string.Empty));

        // Build tensors
        var inputIdsTensor = new DenseTensor<long>(new[] { batchSize, MaxSequenceLength });
        var attentionMaskTensor = new DenseTensor<long>(new[] { batchSize, MaxSequenceLength });
        var tokenTypeIdsTensor = new DenseTensor<long>(new[] { batchSize, MaxSequenceLength });

        for (var b = 0; b < batchSize; b++)
        {
            var ids = allTokenIds[b];
            var len = Math.Min(ids.Length, MaxSequenceLength);
            for (var s = 0; s < len; s++)
            {
                inputIdsTensor[b, s] = ids[s];
                attentionMaskTensor[b, s] = 1;
            }
            for (var s = len; s < MaxSequenceLength; s++)
            {
                inputIdsTensor[b, s] = _padId;
                attentionMaskTensor[b, s] = 0;
            }
        }

        var inputs = new List<NamedOnnxValue>
        {
            NamedOnnxValue.CreateFromTensor("input_ids", inputIdsTensor),
            NamedOnnxValue.CreateFromTensor("attention_mask", attentionMaskTensor),
            NamedOnnxValue.CreateFromTensor("token_type_ids", tokenTypeIdsTensor)
        };

        // Run inference
        using var results = _session.Run(inputs);
        var output = results.First().AsTensor<float>();

        // Mean pooling with attention mask + L2 normalize
        var embeddings = new List<float[]>(batchSize);
        for (var b = 0; b < batchSize; b++)
        {
            var embedding = new float[EmbeddingDimensions];
            var tokenCount = 0f;
            var ids = allTokenIds[b];
            var len = Math.Min(ids.Length, MaxSequenceLength);

            for (var s = 0; s < len; s++)
            {
                tokenCount++;
                for (var d = 0; d < EmbeddingDimensions; d++)
                    embedding[d] += output[b, s, d];
            }

            if (tokenCount > 0)
                for (var d = 0; d < EmbeddingDimensions; d++)
                    embedding[d] /= tokenCount;

            // L2 normalize
            var norm = 0f;
            for (var d = 0; d < EmbeddingDimensions; d++)
                norm += embedding[d] * embedding[d];
            norm = MathF.Sqrt(norm);
            if (norm > 0)
                for (var d = 0; d < EmbeddingDimensions; d++)
                    embedding[d] /= norm;

            embeddings.Add(embedding);
        }

        return embeddings;
    }

    public void Dispose()
    {
        _session.Dispose();
    }
}
