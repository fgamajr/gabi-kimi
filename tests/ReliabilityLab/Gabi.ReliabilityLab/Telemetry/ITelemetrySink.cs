namespace Gabi.ReliabilityLab.Telemetry;

public interface ITelemetrySink
{
    void BeginCapture(string correlationId);
    void EndCapture();
    void RecordSpan(string name, DateTimeOffset start, DateTimeOffset end, IReadOnlyDictionary<string, string>? tags = null);
    void RecordResourceMetrics(ResourceMetrics metrics);
    void RecordStageMetrics(StageMetrics metrics);
    ExecutionTrace GetTrace();
    ResourceMetrics GetResourceMetrics();
    IReadOnlyList<StageMetrics> GetStageMetrics();
}
