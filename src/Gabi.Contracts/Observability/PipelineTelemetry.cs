using System.Diagnostics;
using System.Diagnostics.Metrics;

namespace Gabi.Contracts.Observability;

public static class PipelineTelemetry
{
    public const string ActivitySourceName = "Gabi.Pipeline";
    public const string MeterName = "Gabi.Pipeline";

    public static readonly ActivitySource ActivitySource = new(ActivitySourceName);
    public static readonly Meter Meter = new(MeterName);

    private static readonly Counter<long> DocsProcessedCounter =
        Meter.CreateCounter<long>("gabi.docs.processed", unit: "docs", description: "Documents processed by source and stage");

    private static readonly Histogram<double> StageLatencyMsHistogram =
        Meter.CreateHistogram<double>("gabi.stage.latency_ms", unit: "ms", description: "Pipeline stage latency in milliseconds");

    private static readonly Counter<long> StageErrorsCounter =
        Meter.CreateCounter<long>("gabi.stage.errors", unit: "errors", description: "Pipeline stage errors by source and stage");

    public static void RecordDocsProcessed(long count, string sourceId, string stage)
    {
        DocsProcessedCounter.Add(
            count,
            new KeyValuePair<string, object?>("source.id", sourceId),
            new KeyValuePair<string, object?>("pipeline.stage", stage));
    }

    public static void RecordStageLatency(double milliseconds, string sourceId, string stage)
    {
        StageLatencyMsHistogram.Record(
            milliseconds,
            new KeyValuePair<string, object?>("source.id", sourceId),
            new KeyValuePair<string, object?>("pipeline.stage", stage));
    }

    public static void RecordStageError(string sourceId, string stage)
    {
        StageErrorsCounter.Add(
            1,
            new KeyValuePair<string, object?>("source.id", sourceId),
            new KeyValuePair<string, object?>("pipeline.stage", stage));
    }
}
