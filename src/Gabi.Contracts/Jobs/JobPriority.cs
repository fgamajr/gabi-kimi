namespace Gabi.Contracts.Jobs;

/// <summary>
/// Priority levels for job processing.
/// Higher values are processed first.
/// </summary>
public enum JobPriority
{
    /// <summary>Low priority - background tasks.</summary>
    Low = 1,
    
    /// <summary>Normal priority - default for most jobs.</summary>
    Normal = 5,
    
    /// <summary>High priority - important jobs.</summary>
    High = 8,
    
    /// <summary>Critical priority - urgent jobs processed first.</summary>
    Critical = 10
}
