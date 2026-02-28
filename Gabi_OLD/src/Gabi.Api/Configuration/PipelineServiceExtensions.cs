using Gabi.Contracts.Observability;
using Hangfire;
using Hangfire.PostgreSql;
using OpenTelemetry.Metrics;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;

namespace Gabi.Api.Configuration;

public static class PipelineServiceExtensions
{
    /// <summary>
    /// Configures Hangfire for job enqueueing and the dashboard.
    /// The Worker service runs the Hangfire Server; the API only enqueues jobs.
    /// Skipped when connectionString is null or whitespace (e.g. Testing environment).
    /// </summary>
    public static IServiceCollection AddHangfireServices(
        this IServiceCollection services,
        string? connectionString)
    {
        if (!string.IsNullOrWhiteSpace(connectionString))
        {
            services.AddHangfire(config => config
                .SetDataCompatibilityLevel(CompatibilityLevel.Version_180)
                .UseSimpleAssemblyNameTypeSerializer()
                .UseRecommendedSerializerSettings()
                .UsePostgreSqlStorage(
                    connectionString,
                    new PostgreSqlStorageOptions
                    {
                        QueuePollInterval = TimeSpan.FromSeconds(5),
                        InvisibilityTimeout = TimeSpan.FromMinutes(10),
                        UseSlidingInvisibilityTimeout = true
                    }));
        }

        return services;
    }

    /// <summary>
    /// Configures OpenTelemetry tracing and metrics with OTLP export.
    /// Reads OTEL_EXPORTER_OTLP_ENDPOINT and OTEL_EXPORTER_OTLP_HEADERS from configuration.
    /// </summary>
    public static IServiceCollection AddObservabilityServices(
        this IServiceCollection services,
        IConfiguration configuration)
    {
        var otlpEndpoint = configuration["OTEL_EXPORTER_OTLP_ENDPOINT"] ?? "http://localhost:4317";
        var otlpHeaders = configuration["OTEL_EXPORTER_OTLP_HEADERS"];

        services.AddOpenTelemetry()
            .ConfigureResource(resource => resource.AddService(
                serviceName: "gabi-api",
                serviceVersion: typeof(Program).Assembly.GetName().Version?.ToString() ?? "unknown"))
            .WithTracing(tracing => tracing
                .AddAspNetCoreInstrumentation()
                .AddEntityFrameworkCoreInstrumentation()
                .AddHttpClientInstrumentation()
                .AddSource(PipelineTelemetry.ActivitySourceName)
                .AddOtlpExporter(options =>
                {
                    options.Endpoint = new Uri(otlpEndpoint);
                    if (!string.IsNullOrWhiteSpace(otlpHeaders))
                        options.Headers = otlpHeaders;
                }))
            .WithMetrics(metrics => metrics
                .AddAspNetCoreInstrumentation()
                .AddRuntimeInstrumentation()
                .AddMeter(PipelineTelemetry.MeterName)
                .AddOtlpExporter(options =>
                {
                    options.Endpoint = new Uri(otlpEndpoint);
                    if (!string.IsNullOrWhiteSpace(otlpHeaders))
                        options.Headers = otlpHeaders;
                }));

        return services;
    }
}
