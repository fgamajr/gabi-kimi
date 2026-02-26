# GABI Reliability Lab — Implementation Plan

> **Document Type:** Architectural specification + implementation prompt
> **Target:** Principal .NET Engineer (LLM)
> **Goal:** Build production-grade reliability validation platform
> **Context:** GABI — distributed data pipeline for legal document ingestion

---

## 1. Executive Summary

Build a **deterministic, diagnosable, repeatable system verification laboratory** for a .NET 8 distributed data pipeline. This is not a test suite — it is an engineering verification system comparable to what large platform teams use before shipping infrastructure.

**Key Principle:** Strict separation of concerns:
- **Experiment definition** → what is tested
- **Execution engine** → how it runs
- **Observation** → what happened
- **Evaluation** → is it acceptable
- **Reporting** → how humans understand it

**No class may mix more than one of these concerns.**

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           RELIABILITY LAB ARCHITECTURE                              │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         EXPERIMENT DEFINITION LAYER                          │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐  │   │
│  │  │ ExperimentDef   │  │ WorkloadParams  │  │ PipelineScenario            │  │   │
│  │  │ ─────────────   │  │ ─────────────── │  │ ───────────────             │  │   │
│  │  │ • Name          │  │ • DocumentCount │  │ • ZeroKelvinScenario        │  │   │
│  │  │ • Seed          │  │ • Concurrency   │  │ • BackpressureScenario      │  │   │
│  │  │ • Timeout       │  │ • FaultProfile  │  │ • ChaosScenario             │  │   │
│  │  │ • ExpectedStages│  │ • DataShape     │  │ • RecoveryScenario          │  │   │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                          │                                          │
│                                          ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                           EXECUTION ENGINE LAYER                             │   │
│  │   ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐     │   │
│  │   │ ExperimentRunner │───▶│  RunCoordinator  │───▶│ StageExecutor    │     │   │
│  │   │ ──────────────── │    │ ──────────────── │    │ ─────────────    │     │   │
│  │   │ • Deterministic  │    │ • Parallelism    │    │ • Stage isolation│     │   │
│  │   │ • Cancellation   │    │ • Resource mgmt  │    │ • Timeout enforce│     │   │
│  │   │ • Timeout enforce│    │ • Fault inject   │    │ • Telemetry hook │     │   │
│  │   │ • Result collect │    │ • Cleanup coord  │    │ • Checkpoint     │     │   │
│  │   └──────────────────┘    └──────────────────┘    └──────────────────┘     │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                          │                                          │
│                                          ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                        ENVIRONMENT CONTROLLER LAYER                          │   │
│  │   ┌─────────────────────┐         ┌─────────────────────┐                   │   │
│  │   │ DockerComposeDriver │◄───────►│ TestcontainersDriver│                   │   │
│  │   │ ─────────────────── │         │ ─────────────────── │                   │   │
│  │   │ • Compose up/down   │         │ • Programmatic ctl  │                   │   │
│  │   │ • Health checks     │         │ • Faster startup    │                   │   │
│  │   │ • Network isolation │         │ • CI-friendly       │                   │   │
│  │   │ • Log capture       │         │ • Resource limits   │                   │   │
│  │   └─────────────────────┘         └─────────────────────┘                   │   │
│  │                                                                             │   │
│  │   ┌─────────────────────────────────────────────────────────────────────┐   │   │
│  │   │                     IEnvironmentController                         │   │   │
│  │   │  • StartAsync(ct) → EnvironmentHandle                              │   │   │
│  │   │  • ResetAsync(ct) → Clean state                                    │   │   │
│  │   │  • StopAsync(ct)  → Teardown guarantee                             │   │   │
│  │   │  • GetReadinessAsync(ct) → HealthSnapshot                          │   │   │
│  │   └─────────────────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                          │                                          │
│                                          ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         TELEMETRY CAPTURE LAYER                              │   │
│  │   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │   │
│  │   │ExecutionTrace│  │ResourceMetric│  │  StageMetric │  │  EventLog    │    │   │
│  │   │──────────────│  │──────────────│  │──────────────│  │──────────────│    │   │
│  │   │• Span tree   │  │• CPU/Memory  │  │• Throughput  │  │• Structured  │    │   │
│  │   │• Stage bounds│  │• I/O stats   │  │• Latency p99 │  │• Correlation │    │   │
│  │   │• Annotations │  │• GC pressure │  │• Error rate  │  │• Severity    │    │   │
│  │   └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │   │
│  │                                                                             │   │
│  │   ┌─────────────────────────────────────────────────────────────────────┐   │   │
│  │   │              OpenTelemetry Ingestion (OTLP/Console)                │   │   │
│  │   │   • Traces → Jaeger/Zipkin    • Metrics → Prometheus               │   │   │
│  │   │   • Logs → Structured JSON    • Baggage for correlation            │   │   │
│  │   └─────────────────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                          │                                          │
│                                          ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                      DATA VERIFICATION FRAMEWORK LAYER                       │   │
│  │   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐         │   │
│  │   │ IIntegrityCheck  │  │ ISemanticCheck   │  │IConsistencyCheck │         │   │
│  │   │ ──────────────── │  │ ──────────────── │  │──────────────────│         │   │
│  │   │• SHA-256 match   │  │• Content preserv│  │• Idempotency     │         │   │
│  │   │• Schema valid    │  │• Truncation det │  │• Ordering        │         │   │
│  │   │• Reference integ │  │• Encoding stable│  │• Convergence     │         │   │
│  │   └──────────────────┘  └──────────────────┘  └──────────────────┘         │   │
│  │                                                                             │   │
│  │   ┌─────────────────────────────────────────────────────────────────────┐   │   │
│  │   │                    VerificationPipeline                            │   │   │
│  │   │   Composable: Integrity → Semantic → Consistency → Aggregation     │   │   │
│  │   └─────────────────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                          │                                          │
│                                          ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                       EVALUATION POLICY ENGINE LAYER                         │   │
│  │   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐         │   │
│  │   │ ReliabilityPolicy│  │ DataQualityPolicy│  │PerformancePolicy │         │   │
│  │   │ ──────────────── │  │ ──────────────── │  │──────────────────│         │   │
│  │   │• MaxCrash: 0    │  │• MaxLoss: 0.001  │  │• P95 < 5s        │         │   │
│  │   │• MaxRetries: 10 │  │• MaxDup: 0.0001  │  │• Memory < 2GB    │         │   │
│  │   │• DLQ empty      │  │• MinSemantic:0.99│  │• Throughput >100 │         │   │
│  │   └──────────────────┘  └──────────────────┘  └──────────────────┘         │   │
│  │                                                                             │   │
│  │   ┌─────────────────────────────────────────────────────────────────────┐   │   │
│  │   │              PolicyEvaluator (declarative rules engine)              │   │   │
│  │   │   Input: ExperimentResult + Policies → Output: PolicyVerdict        │   │   │
│  │   └─────────────────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                          │                                          │
│                                          ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         DIAGNOSTIC REPORTING LAYER                           │   │
│  │                                                                             │   │
│  │   artifacts/reliability/{timestamp}/                                         │   │
│  │   ├── summary.json          # High-level verdict, policies evaluated        │   │
│  │   ├── metrics.json          # All telemetry aggregates                      │   │
│  │   ├── timeline.json         # Execution trace with spans                    │   │
│  │   ├── verification.json     # Check results with evidence                   │   │
│  │   ├── failures.md           # Human-readable failure analysis               │   │
│  │   └── raw/                  # Full trace logs, heap dumps if OOM            │   │
│  │                                                                             │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                          │                                          │
│                                          ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                          XUNIT ADAPTER LAYER                                 │   │
│  │                                                                             │   │
│  │   public class ZeroKelvinReliabilityTests : IClassFixture<ReliabilityLab>   │   │
│  │   {                                                                         │   │
│  │       [Fact] public async Task FullPipeline_DataConservation_Passes()       │   │
│  │       {                                                                     │   │
│  │           var result = await LabScenario.ZeroKelvin.RunAsync(policy, ct);   │   │
│  │           Assert.True(result.Verdict.Passed); // ONLY evaluation             │   │
│  │       }                                                                     │   │
│  │   }                                                                         │   │
│  │                                                                             │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Folder Structure

```
tests/
└── ReliabilityLab/                              # NEW: Top-level reliability test domain
    ├── Gabi.ReliabilityLab.Core/                # Experiment engine (no pipeline knowledge)
    │   ├── Experiment/
    │   │   ├── ExperimentDefinition.cs          # What is tested
    │   │   ├── ExperimentRunner.cs              # How it runs
    │   │   ├── ExperimentContext.cs             # Runtime context
    │   │   ├── ExperimentResult.cs              # Structured output
    │   │   └── RunCoordinator.cs                # Parallelism & resource management
    │   ├── Configuration/
    │   │   ├── ReliabilityLabOptions.cs         # IOptions<T> strongly typed config
    │   │   └── ExperimentTimeouts.cs            # Timeout policies
    │   └── Randomization/
    │       ├── DeterministicRandom.cs           # Seeded RNG
    │       └── RandomExtensions.cs              # Deterministic shuffling, sampling
    │
    ├── Gabi.ReliabilityLab.Environment/         # Infrastructure lifecycle
    │   ├── Abstractions/
    │   │   ├── IEnvironmentController.cs        # Main interface
    │   │   ├── IReadinessProbe.cs               # Health checking
    │   │   ├── IResourceIsolator.cs             # Network/fs isolation
    │   │   └── EnvironmentHandle.cs             # Disposable handle
    │   ├── Drivers/
    │   │   ├── DockerComposeDriver.cs           # Docker Compose implementation
    │   │   └── TestcontainersDriver.cs          # Testcontainers fallback
    │   ├── Health/
    │   │   ├── CompositeReadinessProbe.cs       # Aggregates multiple probes
    │   │   ├── PostgreSqlReadinessProbe.cs
    │   │   ├── RedisReadinessProbe.cs
    │   │   └── ElasticsearchReadinessProbe.cs
    │   └── Clock/
    │       ├── IClock.cs                        # Time abstraction
    │       ├── SystemClock.cs                   # Production
    │       └── StoppedClock.cs                  # Deterministic tests
    │
    ├── Gabi.ReliabilityLab.Telemetry/           # Structured measurements
    │   ├── Contracts/
    │   │   ├── ExecutionTrace.cs                # Full trace tree
    │   │   ├── ResourceMetrics.cs               # CPU/memory/GC
    │   │   ├── StageMetrics.cs                  # Per-stage measurements
    │   │   ├── EventTimeline.cs                 # Ordered event log
    │   │   └── TelemetryContext.cs              # Correlation IDs
    │   ├── OpenTelemetry/
    │   │   ├── OtelTelemetryProvider.cs         # OTel integration
    │   │   ├── TraceIdGenerator.cs              # Deterministic trace IDs
    │   │   └── MetricAggregator.cs              # Metric rollup
    │   └── Capture/
    │       ├── InMemoryTelemetrySink.cs         # Test telemetry storage
    │       ├── TelemetrySession.cs              # Scoped capture
    │       └── ResourceMonitor.cs               # Periodic sampling
    │
    ├── Gabi.ReliabilityLab.Verification/        # Data verification framework
    │   ├── Abstractions/
    │   │   ├── IIntegrityCheck.cs               # Bit-exact verification
    │   │   ├── ISemanticCheck.cs                # Content preservation
    │   │   ├── IConsistencyCheck.cs             # Distributed consistency
    │   │   ├── IVerificationResult.cs           # Check output
    │   │   └── IVerificationPipeline.cs         # Composable checks
    │   ├── Integrity/
    │   │   ├── Sha256IntegrityCheck.cs          # Fingerprint matching
    │   │   ├── SchemaIntegrityCheck.cs          # JSON/XML validation
    │   │   └── ReferenceIntegrityCheck.cs       # FK relationships
    │   ├── Semantic/
    │   │   ├── ContentPreservationCheck.cs      # No truncation
    │   │   ├── EncodingStabilityCheck.cs        # UTF-8 consistency
    │   │   └── MetadataAccuracyCheck.cs         # Timestamps, IDs
    │   └── Consistency/
    │       ├── IdempotencyCheck.cs              # Replay safety
    │       ├── EventualConsistencyCheck.cs      # Convergence detection
    │       └── OrderingCheck.cs                 # Sequence validation
    │
    ├── Gabi.ReliabilityLab.Policies/            # Evaluation policy engine
    │   ├── Contracts/
    │   │   ├── IReliabilityPolicy.cs            # Reliability thresholds
    │   │   ├── IDataQualityPolicy.cs            # Data correctness rules
    │   │   ├── IPerformancePolicy.cs            # SLO thresholds
    │   │   └── IPolicyEvaluator.cs              # Rule engine
    │   ├── Policies/
    │   │   ├── DefaultReliabilityPolicy.cs
    │   │   ├── DefaultDataQualityPolicy.cs
    │   │   └── DefaultPerformancePolicy.cs
    │   ├── Evaluator/
    │   │   ├── PolicyEvaluator.cs               # Threshold evaluation
    │   │   ├── PolicyVerdict.cs                 # Pass/Fail with evidence
    │   │   └── ThresholdRule.cs                 # Declarative rule
    │   └── Thresholds/
    │       ├── LatencyThreshold.cs
    │       ├── ThroughputThreshold.cs
    │       ├── LossRateThreshold.cs
    │       └── MemoryThreshold.cs
    │
    ├── Gabi.ReliabilityLab.Reporting/           # Diagnostic reporting
    │   ├── Contracts/
    │   │   ├── IReportGenerator.cs              # Report abstraction
    │   │   └── IArtifactPublisher.cs            # Output management
    │   ├── Generators/
    │   │   ├── JsonReportGenerator.cs           # summary.json, metrics.json
    │   │   ├── MarkdownReportGenerator.cs       # failures.md
    │   │   └── TimelineVisualizer.cs            # timeline.json
    │   ├── Artifacts/
    │   │   ├── ArtifactManager.cs               # Directory structure
    │   │   ├── ReliabilityArtifact.cs           # Artifact metadata
    │   │   └── RetentionPolicy.cs               # Cleanup rules
    │   └── Templates/
    │       └── FailureAnalysisTemplate.cs       # Structured failure docs
    │
    ├── Gabi.ReliabilityLab.Scenarios/           # Concrete pipeline scenarios
    │   ├── Abstractions/
    │   │   ├── ILabScenario.cs                  # Scenario interface
    │   │   ├── ScenarioContext.cs               # Scenario-specific context
    │   │   └── ScenarioResult.cs                # Scenario output
    │   ├── ZeroKelvin/
    │   │   ├── ZeroKelvinScenario.cs            # Full pipeline validation
    │   │   ├── ZeroKelvinWorkload.cs            # Document generation
    │   │   ├── ZeroKelvinStages.cs              # Stage definitions
    │   │   └── ZeroKelvinVerifier.cs            # Pipeline-specific checks
    │   ├── Backpressure/
    │   │   ├── BackpressureScenario.cs          # Overload handling
    │   │   └── BackpressureProfile.cs           # Load patterns
    │   ├── Chaos/
    │   │   ├── ChaosScenario.cs                 # Fault injection
    │   │   └── FaultProfile.cs                  # Failure modes
    │   └── Recovery/
    │       ├── RecoveryScenario.cs              # Crash recovery
    │       └── CheckpointStrategy.cs            # State recovery
    │
    └── Gabi.ReliabilityLab.xUnit/               # xUnit adapter layer (thin)
        ├── Fixtures/
        │   └── ReliabilityLabFixture.cs         # Shared test context
        ├── Attributes/
        │   ├── ReliabilityTestAttribute.cs      # Custom test metadata
        │   └── ScenarioDataAttribute.cs         # Parameterized scenarios
        ├── Discoverers/
        │   └── ScenarioDiscoverer.cs            # xUnit extensibility
        └── Adapters/
            └── ScenarioTestAdapter.cs           # ILabScenario → xUnit test
```

---

## 4. Key Contracts (Must Implement Exactly)

### 4.1 Experiment Engine Core

```csharp
// ============================================================
// EXPERIMENT DEFINITION
// ============================================================

/// <summary>
/// Immutable definition of an experiment. 
/// Fully serializable for reproducibility.
/// </summary>
public sealed record ExperimentDefinition
{
    public required string Name { get; init; }
    public required string Version { get; init; } = "1.0.0";
    
    /// <summary>
    /// Deterministic seed for all randomization.
    /// Same seed → same execution path.
    /// </summary>
    public required int Seed { get; init; }
    
    /// <summary>
    /// Global timeout for entire experiment.
    /// </summary>
    public required TimeSpan Timeout { get; init; }
    
    /// <summary>
    /// Stage definitions in execution order.
    /// </summary>
    public required IReadOnlyList<StageDefinition> Stages { get; init; }
    
    /// <summary>
    /// Workload parameters (data volume, concurrency, etc.)
    /// </summary>
    public required WorkloadParameters Workload { get; init; }
    
    /// <summary>
    /// Arbitrary metadata for traceability.
    /// </summary>
    public IReadOnlyDictionary<string, string> Metadata { get; init; } = 
        new Dictionary<string, string>();
}

public sealed record StageDefinition
{
    public required string Name { get; init; }
    public required TimeSpan Timeout { get; init; }
    public IReadOnlyList<string> Dependencies { get; init; } = Array.Empty<string>();
    public StageIsolation Isolation { get; init; } = StageIsolation.None;
}

public sealed record WorkloadParameters
{
    public int DocumentCount { get; init; } = 1000;
    public int Concurrency { get; init; } = 4;
    public DataShape DataShape { get; init; } = new();
    public FaultProfile? FaultInjection { get; init; }
}

// ============================================================
// EXPERIMENT RUNNER
// ============================================================

/// <summary>
/// Executes experiments with deterministic guarantees.
/// No pipeline knowledge — purely generic orchestration.
/// </summary>
public interface IExperimentRunner
{
    /// <summary>
    /// Executes an experiment according to its definition.
    /// </summary>
    Task<ExperimentResult> RunAsync(
        ExperimentDefinition definition,
        IEnvironmentController environment,
        ExperimentContext context,
        CancellationToken ct = default);
}

/// <summary>
/// Runtime context for an experiment.
/// Provides services to stage executors.
/// </summary>
public sealed class ExperimentContext
{
    public required IServiceProvider Services { get; init; }
    public required ITelemetryCollector Telemetry { get; init; }
    public required IClock Clock { get; init; }
    public required DeterministicRandom Random { get; init; }
    public required CancellationTokenSource TimeoutCts { get; init; }
    
    /// <summary>
    /// Per-experiment correlation ID.
    /// </summary>
    public required string CorrelationId { get; init; }
}

// ============================================================
// EXPERIMENT RESULT
// ============================================================

/// <summary>
/// Immutable result of an experiment execution.
/// Contains all data needed for post-hoc analysis.
/// </summary>
public sealed record ExperimentResult
{
    public required string ExperimentId { get; init; }
    public required string CorrelationId { get; init; }
    public required DateTimeOffset StartTime { get; init; }
    public required DateTimeOffset EndTime { get; init; }
    public required TimeSpan Duration { get; init; }
    public required ExperimentStatus Status { get; init; }
    
    /// <summary>
    /// Per-stage results in execution order.
    /// </summary>
    public required IReadOnlyList<StageResult> StageResults { get; init; }
    
    /// <summary>
    /// Aggregated telemetry from all stages.
    /// </summary>
    public required ExecutionTelemetry Telemetry { get; init; }
    
    /// <summary>
    /// If experiment failed, the root cause.
    /// </summary>
    public ExperimentFailure? Failure { get; init; }
    
    /// <summary>
    /// Verifier outputs (opaque — interpretation is policy layer's job)
    /// </summary>
    public IReadOnlyDictionary<string, IVerificationResult> VerificationResults { get; init; } = 
        new Dictionary<string, IVerificationResult>();
}
```

### 4.2 Environment Controller

```csharp
/// <summary>
/// Controls infrastructure lifecycle.
/// No business logic — only container/infra management.
/// </summary>
public interface IEnvironmentController : IAsyncDisposable
{
    /// <summary>
    /// Starts all infrastructure components.
    /// Idempotent — safe to call multiple times.
    /// </summary>
    Task<EnvironmentHandle> StartAsync(CancellationToken ct = default);
    
    /// <summary>
    /// Resets to clean state without full teardown.
    /// Faster than Start/Stop cycle.
    /// </summary>
    Task ResetAsync(CancellationToken ct = default);
    
    /// <summary>
    /// Stops all infrastructure.
    /// Guaranteed execution (use IAsyncDisposable).
    /// </summary>
    Task StopAsync(CancellationToken ct = default);
    
    /// <summary>
    /// Current readiness status of all components.
    /// </summary>
    Task<ReadinessSnapshot> GetReadinessAsync(CancellationToken ct = default);
    
    /// <summary>
    /// Connection strings and endpoints for started infrastructure.
    /// Throws if not started.
    /// </summary>
    InfrastructureEndpoints Endpoints { get; }
}

/// <summary>
/// Disposable handle for an active environment.
/// Ensures cleanup via 'using' pattern.
/// </summary>
public sealed class EnvironmentHandle : IAsyncDisposable
{
    public required string HandleId { get; init; }
    public required InfrastructureEndpoints Endpoints { get; init; }
    public required IReadinessProbe ReadinessProbe { get; init; }
    public required Func<CancellationToken, Task> OnDispose { get; init; }
    
    public ValueTask DisposeAsync() => new(OnDispose(CancellationToken.None));
}

public sealed record InfrastructureEndpoints
{
    public required string PostgreSqlConnectionString { get; init; }
    public required string RedisConnectionString { get; init; }
    public required string ElasticsearchUrl { get; init; }
    public required string ApiEndpoint { get; init; }
}
```

### 4.3 Policy Engine

```csharp
/// <summary>
/// Declarative policy for reliability requirements.
/// </summary>
public interface IReliabilityPolicy
{
    int MaxCrashCount { get; }
    int MaxRetryCount { get; }
    bool RequireDlqEmpty { get; }
    bool RequireAllStagesComplete { get; }
}

/// <summary>
/// Declarative policy for data quality requirements.
/// </summary>
public interface IDataQualityPolicy
{
    double MaxLossRate { get; }
    double MaxDuplicationRate { get; }
    double MinSemanticPreservationScore { get; }
    double MaxCorruptionRate { get; }
}

/// <summary>
/// Declarative policy for performance SLOs.
/// </summary>
public interface IPerformancePolicy
{
    IReadOnlyDictionary<string, TimeSpan> StageP95Latency { get; }
    IReadOnlyDictionary<string, TimeSpan> StageP99Latency { get; }
    IReadOnlyDictionary<string, double> MinThroughput { get; }
    double MaxMemoryMb { get; }
    TimeSpan MaxTotalDuration { get; }
}

/// <summary>
/// Evaluates experiment results against policies.
/// Pure function — no side effects.
/// </summary>
public interface IPolicyEvaluator
{
    PolicyVerdict Evaluate(
        ExperimentResult result,
        IReliabilityPolicy reliability,
        IDataQualityPolicy dataQuality,
        IPerformancePolicy performance);
}

/// <summary>
/// Immutable verdict from policy evaluation.
/// </summary>
public sealed record PolicyVerdict
{
    public required bool Passed { get; init; }
    public required IReadOnlyList<PolicyViolation> Violations { get; init; }
    public required IReadOnlyList<PolicyWarning> Warnings { get; init; }
    public required IReadOnlyDictionary<string, PolicyEvidence> Evidence { get; init; }
}
```

### 4.4 xUnit Adapter (Thin Layer)

```csharp
/// <summary>
/// Minimal xUnit adapter — xUnit only hosts, never orchestrates.
/// </summary>
public interface ILabScenario
{
    string ScenarioName { get; }
    string ScenarioVersion { get; }
    
    /// <summary>
    /// Runs the scenario with given policies.
    /// This is the ONLY method xUnit calls.
    /// </summary>
    Task<ScenarioResult> RunAsync(
        IPolicySet policies,
        CancellationToken ct = default);
}

/// <summary>
/// Result of a scenario execution with policy evaluation.
/// </summary>
public sealed record ScenarioResult
{
    public required string ScenarioName { get; init; }
    public required ExperimentResult Experiment { get; init; }
    public required PolicyVerdict Verdict { get; init; }
    public required string ArtifactPath { get; init; }
}
```

---

## 5. Execution Lifecycle

```
PHASE 1: PREPARATION
─────────────────────
1.1 Load ExperimentDefinition (from code, JSON, or database)
1.2 Validate definition (schema, dependencies, timeout constraints)
1.3 Initialize DeterministicRandom with Seed
1.4 Create ExperimentContext with services, clock, telemetry, correlation ID
1.5 Initialize CancellationTokenSource with Timeout

PHASE 2: ENVIRONMENT PROVISIONING
──────────────────────────────────
2.1 IEnvironmentController.StartAsync()
    ├── 2.1.1 Start PostgreSQL container
    ├── 2.1.2 Start Redis container
    ├── 2.1.3 Start Elasticsearch container
    ├── 2.1.4 Run health probes (retry with backoff)
    ├── 2.1.5 Apply database migrations
    └── 2.1.6 Return EnvironmentHandle
2.2 Wait for Clock Stabilization Delay (configurable, e.g., 2s)
2.3 Capture baseline ResourceMetrics

PHASE 3: STAGE EXECUTION (per StageDefinition)
───────────────────────────────────────────────
3.1 For each stage in dependency order:
    ├── 3.1.1 Create StageContext from ExperimentContext
    ├── 3.1.2 Start telemetry span for stage
    ├── 3.1.3 Create stage-specific CancellationToken (linked to global)
    ├── 3.1.4 EXECUTE STAGE (implementation-specific)
    ├── 3.1.5 Capture StageMetrics (items, latency percentiles, throughput)
    ├── 3.1.6 Close telemetry span
    └── 3.1.7 If stage failed → capture failure, decide: abort / continue
    
PHASE 4: DATA VERIFICATION
───────────────────────────
4.1 Run IIntegrityCheck implementations (SHA-256, schema, reference)
4.2 Run ISemanticCheck implementations (content preservation, encoding)
4.3 Run IConsistencyCheck implementations (idempotency, convergence)
4.4 Aggregate all IVerificationResult into dictionary

PHASE 5: TELEMETRY AGGREGATION
───────────────────────────────
5.1 Collect all spans into ExecutionTrace
5.2 Rollup metrics (min, max, p50, p95, p99)
5.3 Capture final ResourceMetrics (peak memory, GC counts)
5.4 Build EventTimeline from structured logs

PHASE 6: POLICY EVALUATION
───────────────────────────
6.1 IPolicyEvaluator.Evaluate() against all policies
6.2 Generate PolicyVerdict (Passed/Failed with evidence)
6.3 Collect all PolicyViolations and PolicyWarnings

PHASE 7: REPORT GENERATION
───────────────────────────
7.1 Create artifact directory: artifacts/reliability/{timestamp}_{experimentId}/
7.2 Generate summary.json (high-level verdict)
7.3 Generate metrics.json (all telemetry aggregates)
7.4 Generate timeline.json (execution trace)
7.5 Generate verification.json (check results with evidence)
7.6 If violations exist → generate failures.md (human-readable analysis)
7.7 Copy raw telemetry to raw/ subdirectory

PHASE 8: ENVIRONMENT TEARDOWN
──────────────────────────────
8.1 IEnvironmentController.StopAsync() (or DisposeAsync on handle)
8.2 Guarantee: resources freed even if earlier phases failed

PHASE 9: RESULT RETURN
───────────────────────
9.1 Construct ExperimentResult
9.2 Construct ScenarioResult (including PolicyVerdict and ArtifactPath)
9.3 Return to caller (xUnit or harness)
```

---

## 6. Engineering Standards (MANDATORY)

| Standard | Requirement | Enforcement |
|----------|-------------|-------------|
| **Nullable** | `#nullable enable` in all projects | Compiler |
| **Async** | `async/await` all the way, no `.Result`/`.Wait()` | Code review |
| **Cancellation** | `CancellationToken` propagated to all async methods | Analyzer |
| **No Static State** | No mutable static fields | Architecture tests |
| **Determinism** | Seeded RNG, `IClock` abstraction, no `DateTime.Now` | Unit tests |
| **Configuration** | Strongly typed `IOptions<T>` | DI container |
| **Logging** | Structured logging only (no string interpolation) | Analyzer |
| **No Reflection** | No reflection-based hacks | Code review |
| **Timing** | No timing-dependent assertions (use policies) | Code review |
| **IDs** | Ulid or deterministic GUIDs | Code review |

---

## 7. Integration with Existing Code

The existing `Gabi.ZeroKelvinHarness` becomes a **consumer** of the Reliability Lab:

```
Gabi.ZeroKelvinHarness (refactored)
    ├── Infrastructure/EnvironmentAdapter.cs    (implements IEnvironmentController)
    ├── Stages/                                 (stage executors)
    ├── Verification/                           (pipeline-specific checks)
    └── ZeroKelvinScenario.cs                 (implements ILabScenario)
```

**Key constraint:** The existing harness logic moves INTO the scenario; the lab provides the framework around it.

---

## 8. NuGet Package Dependencies

```xml
<!-- Core (minimal dependencies) -->
<PackageReference Include="Microsoft.Extensions.Options" Version="8.0.0" />
<PackageReference Include="Microsoft.Extensions.Logging.Abstractions" Version="8.0.0" />

<!-- Environment -->
<PackageReference Include="Testcontainers.PostgreSql" Version="4.4.0" />
<PackageReference Include="Testcontainers.Redis" Version="4.4.0" />
<PackageReference Include="Testcontainers.Elasticsearch" Version="4.4.0" />

<!-- Telemetry -->
<PackageReference Include="System.Diagnostics.DiagnosticSource" Version="8.0.0" />
<PackageReference Include="OpenTelemetry" Version="1.7.0" />

<!-- xUnit Adapter -->
<PackageReference Include="xunit" Version="2.6.2" />
<PackageReference Include="xunit.abstractions" Version="2.0.3" />
```

---

## 9. Success Criteria

The implementation is complete when:

1. ✅ All 7 layers compile with `#nullable enable` and zero warnings
2. ✅ Architecture tests verify no layer violations (Core doesn't reference infra)
3. ✅ Unit tests verify `DeterministicRandom` produces same sequence for same seed
4. ✅ Integration test spins up environment via `IEnvironmentController`
5. ✅ `ZeroKelvinScenario` runs full pipeline and produces `ScenarioResult`
6. ✅ Policy evaluator correctly identifies violations (test with failing thresholds)
7. ✅ Artifacts are generated in `artifacts/reliability/{timestamp}/`
8. ✅ xUnit test runs via `ILabScenario.RunAsync()` with single assertion on `Verdict.Passed`
9. ✅ Existing `Gabi.ZeroKelvinHarness` tests pass (backwards compatibility)

---

## 10. Prompt for Implementation LLM

> **You are a principal .NET engineer implementing the GABI Reliability Lab.**
>
> **Your task:** Implement the complete reliability validation platform specified in this document.
>
> **Context:**
> - Existing codebase: .NET 8 distributed data pipeline for legal document ingestion
> - Existing test harness: `tests/System/Gabi.ZeroKelvinHarness/` (to be refactored)
> - Target framework: .NET 8.0
> - C# version: 12.0
> - Nullable reference types: ENABLED (mandatory)
>
> **Instructions:**
> 1. Create the folder structure under `tests/ReliabilityLab/`
> 2. Implement projects in dependency order: Core → Environment → Telemetry → Verification → Policies → Reporting → Scenarios → xUnit
> 3. Each project must have its own `.csproj` with correct references
> 4. Follow the contracts in Section 4 exactly — no deviations without explicit justification
> 5. Implement `ZeroKelvinScenario` as the first concrete scenario, refactoring existing harness code
> 6. Add all projects to `GabiSync.sln` in appropriate solution folders
>
> **Engineering Standards (non-negotiable):**
> - `#nullable enable` in every project
> - `async/await` everywhere — no `.Result`, no `.Wait()`, no `Task.Run` without justification
> - `CancellationToken` propagated to every async method
> - No mutable static state
> - Use `IOptions<T>` for configuration
> - Structured logging via `Microsoft.Extensions.Logging`
> - No reflection hacks
> - No timing-dependent assertions
>
> **Files to examine before starting:**
> - `tests/System/Gabi.ZeroKelvinHarness/` — understand existing harness
> - `src/Gabi.Contracts/` — understand domain contracts
> - `src/Gabi.Postgres/` — understand database schema
>
> **Deliverables:**
> 1. All project files created and added to solution
> 2. All interfaces and contracts implemented
> 3. `ZeroKelvinScenario` fully functional
> 4. xUnit adapter allowing `[Fact]` tests that call `ILabScenario.RunAsync()`
> 5. Sample test demonstrating end-to-end usage
> 6. README.md in `tests/ReliabilityLab/` explaining architecture
>
> **Begin implementation.**

---

*End of Document*
