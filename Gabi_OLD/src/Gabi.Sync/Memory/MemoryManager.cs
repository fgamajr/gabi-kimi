using Gabi.Contracts.Pipeline;
using Microsoft.Extensions.Logging;

namespace Gabi.Sync.Memory;

/// <summary>
/// Implementação concreta do MemoryManager para ambientes serverless.
/// </summary>
public class MemoryManager : IMemoryManager
{
    private readonly ILogger<MemoryManager> _logger;
    private long _currentUsage;
    private long _peakUsage;
    private DateTime _lastGCCollect = DateTime.MinValue;
    
    public long TotalMemory { get; }
    public long PressureThreshold { get; }
    
    public long CurrentUsage => Interlocked.Read(ref _currentUsage);
    public long PeakUsage => Interlocked.Read(ref _peakUsage);
    
    public bool IsUnderPressure => CurrentUsage > PressureThreshold;

    public MemoryManager(ILogger<MemoryManager> logger, long? totalMemory = null)
    {
        _logger = logger;
        TotalMemory = totalMemory ?? GetTotalMemoryFromEnvironment();
        PressureThreshold = (long)(TotalMemory * 0.75);
        
        _logger.LogInformation(
            "MemoryManager: {TotalMB}MB total, {ThresholdMB}MB threshold",
            TotalMemory / 1024 / 1024,
            PressureThreshold / 1024 / 1024);
    }

    public IMemoryLease Acquire(long bytes)
    {
        TrackAllocation(bytes);
        return new MemoryLease(this, bytes);
    }

    public async Task WaitForAvailableAsync(long bytes, CancellationToken ct = default)
    {
        var startTime = DateTime.UtcNow;
        var attempts = 0;
        
        while (CurrentUsage + bytes > PressureThreshold)
        {
            attempts++;
            var elapsed = DateTime.UtcNow - startTime;
            
            if (elapsed > TimeSpan.FromMinutes(2))
            {
                throw new InsufficientMemoryException(
                    $"Memory pressure persisted for {elapsed.TotalSeconds}s. " +
                    $"Current: {CurrentUsage / 1024 / 1024}MB, Threshold: {PressureThreshold / 1024 / 1024}MB");
            }
            
            if (attempts % 10 == 0)
            {
                _logger.LogWarning(
                    "Memory pressure: {CurrentMB}MB / {ThresholdMB}MB (attempt {Attempt})",
                    CurrentUsage / 1024 / 1024,
                    PressureThreshold / 1024 / 1024,
                    attempts);
            }
            
            if (DateTime.UtcNow - _lastGCCollect > TimeSpan.FromSeconds(1))
            {
                CollectIfUnderPressure();
            }
            
            await Task.Delay(100, ct);
        }
    }

    public void CollectIfUnderPressure()
    {
        if (IsUnderPressure)
        {
            _lastGCCollect = DateTime.UtcNow;
            GC.Collect(2, GCCollectionMode.Optimized, blocking: false);
        }
    }

    internal void TrackAllocation(long bytes)
    {
        var newUsage = Interlocked.Add(ref _currentUsage, bytes);
        
        long currentPeak;
        do
        {
            currentPeak = PeakUsage;
            if (newUsage <= currentPeak) break;
        } while (Interlocked.CompareExchange(ref _peakUsage, newUsage, currentPeak) != currentPeak);
    }

    internal void TrackDeallocation(long bytes)
    {
        Interlocked.Add(ref _currentUsage, -bytes);
    }

    private static long GetTotalMemoryFromEnvironment()
    {
        try
        {
            var cgroupV1 = File.ReadAllText("/sys/fs/cgroup/memory/memory.limit_in_bytes");
            if (long.TryParse(cgroupV1.Trim(), out var limit) && limit > 0 && limit < long.MaxValue)
                return limit;
        }
        catch { }

        try
        {
            var cgroupV2 = File.ReadAllText("/sys/fs/cgroup/memory.max");
            if (long.TryParse(cgroupV2.Trim(), out var limit) && limit > 0 && limit < long.MaxValue)
                return limit;
        }
        catch { }

        return GC.GetGCMemoryInfo().TotalAvailableMemoryBytes is > 0 and < long.MaxValue 
            ? GC.GetGCMemoryInfo().TotalAvailableMemoryBytes 
            : 1024L * 1024 * 1024;
    }

    private class MemoryLease : IMemoryLease
    {
        private readonly MemoryManager _manager;
        private bool _disposed;

        public long Bytes { get; }

        public MemoryLease(MemoryManager manager, long bytes)
        {
            _manager = manager;
            Bytes = bytes;
        }

        public void Dispose()
        {
            if (!_disposed)
            {
                _disposed = true;
                _manager.TrackDeallocation(Bytes);
            }
        }
    }
}
