# Job Queue System Design for GABI

> **Status:** Design Document  
> **Date:** 2026-02-12  
> **Related:** `roadmap.md`, `LAYERED_ARCHITECTURE.md`, `DATA_LIFECYCLE.md`

---

## Executive Summary

This document designs a production-grade job queue system for GABI's pipeline processing. The system will handle asynchronous processing of sources (web_crawl, api_pagination, static_url) with reliability guarantees including retries, deduplication, priority handling, and job cancellation.

**Key Decisions:**
- **Primary:** PostgreSQL-based queue with `SKIP LOCKED` (Phase 1)
- **Secondary:** Hangfire for complex scheduling (Phase 2)
- **Worker Pool:** Channel-based with configurable concurrency
- **Storage:** Single source of truth in PostgreSQL

---

## Table of Contents

1. [Requirements Analysis](#1-requirements-analysis)
2. [Option Evaluation](#2-option-evaluation)
3. [Selected Architecture](#3-selected-architecture)
4. [Database Schema](#4-database-schema)
5. [Job State Machine](#5-job-state-machine)
6. [Worker Pool Architecture](#6-worker-pool-architecture)
7. [Dead Letter Queue (DLQ)](#7-dead-letter-queue-dlq)
8. [Monitoring & Metrics](#8-monitoring--metrics)
9. [Implementation Plan](#9-implementation-plan)
10. [Code Examples](#10-code-examples)

---

## 1. Requirements Analysis

### 1.1 Functional Requirements

| Requirement | Description | Priority |
|------------|-------------|----------|
| Async Processing | Process sources without blocking | P0 |
| Source Types | Support web_crawl, api_pagination, static_url | P0 |
| Retry Logic | Exponential backoff for failures | P0 |
| Deduplication | Prevent duplicate job execution | P0 |
| Priority Queue | High-priority sources first | P1 |
| Cancellation | Graceful job cancellation | P1 |
| Observability | Metrics, logs, tracing | P1 |
| DLQ | Failed job isolation | P1 |

### 1.2 Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Throughput | 100 jobs/min minimum |
| Latency | < 1s job pickup |
| Reliability | 99.9% job completion |
| Memory | < 100MB queue overhead |
| Concurrency | Configurable (1-N workers) |

### 1.3 Source Types Mapping

```
┌─────────────────┬────────────────────────────────────────┐
│ Source Type     │ Characteristics                        │
├─────────────────┼────────────────────────────────────────┤
│ static_url      │ Single job, fast, idempotent           │
│ url_pattern     │ Multi-job (per URL), parallelizable    │
│ web_crawl       │ Single job, long-running, recursive    │
│ api_pagination  │ Single job, stateful, resume-capable   │
└─────────────────┴────────────────────────────────────────┘
```

---

## 2. Option Evaluation

### 2.1 Option Matrix

| Criteria | Hangfire | Quartz.NET | Channel-based | PostgreSQL+SKIP LOCKED |
|----------|----------|------------|---------------|------------------------|
| **Complexity** | Medium | Medium | Low | Low |
| **Reliability** | High | High | Medium | High |
| **Observability** | Excellent | Good | Custom needed | Custom needed |
| **Scheduling** | Built-in | Excellent | None | Minimal |
| **Scalability** | Good | Good | Process-bound | Database-bound |
| **Dependencies** | Redis/PG | None | None | PostgreSQL |
| **Learning Curve** | Medium | Medium | Low | Low |
| **Retry Logic** | Built-in | Built-in | Custom | Custom |
| **Priority Queue** | Limited | Limited | Easy | Easy |
| **DLQ** | Built-in | Manual | Custom | Custom |

### 2.2 Detailed Analysis

#### Option 1: Hangfire

```csharp
// Hangfire approach
public class SyncJob
{
    [AutomaticRetry(Attempts = 3, DelaysInSeconds = new[] { 10, 30, 60 })]
    [Queue("high-priority")]
    public async Task ExecuteSync(string sourceId, CancellationToken ct)
    {
        // Job implementation
    }
}

// Scheduling
RecurringJob.AddOrUpdate<SyncJob>(
    "tcu_acordaos",
    x => x.ExecuteSync("tcu_acordaos", CancellationToken.None),
    Cron.Daily(2, 0));
```

**Pros:**
- Mature ecosystem
- Built-in dashboard
- Automatic retries
- Excellent monitoring

**Cons:**
- Additional dependency (Redis or PostgreSQL storage)
- Higher resource usage
- Complex for simple needs

#### Option 2: Quartz.NET

```csharp
// Quartz approach
public class SyncJob : IJob
{
    public async Task Execute(IJobExecutionContext context)
    {
        var sourceId = context.JobDetail.JobDataMap.GetString("sourceId");
        // Job implementation
    }
}

// Scheduling
var trigger = TriggerBuilder.Create()
    .WithCronSchedule("0 0 2 * * ?") // Daily at 2 AM
    .Build();
```

**Pros:**
- No external storage needed
- Powerful scheduling expressions
- Mature and stable

**Cons:**
- In-memory = lost jobs on restart
- Requires persistent job store for reliability
- Complex retry configuration

#### Option 3: Custom Channel-based

```csharp
// Channel-based approach
var channel = Channel.CreateBounded<JobRequest>(
    new BoundedChannelOptions(1000));

// Producer
await channel.Writer.WriteAsync(new JobRequest { ... });

// Consumer pool
var workers = Enumerable.Range(0, workerCount)
    .Select(_ => Task.Run(async () => {
        await foreach (var job in channel.Reader.ReadAllAsync())
            await ProcessJobAsync(job);
    }));
```

**Pros:**
- Zero dependencies
- High performance
- Full control

**Cons:**
- Lost jobs on process restart
- Must implement persistence layer
- Custom retry logic needed

#### Option 4: PostgreSQL + SKIP LOCKED ⭐ RECOMMENDED

```sql
-- Atomically pick next job
WITH next_job AS (
    SELECT id 
    FROM job_queue 
    WHERE status = 'pending' 
      AND scheduled_at <= NOW()
    ORDER BY priority DESC, created_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE job_queue 
SET status = 'running', 
    worker_id = @workerId,
    started_at = NOW()
FROM next_job
WHERE job_queue.id = next_job.id
RETURNING *;
```

**Pros:**
- Single source of truth (PostgreSQL)
- ACID guarantees
- No additional infrastructure
- Horizontal scaling ready
- Simple and transparent

**Cons:**
- Requires custom implementation
- Polling-based (can use LISTEN/NOTIFY)

### 2.3 Decision

**Hybrid Approach:**

| Phase | Component | Technology |
|-------|-----------|------------|
| **Phase 1** | Job Queue | PostgreSQL + SKIP LOCKED |
| **Phase 1** | Worker Pool | Channel-based (in-process) |
| **Phase 2** | Scheduling | Quartz.NET (optional) |
| **Phase 2** | Distributed | Hangfire (if multi-instance) |

**Rationale:**
1. PostgreSQL already in stack (no new deps)
2. SKIP LOCKED = industry standard (used by Sidekiq, etc.)
3. Channel-based workers = high performance
4. Can migrate to Hangfire later without data loss

---

## 3. Selected Architecture

### 3.1 High-Level Design

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Gabi.Worker                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │   Scheduler  │  │   Worker     │  │   Worker     │  │   Worker     │   │
│  │   (Hosted)   │  │   #1         │  │   #2         │  │   #N         │   │
│  │              │  │              │  │              │  │              │   │
│  │ • Cron parse │  │ • Dequeue    │  │ • Dequeue    │  │ • Dequeue    │   │
│  │ • Enqueue    │  │ • Execute    │  │ • Execute    │  │ • Execute    │   │
│  │ • Reschedule │  │ • Heartbeat  │  │ • Heartbeat  │  │ • Heartbeat  │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
│         │                 │                 │                 │            │
│         └─────────────────┴────────┬────────┴─────────────────┘            │
│                                    │                                       │
│                         ┌──────────▼──────────┐                           │
│                         │   Job Channel       │                           │
│                         │   (BoundedChannel)  │                           │
│                         └──────────┬──────────┘                           │
└────────────────────────────────────┼──────────────────────────────────────┘
                                     │
                                     │ SQL
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PostgreSQL                                         │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                         job_queue                                     │  │
│  │  ┌─────────┬─────────┬─────────┬─────────┬─────────┬───────────────┐  │  │
│  │  │  id     │source_id│ status  │priority │payload  │ retry_count   │  │  │
│  │  ├─────────┼─────────┼─────────┼─────────┼─────────┼───────────────┤  │  │
│  │  │ uuid    │ string  │ enum    │ int     │ jsonb   │ int           │  │  │
│  │  └─────────┴─────────┴─────────┴─────────┴─────────┴───────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                         job_dlq                                       │  │
│  │  ┌─────────┬─────────┬─────────┬─────────┬──────────────────────────┐ │  │
│  │  │  id     │ job_id  │ error   │stacktrace│ resolved_at              │ │  │
│  │  ├─────────┼─────────┼─────────┼─────────┼──────────────────────────┤ │  │
│  │  │ uuid    │ uuid    │ text    │ text    │ timestamp                │ │  │
│  │  └─────────┴─────────┴─────────┴─────────┴──────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Component Breakdown

```
┌─────────────────────────────────────────────────────────────────┐
│                      IJobQueue (Interface)                       │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │   EnqueueAsync  │  │  DequeueAsync   │  │ CompleteAsync   │ │
│  │   (create job)  │  │  (claim job)    │  │ (finish job)    │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
        ┌──────────────────────┐  ┌──────────────────────┐
        │ PostgreSqlJobQueue   │  │  InMemoryJobQueue    │
        │   (Production)       │  │  (Testing/Dev)       │
        └──────────────────────┘  └──────────────────────┘
```

---

## 4. Database Schema

### 4.1 Job Queue Table

```sql
-- Main job queue table
CREATE TABLE job_queue (
    -- Primary identification
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id VARCHAR(100) NOT NULL,
    job_type VARCHAR(50) NOT NULL DEFAULT 'sync', -- sync, crawl, api_fetch
    
    -- Job payload and configuration
    payload JSONB NOT NULL DEFAULT '{}',
    -- Example: {"discovery_config": {...}, "pipeline_options": {...}}
    
    -- State machine
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- pending, running, completed, failed, cancelled, scheduled
    
    -- Priority (higher = first)
    priority INTEGER NOT NULL DEFAULT 5,
    -- 10 = critical, 5 = normal, 1 = background
    
    -- Scheduling
    scheduled_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- Retry configuration
    max_retries INTEGER NOT NULL DEFAULT 3,
    retry_count INTEGER NOT NULL DEFAULT 0,
    retry_delay INTERVAL NOT NULL DEFAULT '30 seconds',
    last_retry_at TIMESTAMP WITH TIME ZONE,
    
    -- Worker tracking
    worker_id VARCHAR(100), -- hostname:process_id:worker_number
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    
    -- Timeout and heartbeat
    timeout_seconds INTEGER NOT NULL DEFAULT 3600, -- 1 hour
    last_heartbeat_at TIMESTAMP WITH TIME ZONE,
    
    -- Progress tracking (for long-running jobs)
    progress_percent INTEGER DEFAULT 0,
    progress_message TEXT,
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_by VARCHAR(100) DEFAULT 'scheduler',
    
    -- Idempotency key (prevents duplicate jobs)
    idempotency_key VARCHAR(255),
    
    -- Correlation for tracing
    correlation_id UUID DEFAULT gen_random_uuid()
);

-- Indexes for efficient queries
CREATE INDEX idx_job_queue_status_scheduled 
    ON job_queue (status, scheduled_at) 
    WHERE status IN ('pending', 'scheduled');

CREATE INDEX idx_job_queue_status_priority 
    ON job_queue (status, priority DESC, created_at ASC) 
    WHERE status = 'pending';

CREATE INDEX idx_job_queue_worker_running 
    ON job_queue (worker_id, status) 
    WHERE status = 'running';

CREATE INDEX idx_job_queue_source_id 
    ON job_queue (source_id, created_at DESC);

CREATE INDEX idx_job_queue_idempotency 
    ON job_queue (idempotency_key) 
    WHERE idempotency_key IS NOT NULL;

-- Unique constraint for idempotency
CREATE UNIQUE INDEX idx_job_queue_idempotent_unique 
    ON job_queue (idempotency_key) 
    WHERE idempotency_key IS NOT NULL AND status IN ('pending', 'running', 'scheduled');
```

### 4.2 Dead Letter Queue Table

```sql
CREATE TABLE job_dlq (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_job_id UUID NOT NULL REFERENCES job_queue(id),
    
    -- Failure information
    error_message TEXT NOT NULL,
    error_type VARCHAR(100) NOT NULL,
    stack_trace TEXT,
    
    -- Context at failure
    failed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    worker_id VARCHAR(100),
    retry_count INTEGER NOT NULL,
    
    -- DLQ management
    status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending, retrying, archived, resolved
    resolution_notes TEXT,
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolved_by VARCHAR(100),
    
    -- For replay attempts
    retry_after TIMESTAMP WITH TIME ZONE,
    
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_dlq_status ON job_dlq (status, failed_at);
CREATE INDEX idx_dlq_source ON job_dlq (original_job_id);
```

### 4.3 Job History Table (Optional - for audit)

```sql
CREATE TABLE job_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES job_queue(id),
    
    event_type VARCHAR(50) NOT NULL, -- created, started, completed, failed, retried
    event_data JSONB,
    
    worker_id VARCHAR(100),
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_history_job_id ON job_history (job_id, recorded_at DESC);
```

---

## 5. Job State Machine

### 5.1 State Diagram

```
                         ┌─────────────┐
                         │   START     │
                         └──────┬──────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │      SCHEDULED        │
                    │  (waiting for time)   │
                    └───────────┬───────────┘
                                │ scheduled_at <= NOW()
                                ▼
                    ┌───────────────────────┐
              ┌────▶│        PENDING        │◀──────────────────┐
              │     │  (ready to execute)   │                   │
              │     └───────────┬───────────┘                   │
              │                 │ dequeue()                     │ retry()
              │                 ▼                               │ (exponential
              │     ┌───────────────────────┐                  │  backoff)
       cancel │     │       RUNNING         │──────────────────┘
         │    │     │  (worker executing)   │
         │    │     └───────────┬───────────┘
         │    │                 │
         │    │     ┌───────────┼───────────┐
         │    │     │           │           │
         │    │     ▼           ▼           ▼
         │    │  COMPLETED    FAILED    TIMEOUT/CANCEL
         │    │     │           │           │
         │    │     │           │           │
         │    │     │           ▼           │
         │    │     │   ┌───────────────┐   │
         │    │     │   │ retry < max?  │   │
         │    │     │   └───────┬───────┘   │
         │    │     │           │           │
         │    │     │     YES ──┴── NO      │
         │    │     │           │           │
         │    └─────┘           ▼           │
         │                  ┌──────┐        │
         │                  │ DLQ  │        │
         │                  └──────┘        │
         │                                  │
         └──────────────────────────────────┘
```

### 5.2 State Definitions

| State | Description | Transitions |
|-------|-------------|-------------|
| `scheduled` | Job enqueued for future execution | → pending (when due) |
| `pending` | Ready to be picked up by worker | → running (claimed) |
| `running` | Currently being processed | → completed, failed, cancelled |
| `completed` | Successfully finished | (terminal) |
| `failed` | Error occurred, will retry | → pending (retry) or DLQ |
| `cancelled` | Manually cancelled or timeout | → DLQ |

### 5.3 Retry Strategy

```csharp
// Exponential backoff with jitter
public static class RetryPolicy
{
    public static TimeSpan CalculateDelay(
        int retryCount, 
        TimeSpan baseDelay,
        TimeSpan maxDelay,
        bool addJitter = true)
    {
        // Exponential: 30s, 60s, 120s, 240s, 480s...
        var delay = baseDelay * Math.Pow(2, retryCount);
        
        // Cap at max delay
        if (delay > maxDelay)
            delay = maxDelay;
        
        // Add jitter (±25%) to prevent thundering herd
        if (addJitter)
        {
            var jitter = Random.Shared.NextDouble() * 0.5 - 0.25; // -25% to +25%
            delay = delay * (1 + jitter);
        }
        
        return TimeSpan.FromSeconds(delay.TotalSeconds);
    }
}

// Usage:
// Retry 1: ~30s (22.5s - 37.5s)
// Retry 2: ~60s (45s - 75s)
// Retry 3: ~120s (90s - 150s)
// ... up to max 1 hour
```

---

## 6. Worker Pool Architecture

### 6.1 Worker Types

```
┌─────────────────────────────────────────────────────────────────────┐
│                       WorkerPool (HostedService)                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                    Job Channel                                 │ │
│  │   Channel<JobRequest> (bounded, capacity = worker_count * 2)  │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                              │                                      │
│         ┌────────────────────┼────────────────────┐                │
│         │                    │                    │                │
│         ▼                    ▼                    ▼                │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐           │
│  │   Worker 1   │   │   Worker 2   │   │   Worker N   │           │
│  │              │   │              │   │              │           │
│  │ • Dequeue    │   │ • Dequeue    │   │ • Dequeue    │           │
│  │ • Execute    │   │ • Execute    │   │ • Execute    │           │
│  │ • Heartbeat  │   │ • Heartbeat  │   │ • Heartbeat  │           │
│  │ • Report     │   │ • Report     │   │ • Report     │           │
│  └──────────────┘   └──────────────┘   └──────────────┘           │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.2 Worker Lifecycle

```csharp
public interface IJobWorker : IDisposable
{
    string WorkerId { get; }
    JobStatus CurrentStatus { get; }
    string? CurrentJobId { get; }
    
    Task StartAsync(CancellationToken ct);
    Task StopAsync(CancellationToken ct);
}

public enum WorkerStatus
{
    Idle,       // Waiting for job
    Busy,       // Processing job
    Stopping,   // Finishing current job
    Stopped     // Not running
}
```

### 6.3 Concurrency Configuration

```csharp
public class WorkerPoolOptions
{
    /// <summary>
    /// Number of parallel workers.
    /// For serverless (1GB RAM): 1-2 workers
    /// For dedicated server: 4-8 workers per CPU core
    /// </summary>
    public int WorkerCount { get; set; } = Environment.ProcessorCount;
    
    /// <summary>
    /// Channel capacity (backpressure).
    /// When full, new jobs wait in database.
    /// </summary>
    public int ChannelCapacity { get; set; } = 100;
    
    /// <summary>
    /// How often to poll database for new jobs (when channel empty).
    /// </summary>
    public TimeSpan PollInterval { get; set; } = TimeSpan.FromSeconds(5);
    
    /// <summary>
    /// Heartbeat interval (for timeout detection).
    /// </summary>
    public TimeSpan HeartbeatInterval { get; set; } = TimeSpan.FromSeconds(30);
    
    /// <summary>
    /// Graceful shutdown timeout.
    /// </summary>
    public TimeSpan ShutdownTimeout { get; set; } = TimeSpan.FromMinutes(1);
}
```

### 6.4 Job Executor Interface

```csharp
/// <summary>
/// Executes a specific type of job.
/// Implementations are registered by job type.
/// </summary>
public interface IJobExecutor
{
    string JobType { get; }
    
    /// <summary>
    /// Execute the job. Can report progress via IProgress<JobProgress>.
    /// </summary>
    Task<JobResult> ExecuteAsync(
        JobRequest job,
        IProgress<JobProgress> progress,
        CancellationToken ct);
}

public record JobResult
{
    public bool Success { get; init; }
    public string? ErrorMessage { get; init; }
    public string? ErrorType { get; init; }
    public Dictionary<string, object> Metadata { get; init; } = new();
}

public record JobProgress
{
    public int PercentComplete { get; init; }
    public string Message { get; init; } = string.Empty;
    public Dictionary<string, object> Metrics { get; init; } = new();
}
```

---

## 7. Dead Letter Queue (DLQ)

### 7.1 DLQ Triggers

A job goes to DLQ when:
1. **Max retries exceeded** - Failed N times
2. **Permanent error** - Non-retryable error (e.g., invalid config)
3. **Timeout** - Running longer than max timeout
4. **Cancelled** - Manually cancelled by admin

### 7.2 DLQ Management

```csharp
public interface IDlqManager
{
    /// <summary>
    /// List failed jobs in DLQ.
    /// </summary>
    Task<IReadOnlyList<DlqEntry>> ListAsync(
        DlqFilter filter, 
        CancellationToken ct = default);
    
    /// <summary>
    /// Retry a failed job (move back to queue).
    /// </summary>
    Task<bool> RetryAsync(Guid dlqEntryId, CancellationToken ct = default);
    
    /// <summary>
    /// Archive a DLQ entry (mark as resolved without retry).
    /// </summary>
    Task<bool> ArchiveAsync(
        Guid dlqEntryId, 
        string reason, 
        CancellationToken ct = default);
    
    /// <summary>
    /// Bulk retry multiple jobs.
    /// </summary>
    Task<int> BulkRetryAsync(IEnumerable<Guid> dlqEntryIds, CancellationToken ct = default);
}
```

### 7.3 DLQ Dashboard (Future)

```
┌─────────────────────────────────────────────────────────────────────┐
│                     DLQ Dashboard (API)                              │
├─────────────────────────────────────────────────────────────────────┤
│  Total Failed: 45  │  Pending Retry: 12  │  Archived: 33           │
├─────────────────────────────────────────────────────────────────────┤
│  Source          │ Error Type      │ Failed At    │ Actions        │
├──────────────────┼─────────────────┼──────────────┼────────────────┤
│  tcu_acordaos    │ Timeout         │ 2 hours ago  │ [Retry] [Arch] │
│  tcu_normas      │ NetworkError    │ 5 hours ago  │ [Retry] [Arch] │
│  web_crawl_1     │ ConfigError     │ 1 day ago    │ [Arch]         │
└──────────────────┴─────────────────┴──────────────┴────────────────┘
```

---

## 8. Monitoring & Metrics

### 8.1 Prometheus Metrics

```csharp
public static class JobQueueMetrics
{
    // Job counters
    public static readonly Counter JobsEnqueuedTotal = Metrics.CreateCounter(
        "gabi_jobs_enqueued_total",
        "Total jobs enqueued",
        new CounterConfiguration { LabelNames = new[] { "source_id", "job_type" } });
    
    public static readonly Counter JobsCompletedTotal = Metrics.CreateCounter(
        "gabi_jobs_completed_total",
        "Total jobs completed",
        new CounterConfiguration { LabelNames = new[] { "source_id", "status" } });
    
    public static readonly Counter JobsFailedTotal = Metrics.CreateCounter(
        "gabi_jobs_failed_total",
        "Total job failures",
        new CounterConfiguration { LabelNames = new[] { "source_id", "error_type" } });
    
    // Gauge - current state
    public static readonly Gauge JobsPending = Metrics.CreateGauge(
        "gabi_jobs_pending",
        "Jobs waiting to be processed",
        new GaugeConfiguration { LabelNames = new[] { "source_id" } });
    
    public static readonly Gauge JobsRunning = Metrics.CreateGauge(
        "gabi_jobs_running",
        "Jobs currently being processed",
        new GaugeConfiguration { LabelNames = new[] { "source_id" } });
    
    public static readonly Gauge DlqSize = Metrics.CreateGauge(
        "gabi_dlq_size",
        "Messages in dead letter queue",
        new GaugeConfiguration { LabelNames = new[] { "source_id" } });
    
    // Histogram - duration
    public static readonly Histogram JobDuration = Metrics.CreateHistogram(
        "gabi_job_duration_seconds",
        "Job execution duration",
        new HistogramConfiguration 
        { 
            LabelNames = new[] { "source_id", "job_type" },
            Buckets = new[] { 1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600 }
        });
    
    // Worker metrics
    public static readonly Gauge WorkersActive = Metrics.CreateGauge(
        "gabi_workers_active",
        "Number of active workers");
    
    public static readonly Counter WorkerHeartbeats = Metrics.CreateCounter(
        "gabi_worker_heartbeats_total",
        "Worker heartbeat count",
        new CounterConfiguration { LabelNames = new[] { "worker_id" } });
}
```

### 8.2 Health Checks

```csharp
public class JobQueueHealthCheck : IHealthCheck
{
    private readonly IJobQueue _queue;
    
    public async Task<HealthCheckResult> CheckHealthAsync(
        HealthCheckContext context, 
        CancellationToken ct = default)
    {
        var stats = await _queue.GetStatisticsAsync(ct);
        
        // Degraded if DLQ has items
        if (stats.DlqCount > 100)
            return HealthCheckResult.Degraded($"DLQ has {stats.DlqCount} items");
        
        // Unhealthy if workers not processing
        if (stats.PendingCount > 1000 && stats.RunningCount == 0)
            return HealthCheckResult.Unhealthy("Jobs pending but no workers active");
        
        // Unhealthy if jobs stuck running
        var stuckJobs = stats.RunningJobs
            .Count(j => j.RunningFor > TimeSpan.FromHours(2));
        if (stuckJobs > 5)
            return HealthCheckResult.Unhealthy($"{stuckJobs} jobs stuck for >2h");
        
        return HealthCheckResult.Healthy();
    }
}
```

### 8.3 Alerting Rules (Prometheus)

```yaml
groups:
  - name: gabi-job-queue
    rules:
      # Critical: High failure rate
      - alert: GabiHighJobFailureRate
        expr: rate(gabi_jobs_failed_total[5m]) > 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High job failure rate detected"
          description: "More than 10% of jobs are failing"
      
      # Warning: DLQ growing
      - alert: GabiDlqGrowing
        expr: gabi_dlq_size > 50
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "DLQ has {{ $value }} messages"
      
      # Critical: No workers processing
      - alert: GabiNoActiveWorkers
        expr: gabi_workers_active == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "No active job workers"
      
      # Warning: Jobs stuck in running state
      - alert: GabiStuckJobs
        expr: |
          count by (source_id) (
            gabi_jobs_running{status="running"} 
            and on() (time() - gabi_job_last_heartbeat > 300)
          ) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Jobs stuck in running state"
```

---

## 9. Implementation Plan

### 9.1 Phase 1: Core Queue (Week 1-2)

| Task | Description | Files |
|------|-------------|-------|
| 1.1 | Create database migrations | `Migrations/001_JobQueue.sql` |
| 1.2 | Define contracts (interfaces) | `Gabi.Contracts/JobQueue/*.cs` |
| 1.3 | Implement PostgreSQL queue | `Gabi.Postgres/JobQueue/PostgreSqlJobQueue.cs` |
| 1.4 | Implement worker pool | `Gabi.Sync/Workers/WorkerPool.cs` |
| 1.5 | Implement job executors | `Gabi.Sync/Jobs/SourceSyncJobExecutor.cs` |
| 1.6 | Unit tests | `tests/Gabi.Sync.Tests/JobQueueTests.cs` |

### 9.2 Phase 2: Scheduling & DLQ (Week 3)

| Task | Description | Files |
|------|-------------|-------|
| 2.1 | Scheduler service | `Gabi.Worker/SchedulerHostedService.cs` |
| 2.2 | DLQ implementation | `Gabi.Postgres/JobQueue/DlqManager.cs` |
| 2.3 | Retry logic | `Gabi.Sync/Retry/ExponentialBackoffRetryPolicy.cs` |
| 2.4 | Heartbeat mechanism | `Gabi.Sync/Workers/HeartbeatService.cs` |

### 9.3 Phase 3: Observability (Week 4)

| Task | Description | Files |
|------|-------------|-------|
| 3.1 | Metrics integration | `Gabi.Sync/Metrics/JobQueueMetrics.cs` |
| 3.2 | Health checks | `Gabi.Worker/Health/JobQueueHealthCheck.cs` |
| 3.3 | Structured logging | Update existing log statements |
| 3.4 | Tracing spans | Add ActivitySource to job execution |

### 9.4 Phase 4: API Integration (Week 5)

| Task | Description | Files |
|------|-------------|-------|
| 4.1 | Job control endpoints | `Gabi.Api/Controllers/JobsController.cs` |
| 4.2 | DLQ management endpoints | `Gabi.Api/Controllers/DlqController.cs` |
| 4.3 | Job status endpoint | `GET /api/v1/jobs/{id}/status` |
| 4.4 | Cancel job endpoint | `POST /api/v1/jobs/{id}/cancel` |

---

## 10. Code Examples

### 10.1 Contract Definitions

```csharp
// Gabi.Contracts/JobQueue/JobRequest.cs
namespace Gabi.Contracts.JobQueue;

public record JobRequest
{
    public Guid Id { get; init; } = Guid.NewGuid();
    public string SourceId { get; init; } = string.Empty;
    public string JobType { get; init; } = "sync";
    public JobPayload Payload { get; init; } = new();
    public int Priority { get; init; } = 5;
    public DateTime? ScheduledAt { get; init; }
    public string? IdempotencyKey { get; init; }
    public int MaxRetries { get; init; } = 3;
    public string? CorrelationId { get; init; }
}

public record JobPayload
{
    public DiscoveryConfig Discovery { get; init; } = new();
    public PipelineOptions Pipeline { get; init; } = new();
    public Dictionary<string, object> CustomData { get; init; } = new();
}

public enum JobStatus
{
    Scheduled,
    Pending,
    Running,
    Completed,
    Failed,
    Cancelled
}
```

### 10.2 PostgreSQL Queue Implementation

```csharp
// Gabi.Postgres/JobQueue/PostgreSqlJobQueue.cs
using System.Data;
using System.Text.Json;
using Dapper;
using Gabi.Contracts.JobQueue;

namespace Gabi.Postgres.JobQueue;

public class PostgreSqlJobQueue : IJobQueue
{
    private readonly IDbConnection _connection;
    private readonly ILogger<PostgreSqlJobQueue> _logger;
    private readonly string _workerId;
    
    public PostgreSqlJobQueue(
        IDbConnection connection, 
        ILogger<PostgreSqlJobQueue> logger)
    {
        _connection = connection;
        _logger = logger;
        _workerId = $"{Environment.MachineName}:{Environment.ProcessId}";
    }
    
    public async Task<Guid> EnqueueAsync(
        JobRequest request, 
        CancellationToken ct = default)
    {
        const string sql = @"
            INSERT INTO job_queue (
                id, source_id, job_type, payload, priority, 
                scheduled_at, max_retries, idempotency_key, 
                correlation_id, created_by
            ) VALUES (
                @Id, @SourceId, @JobType, @Payload::jsonb, @Priority,
                COALESCE(@ScheduledAt, NOW()), @MaxRetries, @IdempotencyKey,
                COALESCE(@CorrelationId::uuid, gen_random_uuid()), 'api'
            )
            ON CONFLICT (idempotency_key) 
            WHERE idempotency_key IS NOT NULL AND status IN ('pending', 'running', 'scheduled')
            DO UPDATE SET 
                updated_at = NOW()
            RETURNING id";
        
        var id = await _connection.ExecuteScalarAsync<Guid>(
            new CommandDefinition(sql, new
            {
                request.Id,
                request.SourceId,
                request.JobType,
                Payload = JsonSerializer.Serialize(request.Payload),
                request.Priority,
                request.ScheduledAt,
                request.MaxRetries,
                request.IdempotencyKey,
                request.CorrelationId
            }, cancellationToken: ct));
        
        _logger.LogInformation(
            "Enqueued job {JobId} for source {SourceId}", 
            id, request.SourceId);
        
        return id;
    }
    
    public async Task<JobRequest?> DequeueAsync(
        IEnumerable<string> jobTypes,
        CancellationToken ct = default)
    {
        const string sql = @"
            WITH next_job AS (
                SELECT id 
                FROM job_queue 
                WHERE status IN ('pending', 'scheduled')
                  AND scheduled_at <= NOW()
                  AND job_type = ANY(@JobTypes)
                ORDER BY priority DESC, created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE job_queue 
            SET status = 'running',
                worker_id = @WorkerId,
                started_at = NOW(),
                last_heartbeat_at = NOW(),
                updated_at = NOW()
            FROM next_job
            WHERE job_queue.id = next_job.id
            RETURNING 
                id, source_id, job_type, payload, priority,
                retry_count, max_retries, timeout_seconds, correlation_id";
        
        var jobTypesArray = jobTypes.ToArray();
        
        var result = await _connection.QueryFirstOrDefaultAsync<JobRow>(
            new CommandDefinition(sql, new 
            { 
                JobTypes = jobTypesArray,
                WorkerId = _workerId 
            }, cancellationToken: ct));
        
        if (result == null) return null;
        
        return new JobRequest
        {
            Id = result.id,
            SourceId = result.source_id,
            JobType = result.job_type,
            Payload = JsonSerializer.Deserialize<JobPayload>(result.payload)!,
            Priority = result.priority,
            MaxRetries = result.max_retries
        };
    }
    
    public async Task CompleteAsync(
        Guid jobId, 
        bool success, 
        string? errorMessage = null,
        CancellationToken ct = default)
    {
        if (success)
        {
            const string sql = @"
                UPDATE job_queue 
                SET status = 'completed',
                    completed_at = NOW(),
                    updated_at = NOW()
                WHERE id = @JobId";
            
            await _connection.ExecuteAsync(
                new CommandDefinition(sql, new { JobId = jobId }, cancellationToken: ct));
        }
        else
        {
            // Will be handled by retry logic or moved to DLQ
            await HandleFailureAsync(jobId, errorMessage, ct);
        }
    }
    
    private async Task HandleFailureAsync(
        Guid jobId, 
        string? errorMessage, 
        CancellationToken ct)
    {
        const string sql = @"
            UPDATE job_queue 
            SET retry_count = retry_count + 1,
                last_retry_at = NOW(),
                status = CASE 
                    WHEN retry_count + 1 >= max_retries THEN 'failed'
                    ELSE 'pending'
                END,
                scheduled_at = CASE 
                    WHEN retry_count + 1 >= max_retries THEN scheduled_at
                    ELSE NOW() + (retry_delay * POWER(2, retry_count))
                END,
                updated_at = NOW()
            WHERE id = @JobId
            RETURNING retry_count >= max_retries as should_dlq";
        
        var shouldDlq = await _connection.ExecuteScalarAsync<bool>(
            new CommandDefinition(sql, new { JobId = jobId }, cancellationToken: ct));
        
        if (shouldDlq)
        {
            await MoveToDlqAsync(jobId, errorMessage, ct);
        }
    }
    
    private async Task MoveToDlqAsync(
        Guid jobId, 
        string? errorMessage, 
        CancellationToken ct)
    {
        const string sql = @"
            WITH job_data AS (
                SELECT * FROM job_queue WHERE id = @JobId
            )
            INSERT INTO job_dlq (
                original_job_id, error_message, error_type, 
                failed_at, worker_id, retry_count
            )
            SELECT 
                id, @ErrorMessage, 'ExecutionFailed',
                NOW(), worker_id, retry_count
            FROM job_data";
        
        await _connection.ExecuteAsync(
            new CommandDefinition(sql, new 
            { 
                JobId = jobId, 
                ErrorMessage = errorMessage ?? "Unknown error" 
            }, cancellationToken: ct));
        
        _logger.LogWarning(
            "Job {JobId} moved to DLQ after max retries", jobId);
    }
    
    public async Task<bool> SendHeartbeatAsync(
        Guid jobId, 
        CancellationToken ct = default)
    {
        const string sql = @"
            UPDATE job_queue 
            SET last_heartbeat_at = NOW()
            WHERE id = @JobId AND status = 'running'
            RETURNING true";
        
        return await _connection.ExecuteScalarAsync<bool>(
            new CommandDefinition(sql, new { JobId = jobId }, cancellationToken: ct));
    }
    
    public async Task<IReadOnlyList<JobRequest>> RecoverStalledJobsAsync(
        TimeSpan timeout, 
        CancellationToken ct = default)
    {
        const string sql = @"
            UPDATE job_queue 
            SET status = 'pending',
                worker_id = NULL,
                retry_count = retry_count + 1,
                updated_at = NOW()
            WHERE status = 'running'
              AND last_heartbeat_at < NOW() - @Timeout
            RETURNING id, source_id, job_type, payload";
        
        var rows = await _connection.QueryAsync<JobRow>(
            new CommandDefinition(sql, new { Timeout = timeout }, cancellationToken: ct));
        
        return rows.Select(r => new JobRequest
        {
            Id = r.id,
            SourceId = r.source_id,
            JobType = r.job_type,
            Payload = JsonSerializer.Deserialize<JobPayload>(r.payload)!
        }).ToList();
    }
    
    private record JobRow(
        Guid id,
        string source_id,
        string job_type,
        string payload,
        int priority,
        int retry_count,
        int max_retries,
        int timeout_seconds,
        Guid correlation_id);
}
```

### 10.3 Worker Implementation

```csharp
// Gabi.Sync/Workers/JobWorker.cs
using System.Threading.Channels;
using Gabi.Contracts.JobQueue;

namespace Gabi.Sync.Workers;

public class JobWorker : IJobWorker
{
    private readonly ChannelReader<JobRequest> _channel;
    private readonly IJobQueue _queue;
    private readonly IEnumerable<IJobExecutor> _executors;
    private readonly ILogger<JobWorker> _logger;
    private readonly CancellationTokenSource _cts = new();
    private Task? _executingTask;
    
    public string WorkerId { get; }
    public WorkerStatus CurrentStatus { get; private set; } = WorkerStatus.Idle;
    public string? CurrentJobId { get; private set; }
    
    public JobWorker(
        int workerNumber,
        ChannelReader<JobRequest> channel,
        IJobQueue queue,
        IEnumerable<IJobExecutor> executors,
        ILogger<JobWorker> logger)
    {
        WorkerId = $"{Environment.MachineName}:{Environment.ProcessId}:{workerNumber}";
        _channel = channel;
        _queue = queue;
        _executors = executors;
        _logger = logger;
    }
    
    public Task StartAsync(CancellationToken ct)
    {
        _executingTask = ExecuteAsync(ct);
        return Task.CompletedTask;
    }
    
    private async Task ExecuteAsync(CancellationToken externalCt)
    {
        using var linkedCts = CancellationTokenSource.CreateLinkedTokenSource(
            externalCt, _cts.Token);
        var ct = linkedCts.Token;
        
        _logger.LogInformation("Worker {WorkerId} started", WorkerId);
        
        try
        {
            await foreach (var job in _channel.ReadAllAsync(ct))
            {
                await ProcessJobAsync(job, ct);
            }
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested)
        {
            _logger.LogInformation("Worker {WorkerId} cancelled", WorkerId);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Worker {WorkerId} failed", WorkerId);
        }
    }
    
    private async Task ProcessJobAsync(JobRequest job, CancellationToken ct)
    {
        CurrentStatus = WorkerStatus.Busy;
        CurrentJobId = job.Id.ToString();
        
        var executor = _executors.FirstOrDefault(e => e.JobType == job.JobType);
        if (executor == null)
        {
            _logger.LogError("No executor found for job type {JobType}", job.JobType);
            await _queue.CompleteAsync(job.Id, success: false, 
                $"No executor for type: {job.JobType}", ct);
            return;
        }
        
        using var heartbeatCts = new CancellationTokenSource();
        var heartbeatTask = SendHeartbeatsAsync(job.Id, heartbeatCts.Token);
        
        var stopwatch = Stopwatch.StartNew();
        
        try
        {
            _logger.LogInformation(
                "Processing job {JobId} for source {SourceId}", 
                job.Id, job.SourceId);
            
            var progress = new Progress<JobProgress>(p =>
            {
                _logger.LogDebug(
                    "Job {JobId} progress: {Percent}% - {Message}",
                    job.Id, p.PercentComplete, p.Message);
            });
            
            var result = await executor.ExecuteAsync(job, progress, ct);
            
            stopwatch.Stop();
            JobQueueMetrics.JobDuration
                .WithLabels(job.SourceId, job.JobType)
                .Observe(stopwatch.Elapsed.TotalSeconds);
            
            await _queue.CompleteAsync(
                job.Id, 
                result.Success, 
                result.ErrorMessage, 
                ct);
            
            JobQueueMetrics.JobsCompletedTotal
                .WithLabels(job.SourceId, result.Success ? "success" : "failed")
                .Inc();
            
            _logger.LogInformation(
                "Job {JobId} completed in {Duration}s with status {Status}",
                job.Id, stopwatch.Elapsed.TotalSeconds,
                result.Success ? "success" : "failed");
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested)
        {
            _logger.LogWarning("Job {JobId} was cancelled", job.Id);
            // Job will be recovered by heartbeat timeout
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Job {JobId} failed with exception", job.Id);
            await _queue.CompleteAsync(job.Id, success: false, ex.Message, ct);
        }
        finally
        {
            heartbeatCts.Cancel();
            try { await heartbeatTask; } catch { /* ignore */ }
            
            CurrentStatus = WorkerStatus.Idle;
            CurrentJobId = null;
        }
    }
    
    private async Task SendHeartbeatsAsync(Guid jobId, CancellationToken ct)
    {
        try
        {
            while (!ct.IsCancellationRequested)
            {
                await Task.Delay(TimeSpan.FromSeconds(30), ct);
                await _queue.SendHeartbeatAsync(jobId, CancellationToken.None);
                JobQueueMetrics.WorkerHeartbeats.WithLabels(WorkerId).Inc();
            }
        }
        catch (OperationCanceledException) { }
    }
    
    public async Task StopAsync(CancellationToken ct)
    {
        CurrentStatus = WorkerStatus.Stopping;
        _cts.Cancel();
        
        if (_executingTask != null)
        {
            try
            {
                await _executingTask.WaitAsync(TimeSpan.FromMinutes(1), ct);
            }
            catch (TimeoutException)
            {
                _logger.LogWarning("Worker {WorkerId} stop timed out", WorkerId);
            }
        }
        
        CurrentStatus = WorkerStatus.Stopped;
    }
    
    public void Dispose()
    {
        _cts.Dispose();
    }
}
```

### 10.4 Source Sync Job Executor

```csharp
// Gabi.Sync/Jobs/SourceSyncJobExecutor.cs
using Gabi.Contracts.Discovery;
using Gabi.Contracts.JobQueue;
using Gabi.Contracts.Pipeline;

namespace Gabi.Sync.Jobs;

public class SourceSyncJobExecutor : IJobExecutor
{
    public string JobType => "sync";
    
    private readonly IDiscoveryEngine _discoveryEngine;
    private readonly IPipelineOrchestrator _pipelineOrchestrator;
    private readonly ILogger<SourceSyncJobExecutor> _logger;
    
    public SourceSyncJobExecutor(
        IDiscoveryEngine discoveryEngine,
        IPipelineOrchestrator pipelineOrchestrator,
        ILogger<SourceSyncJobExecutor> logger)
    {
        _discoveryEngine = discoveryEngine;
        _pipelineOrchestrator = pipelineOrchestrator;
        _logger = logger;
    }
    
    public async Task<JobResult> ExecuteAsync(
        JobRequest job,
        IProgress<JobProgress> progress,
        CancellationToken ct)
    {
        try
        {
            var sourceId = job.SourceId;
            var discoveryConfig = job.Payload.Discovery;
            var pipelineOptions = job.Payload.Pipeline;
            
            progress.Report(new JobProgress
            {
                PercentComplete = 0,
                Message = "Starting discovery..."
            });
            
            // Discovery phase
            var discoveredSources = _discoveryEngine
                .DiscoverAsync(sourceId, discoveryConfig, ct);
            
            var urlCount = 0;
            await foreach (var _ in discoveredSources)
                urlCount++;
            
            _logger.LogInformation(
                "Discovered {Count} URLs for source {SourceId}",
                urlCount, sourceId);
            
            progress.Report(new JobProgress
            {
                PercentComplete = 10,
                Message = $"Discovered {urlCount} URLs"
            });
            
            // Pipeline phase
            var documents = FetchAndParseAsync(discoveredSources, ct);
            
            var result = await _pipelineOrchestrator.ExecuteAsync(
                sourceId, documents, pipelineOptions, ct);
            
            progress.Report(new JobProgress
            {
                PercentComplete = 100,
                Message = "Completed"
            });
            
            return new JobResult
            {
                Success = result.Success,
                ErrorMessage = result.ErrorMessage,
                Metadata = new Dictionary<string, object>
                {
                    ["urls_discovered"] = urlCount,
                    ["documents_processed"] = result.Metrics.DocumentsProcessed,
                    ["duration_seconds"] = result.Metrics.TotalDuration.TotalSeconds
                }
            };
        }
        catch (Exception ex)
        {
            return new JobResult
            {
                Success = false,
                ErrorMessage = ex.Message,
                ErrorType = ex.GetType().Name
            };
        }
    }
    
    private async IAsyncEnumerable<Document> FetchAndParseAsync(
        IAsyncEnumerable<DiscoveredSource> sources,
        [EnumeratorCancellation] CancellationToken ct)
    {
        // Placeholder - will be implemented in Gabi.Ingest
        await foreach (var source in sources.WithCancellation(ct))
        {
            yield return new Document
            {
                SourceId = source.SourceId,
                Metadata = new Dictionary<string, object>
                {
                    ["url"] = source.Url
                }
            };
        }
    }
}
```

### 10.5 Worker Pool Hosted Service

```csharp
// Gabi.Worker/WorkerPoolHostedService.cs
using Gabi.Contracts.JobQueue;
using Gabi.Sync.Workers;
using System.Threading.Channels;

namespace Gabi.Worker;

public class WorkerPoolHostedService : IHostedService
{
    private readonly IServiceProvider _serviceProvider;
    private readonly ILogger<WorkerPoolHostedService> _logger;
    private readonly WorkerPoolOptions _options;
    private readonly List<IJobWorker> _workers = new();
    private Channel<JobRequest>? _channel;
    private Task? _dequeueTask;
    private CancellationTokenSource? _cts;
    
    public WorkerPoolHostedService(
        IServiceProvider serviceProvider,
        ILogger<WorkerPoolHostedService> logger,
        IOptions<WorkerPoolOptions> options)
    {
        _serviceProvider = serviceProvider;
        _logger = logger;
        _options = options.Value;
    }
    
    public Task StartAsync(CancellationToken ct)
    {
        _logger.LogInformation(
            "Starting worker pool with {Count} workers",
            _options.WorkerCount);
        
        _cts = new CancellationTokenSource();
        _channel = Channel.CreateBounded<JobRequest>(
            new BoundedChannelOptions(_options.ChannelCapacity)
            {
                FullMode = BoundedChannelFullMode.Wait
            });
        
        // Create workers
        for (int i = 0; i < _options.WorkerCount; i++)
        {
            var worker = CreateWorker(i);
            _workers.Add(worker);
            _ = worker.StartAsync(_cts.Token);
        }
        
        JobQueueMetrics.WorkersActive.Set(_workers.Count);
        
        // Start dequeue loop
        _dequeueTask = DequeueLoopAsync(_cts.Token);
        
        // Start recovery loop
        _ = RecoveryLoopAsync(_cts.Token);
        
        return Task.CompletedTask;
    }
    
    private IJobWorker CreateWorker(int number)
    {
        var scope = _serviceProvider.CreateScope();
        var queue = scope.ServiceProvider.GetRequiredService<IJobQueue>();
        var executors = scope.ServiceProvider.GetRequiredService<IEnumerable<IJobExecutor>>();
        var logger = scope.ServiceProvider.GetRequiredService<ILogger<JobWorker>>();
        
        return new JobWorker(
            number, _channel!.Reader, queue, executors, logger);
    }
    
    private async Task DequeueLoopAsync(CancellationToken ct)
    {
        await using var scope = _serviceProvider.CreateAsyncScope();
        var queue = scope.ServiceProvider.GetRequiredService<IJobQueue>();
        var executors = scope.ServiceProvider.GetRequiredService<IEnumerable<IJobExecutor>>();
        var jobTypes = executors.Select(e => e.JobType).ToList();
        
        while (!ct.IsCancellationRequested)
        {
            try
            {
                // Wait for channel capacity
                if (_channel!.Writer.TryGetSpan(out var span) && span.IsEmpty)
                {
                    // Channel has space, try to dequeue
                    var job = await queue.DequeueAsync(jobTypes, ct);
                    
                    if (job != null)
                    {
                        await _channel.Writer.WriteAsync(job, ct);
                        JobQueueMetrics.JobsPending.Dec();
                        JobQueueMetrics.JobsRunning.WithLabels(job.SourceId).Inc();
                    }
                    else
                    {
                        // No jobs available, wait before polling again
                        await Task.Delay(_options.PollInterval, ct);
                    }
                }
                else
                {
                    // Channel full, wait a bit
                    await Task.Delay(TimeSpan.FromMilliseconds(100), ct);
                }
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error in dequeue loop");
                await Task.Delay(_options.PollInterval, ct);
            }
        }
    }
    
    private async Task RecoveryLoopAsync(CancellationToken ct)
    {
        await using var scope = _serviceProvider.CreateAsyncScope();
        var queue = scope.ServiceProvider.GetRequiredService<IJobQueue>();
        
        while (!ct.IsCancellationRequested)
        {
            try
            {
                await Task.Delay(TimeSpan.FromMinutes(1), ct);
                
                // Recover jobs that haven't sent heartbeat
                var stalled = await queue.RecoverStalledJobsAsync(
                    TimeSpan.FromMinutes(5), ct);
                
                if (stalled.Count > 0)
                {
                    _logger.LogWarning(
                        "Recovered {Count} stalled jobs",
                        stalled.Count);
                }
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error in recovery loop");
            }
        }
    }
    
    public async Task StopAsync(CancellationToken ct)
    {
        _logger.LogInformation("Stopping worker pool...");
        
        _cts?.Cancel();
        _channel?.Writer.Complete();
        
        // Stop all workers
        var stopTasks = _workers.Select(w => w.StopAsync(ct));
        await Task.WhenAll(stopTasks);
        
        if (_dequeueTask != null)
        {
            try
            {
                await _dequeueTask.WaitAsync(_options.ShutdownTimeout, ct);
            }
            catch (TimeoutException)
            {
                _logger.LogWarning("Dequeue task stop timed out");
            }
        }
        
        foreach (var worker in _workers)
        {
            worker.Dispose();
        }
        
        JobQueueMetrics.WorkersActive.Set(0);
        _logger.LogInformation("Worker pool stopped");
    }
}
```

### 10.6 DI Registration

```csharp
// Program.cs extensions
public static class JobQueueServiceExtensions
{
    public static IServiceCollection AddJobQueue(
        this IServiceCollection services,
        IConfiguration configuration)
    {
        // Configuration
        services.Configure<WorkerPoolOptions>(
            configuration.GetSection("WorkerPool"));
        
        // Queue implementation
        services.AddScoped<IJobQueue, PostgreSqlJobQueue>();
        
        // DLQ
        services.AddScoped<IDlqManager, DlqManager>();
        
        // Executors
        services.AddScoped<IJobExecutor, SourceSyncJobExecutor>();
        // Add more executors here
        
        // Hosted services
        services.AddHostedService<WorkerPoolHostedService>();
        services.AddHostedService<SchedulerHostedService>();
        
        // Health checks
        services.AddHealthChecks()
            .AddCheck<JobQueueHealthCheck>("job-queue");
        
        return services;
    }
}

// In Program.cs:
// builder.Services.AddJobQueue(builder.Configuration);
```

### 10.7 appsettings.json Configuration

```json
{
  "WorkerPool": {
    "WorkerCount": 2,
    "ChannelCapacity": 100,
    "PollInterval": "00:00:05",
    "HeartbeatInterval": "00:00:30",
    "ShutdownTimeout": "00:01:00"
  },
  "JobQueue": {
    "DefaultMaxRetries": 3,
    "DefaultRetryDelay": "00:00:30",
    "MaxRetryDelay": "01:00:00",
    "StallTimeout": "00:05:00"
  }
}
```

---

## 11. Migration Path

### From Current State (BackgroundService)

```
Current: Gabi.Worker/Worker.cs (simple loop)
                ↓
Step 1: Add job_queue table
                ↓
Step 2: Implement IJobQueue (PostgreSQL)
                ↓
Step 3: Replace Worker with WorkerPoolHostedService
                ↓
Step 4: Add scheduler for cron-based jobs
                ↓
Step 5: Add DLQ management
                ↓
Step 6: Add API endpoints for job control
```

---

## 12. Appendix

### A. Comparison with Existing Solutions

| Feature | This Design | Hangfire | RabbitMQ | AWS SQS |
|---------|-------------|----------|----------|---------|
| Self-hosted | ✅ | ✅ | ✅ | ❌ |
| PostgreSQL only | ✅ | ❌* | ❌ | ❌ |
| Priorities | ✅ | ⚠️ | ✅ | ✅ |
| Scheduling | ✅ | ✅ | ❌ | ❌ |
| DLQ | ✅ | ✅ | Manual | ⚠️ |
| Dashboard | API | Built-in | 3rd party | AWS |
| Complexity | Medium | Medium | High | Low |

*Hangfire supports PostgreSQL but recommends Redis for production.

### B. References

1. [SKIP LOCKED in PostgreSQL](https://www.2ndquadrant.com/en/blog/what-is-select-skip-locked-for-in-postgresql-9-5/)
2. [Job Queue Patterns](https://docs.hangfire.io/en/latest/background-methods/calling-methods-in-background.html)
3. [Channel API in .NET](https://devblogs.microsoft.com/dotnet/an-introduction-to-system-threading-channels/)
4. [Exponential Backoff](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/)

---

*Document Version: 1.0*  
*Next Review: After Phase 1 Implementation*
