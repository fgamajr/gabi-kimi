namespace Gabi.Worker.Jobs;

/// <summary>
/// Thrown when the embedding API returns 429 Too Many Requests.
/// Hangfire/DlqFilter can use this to apply a longer retry delay (e.g. respect Retry-After).
/// </summary>
public sealed class EmbeddingRateLimitException : Exception
{
    public EmbeddingRateLimitException(string message) : base(message) { }

    public EmbeddingRateLimitException(string message, Exception inner) : base(message, inner) { }
}
