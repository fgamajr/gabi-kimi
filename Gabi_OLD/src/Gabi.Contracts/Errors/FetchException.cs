namespace Gabi.Contracts.Errors;

/// <summary>
/// Exception thrown when a fetch operation fails, carrying error classification and context.
/// </summary>
public class FetchException : Exception
{
    /// <summary>
    /// The error classification for this failure.
    /// </summary>
    public ErrorClassification Classification { get; }

    /// <summary>
    /// Context about the error for debugging.
    /// </summary>
    public ErrorContext? Context { get; }

    /// <summary>
    /// The URL that was being fetched (if applicable).
    /// </summary>
    public string? Url { get; }

    public FetchException(string message, ErrorClassification classification)
        : base(message)
    {
        Classification = classification;
    }

    public FetchException(string message, ErrorClassification classification, Exception inner)
        : base(message, inner)
    {
        Classification = classification;
    }

    public FetchException(string message, Exception inner, ErrorClassification classification, ErrorContext? context)
        : base(message, inner)
    {
        Classification = classification;
        Context = context;
        Url = context?.Url;
    }

    public override string ToString()
    {
        return $"[{Classification.Category}/{Classification.Code}] {Message}\n" +
               $"Recoverable: {Classification.IsRecoverable}\n" +
               $"Action: {Classification.SuggestedAction}\n" +
               $"URL: {Url ?? "N/A"}\n" +
               $"Base: {base.ToString()}";
    }
}
