namespace Gabi.ReliabilityLab.Telemetry;

public sealed class InMemoryTelemetrySink : ITelemetrySink
{
    private string _correlationId = string.Empty;
    private readonly List<TraceSpan> _spans = new();
    private ResourceMetrics _resourceMetrics = new();
    private readonly List<StageMetrics> _stageMetrics = new();
    private readonly object _lock = new();

    public void BeginCapture(string correlationId)
    {
        lock (_lock)
        {
            _correlationId = correlationId;
            _spans.Clear();
            _stageMetrics.Clear();
        }
    }

    public void EndCapture() { }

    public void RecordSpan(string name, DateTimeOffset start, DateTimeOffset end, IReadOnlyDictionary<string, string>? tags = null)
    {
        lock (_lock)
        {
            _spans.Add(new TraceSpan
            {
                Name = name,
                Start = start,
                End = end,
                Tags = tags ?? new Dictionary<string, string>()
            });
        }
    }

    public void RecordResourceMetrics(ResourceMetrics metrics)
    {
        lock (_lock) { _resourceMetrics = metrics; }
    }

    public void RecordStageMetrics(StageMetrics metrics)
    {
        lock (_lock) { _stageMetrics.Add(metrics); }
    }

    public ExecutionTrace GetTrace()
    {
        lock (_lock)
        {
            return new ExecutionTrace { CorrelationId = _correlationId, Spans = _spans.ToList() };
        }
    }

    public ResourceMetrics GetResourceMetrics()
    {
        lock (_lock) { return _resourceMetrics; }
    }

    public IReadOnlyList<StageMetrics> GetStageMetrics()
    {
        lock (_lock) { return _stageMetrics.ToList(); }
    }
}
