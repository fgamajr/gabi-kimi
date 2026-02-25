namespace Gabi.Contracts.Jobs;

/// <summary>
/// Terminal status of a job execution (semantic closure: no collapse to boolean success).
/// </summary>
public enum JobTerminalStatus
{
    /// <summary>Job completed with full success (no partial/capped/failed).</summary>
    Success,

    /// <summary>Some items failed; run is not fully successful.</summary>
    Partial,

    /// <summary>Run was capped (e.g. max_docs_per_source); not full coverage.</summary>
    Capped,

    /// <summary>Job failed (e.g. all items failed or fatal error).</summary>
    Failed,

    /// <summary>Run inconclusive (e.g. discovery 0 links without zero_ok policy).</summary>
    Inconclusive
}
