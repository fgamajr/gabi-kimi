# GABI-SYNC: Persistence Architecture Design

**Status:** Draft  
**Date:** 2026-02-12  
**Author:** Persistence Architecture Team  
**Scope:** Discovery/Ingest Pipeline Persistence Layer

---

## Executive Summary

This document designs a production-ready persistence layer for the GABI discovery and ingest pipeline. The current in-memory `Dictionary` approach in `SourceCatalogService` loses all state on restart, preventing reliable pipeline operation.

### Goals

| Goal | Description | Priority |
|------|-------------|----------|
| **Resilience** | Zero data loss, crash recovery, idempotent operations | P0 |
| **Performance** | Sub-100ms queries, efficient batching, proper indexing | P0 |
| **Auditability** | Full trail of who/what/when for compliance | P0 |
| **Scalability** | Support multiple workers, distributed processing | P1 |
| **Maintainability** | Clean patterns, testable, well-documented | P1 |

---

## 1. Database Schema Design

### 1.1 Entity Relationship Diagram

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  source_registry│────▶│ discovered_links│◀────│ source_refresh  │
│   (catalog)     │     │  (URLs found)   │     │   (runs)        │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                       │
         │              ┌────────┴────────┐
         │              ▼                 ▼
         │       ┌─────────────┐   ┌─────────────┐
         │       │ingest_jobs  │   │link_history │
         │       │(work queue) │   │(audit)      │
         │       └──────┬──────┘   └─────────────┘
         │              │
         ▼              ▼
┌─────────────────┐     ┌─────────────────┐
│ pipeline_state  │◀────│ pipeline_metrics│
│  (checkpoints)  │     │  (telemetry)    │
└─────────────────┘     └─────────────────┘
```

### 1.2 Table Specifications

#### 1.2.1 `source_registry`

Static configuration cache loaded from `sources_v2.yaml`.

```sql
CREATE TABLE source_registry (
    id VARCHAR(100) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    provider VARCHAR(100) NOT NULL,
    domain VARCHAR(100),
    jurisdiction VARCHAR(10),
    category VARCHAR(50),
    canonical_type VARCHAR(50),
    
    -- Discovery config (JSON for flexibility)
    discovery_strategy VARCHAR(50) NOT NULL,
    discovery_config JSONB NOT NULL,
    
    -- Fetch config
    fetch_protocol VARCHAR(20) DEFAULT 'https',
    fetch_config JSONB,
    
    -- Pipeline config
    pipeline_config JSONB,
    
    -- State
    enabled BOOLEAN DEFAULT true,
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(100) DEFAULT 'system',
    updated_by VARCHAR(100) DEFAULT 'system',
    
    -- Concurrency control
    version INTEGER DEFAULT 1
);

-- Indexes
CREATE INDEX idx_source_registry_enabled ON source_registry(enabled) WHERE enabled = true;
CREATE INDEX idx_source_registry_provider ON source_registry(provider);
CREATE INDEX idx_source_registry_category ON source_registry(category);
```

#### 1.2.2 `discovered_links`

URLs discovered during source refresh. Unique per source+URL.

```sql
CREATE TABLE discovered_links (
    id BIGSERIAL PRIMARY KEY,
    source_id VARCHAR(100) NOT NULL REFERENCES source_registry(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    url_hash VARCHAR(64) NOT NULL, -- SHA256 for quick comparison
    
    -- Discovery metadata
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    first_seen_at TIMESTAMPTZ DEFAULT NOW(), -- Immutable
    etag VARCHAR(255),
    last_modified TIMESTAMPTZ,
    content_length BIGINT,
    
    -- Processing state
    status VARCHAR(20) DEFAULT 'pending', -- pending, queued, processing, completed, failed, skipped
    last_processed_at TIMESTAMPTZ,
    process_attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    
    -- Content fingerprint (for change detection)
    content_hash VARCHAR(64),
    last_content_hash VARCHAR(64), -- Previous known hash
    
    -- Metadata
    metadata JSONB DEFAULT '{}',
    
    -- Concurrency control
    version INTEGER DEFAULT 1,
    
    -- Unique constraint: one URL per source
    CONSTRAINT uq_discovered_links_source_url UNIQUE (source_id, url_hash)
);

-- Indexes for performance
CREATE INDEX idx_discovered_links_source_status 
    ON discovered_links(source_id, status) 
    WHERE status IN ('pending', 'failed');
    
CREATE INDEX idx_discovered_links_status_attempts 
    ON discovered_links(status, process_attempts) 
    WHERE status = 'failed' AND process_attempts < max_attempts;
    
CREATE INDEX idx_discovered_links_discovered_at 
    ON discovered_links(discovered_at DESC);
    
CREATE INDEX idx_discovered_links_content_hash 
    ON discovered_links(content_hash) 
    WHERE content_hash IS NOT NULL;
    
-- GIN index for metadata queries
CREATE INDEX idx_discovered_links_metadata ON discovered_links USING GIN(metadata);
```

#### 1.2.3 `source_refresh`

Audit log of all refresh operations.

```sql
CREATE TABLE source_refresh (
    id BIGSERIAL PRIMARY KEY,
    source_id VARCHAR(100) NOT NULL REFERENCES source_registry(id) ON DELETE CASCADE,
    
    -- Execution info
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'running', -- running, completed, failed, cancelled
    
    -- Results
    links_discovered INTEGER DEFAULT 0,
    links_new INTEGER DEFAULT 0,
    links_updated INTEGER DEFAULT 0,
    links_removed INTEGER DEFAULT 0,
    
    -- Error tracking
    error_message TEXT,
    error_details JSONB,
    
    -- Performance metrics
    duration_ms INTEGER,
    peak_memory_mb INTEGER,
    
    -- Metadata
    triggered_by VARCHAR(100) DEFAULT 'system', -- user, scheduler, api
    request_id VARCHAR(100), -- For distributed tracing
    
    -- Concurrency control
    worker_id VARCHAR(100), -- Which worker executed
    heartbeat_at TIMESTAMPTZ -- For detecting stale workers
);

-- Indexes
CREATE INDEX idx_source_refresh_source_started 
    ON source_refresh(source_id, started_at DESC);
    
CREATE INDEX idx_source_refresh_status_heartbeat 
    ON source_refresh(status, heartbeat_at) 
    WHERE status = 'running';
    
CREATE INDEX idx_source_refresh_request_id 
    ON source_refresh(request_id) 
    WHERE request_id IS NOT NULL;
```

#### 1.2.4 `ingest_jobs`

Job queue for distributed processing.

```sql
CREATE TYPE job_priority AS ENUM ('critical', 'high', 'normal', 'low');
CREATE TYPE job_status AS ENUM (
    'pending',      -- Waiting to be picked up
    'queued',       -- In queue, ready for processing
    'processing',   -- Currently being processed
    'completed',    -- Successfully finished
    'failed',       -- Failed, may retry
    'dead',         -- Failed permanently (sent to DLQ)
    'cancelled'     -- Manually cancelled
);

CREATE TABLE ingest_jobs (
    id BIGSERIAL PRIMARY KEY,
    job_type VARCHAR(50) NOT NULL, -- 'fetch', 'parse', 'chunk', 'embed', 'index'
    
    -- Job payload
    payload JSONB NOT NULL,
    payload_hash VARCHAR(64) NOT NULL, -- For deduplication
    
    -- Linking (optional, for link-based jobs)
    link_id BIGINT REFERENCES discovered_links(id) ON DELETE SET NULL,
    source_id VARCHAR(100) REFERENCES source_registry(id) ON DELETE SET NULL,
    
    -- Queue management
    status job_status DEFAULT 'pending',
    priority job_priority DEFAULT 'normal',
    
    -- Scheduling
    created_at TIMESTAMPTZ DEFAULT NOW(),
    scheduled_at TIMESTAMPTZ DEFAULT NOW(), -- For delayed execution
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    
    -- Retry logic
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    last_error TEXT,
    error_details JSONB,
    retry_at TIMESTAMPTZ, -- Next retry time (exponential backoff)
    
    -- Worker assignment
    worker_id VARCHAR(100), -- Worker that claimed this job
    locked_at TIMESTAMPTZ,  -- When worker claimed it
    lock_expires_at TIMESTAMPTZ, -- Lease timeout (safety)
    
    -- Progress tracking
    progress_percent INTEGER CHECK (progress_percent BETWEEN 0 AND 100),
    progress_message TEXT,
    
    -- Result
    result JSONB,
    
    -- Concurrency control
    version INTEGER DEFAULT 1,
    
    -- Unique constraint for deduplication
    CONSTRAINT uq_ingest_jobs_payload_hash UNIQUE (payload_hash)
);

-- Critical indexes for queue performance
CREATE INDEX idx_ingest_jobs_available 
    ON ingest_jobs(status, priority, scheduled_at, created_at) 
    WHERE status IN ('pending', 'queued') AND scheduled_at <= NOW();
    
CREATE INDEX idx_ingest_jobs_processing 
    ON ingest_jobs(status, worker_id, locked_at) 
    WHERE status = 'processing';
    
CREATE INDEX idx_ingest_jobs_retry 
    ON ingest_jobs(status, retry_at) 
    WHERE status = 'failed';
    
CREATE INDEX idx_ingest_jobs_link 
    ON ingest_jobs(link_id) 
    WHERE link_id IS NOT NULL;
    
CREATE INDEX idx_ingest_jobs_source 
    ON ingest_jobs(source_id, created_at DESC) 
    WHERE source_id IS NOT NULL;
    
CREATE INDEX idx_ingest_jobs_deadletter 
    ON ingest_jobs(status, attempts, created_at) 
    WHERE status = 'dead';
```

#### 1.2.5 `pipeline_state`

Checkpoints for long-running pipelines.

```sql
CREATE TABLE pipeline_state (
    id BIGSERIAL PRIMARY KEY,
    state_key VARCHAR(255) NOT NULL UNIQUE, -- e.g., "tcu_acordaos:2024:checkpoint"
    
    -- State data
    state_type VARCHAR(50) NOT NULL, -- 'discovery', 'ingest', 'sync'
    source_id VARCHAR(100) REFERENCES source_registry(id) ON DELETE CASCADE,
    
    -- Checkpoint data
    checkpoint_data JSONB NOT NULL,
    
    -- Position tracking (for resume)
    current_position INTEGER DEFAULT 0,
    total_items INTEGER,
    
    -- State
    status VARCHAR(20) DEFAULT 'active', -- active, paused, completed, failed
    
    -- Timing
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    
    -- Concurrency control
    version INTEGER DEFAULT 1,
    worker_id VARCHAR(100)
);

-- Indexes
CREATE INDEX idx_pipeline_state_source 
    ON pipeline_state(source_id, state_type);
    
CREATE INDEX idx_pipeline_state_status 
    ON pipeline_state(status, updated_at) 
    WHERE status = 'active';
```

#### 1.2.6 `audit_log`

Generic audit trail for compliance.

```sql
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    
    -- Event details
    event_type VARCHAR(50) NOT NULL, -- 'source.created', 'link.discovered', 'job.completed', etc.
    entity_type VARCHAR(50) NOT NULL, -- 'source', 'link', 'job', 'document'
    entity_id VARCHAR(100) NOT NULL,
    
    -- Actor
    actor_type VARCHAR(20) NOT NULL, -- 'user', 'system', 'worker', 'api'
    actor_id VARCHAR(100),
    
    -- Change details
    action VARCHAR(20) NOT NULL, -- 'create', 'update', 'delete', 'execute'
    old_values JSONB,
    new_values JSONB,
    change_summary TEXT,
    
    -- Context
    occurred_at TIMESTAMPTZ DEFAULT NOW(),
    request_id VARCHAR(100),
    source_ip INET,
    user_agent TEXT,
    
    -- Metadata
    metadata JSONB DEFAULT '{}'
);

-- Indexes for audit queries
CREATE INDEX idx_audit_log_entity 
    ON audit_log(entity_type, entity_id, occurred_at DESC);
    
CREATE INDEX idx_audit_log_actor 
    ON audit_log(actor_type, actor_id, occurred_at DESC);
    
CREATE INDEX idx_audit_log_event 
    ON audit_log(event_type, occurred_at DESC);
    
CREATE INDEX idx_audit_log_occurred 
    ON audit_log(occurred_at DESC);
    
CREATE INDEX idx_audit_log_request 
    ON audit_log(request_id) 
    WHERE request_id IS NOT NULL;

-- Partition by month for large scale
-- CREATE TABLE audit_log_2024_01 PARTITION OF audit_log 
--     FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
```

#### 1.2.7 `link_history`

History of all changes to discovered_links (for debugging/auditing).

```sql
CREATE TABLE link_history (
    id BIGSERIAL PRIMARY KEY,
    link_id BIGINT NOT NULL REFERENCES discovered_links(id) ON DELETE CASCADE,
    
    -- Snapshot
    url TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    etag VARCHAR(255),
    content_hash VARCHAR(64),
    metadata JSONB,
    
    -- Change context
    changed_at TIMESTAMPTZ DEFAULT NOW(),
    changed_by VARCHAR(100) DEFAULT 'system',
    change_reason VARCHAR(100), -- 'discovery', 'fetch', 'manual', etc.
    
    -- Diff
    previous_status VARCHAR(20),
    previous_hash VARCHAR(64)
);

-- Indexes
CREATE INDEX idx_link_history_link 
    ON link_history(link_id, changed_at DESC);
    
CREATE INDEX idx_link_history_changed 
    ON link_history(changed_at DESC);
```

---

## 2. EF Core Entities

### 2.1 Entity Classes

```csharp
// ============================================================================
// Core Base Classes
// ============================================================================

/// <summary>
/// Base entity with audit and concurrency support.
/// </summary>
public abstract class AuditableEntity
{
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;
    public string CreatedBy { get; set; } = "system";
    public string UpdatedBy { get; set; } = "system";
    
    /// <summary>
    /// Optimistic concurrency token.
    /// </summary>
    [Timestamp]
    public uint Version { get; set; }
}

/// <summary>
/// Base entity with soft delete support.
/// </summary>
public abstract class SoftDeletableEntity : AuditableEntity
{
    public bool IsDeleted { get; set; }
    public DateTime? DeletedAt { get; set; }
    public string? DeletedBy { get; set; }
}

// ============================================================================
// Domain Entities
// ============================================================================

/// <summary>
/// Static source configuration from sources_v2.yaml.
/// </summary>
[Table("source_registry")]
[Index(nameof(Enabled))]
[Index(nameof(Provider))]
[Index(nameof(Category))]
public class SourceRegistry : AuditableEntity
{
    [Key]
    [MaxLength(100)]
    public string Id { get; set; } = string.Empty;
    
    [Required]
    [MaxLength(255)]
    public string Name { get; set; } = string.Empty;
    
    public string? Description { get; set; }
    
    [Required]
    [MaxLength(100)]
    public string Provider { get; set; } = string.Empty;
    
    [MaxLength(100)]
    public string? Domain { get; set; }
    
    [MaxLength(10)]
    public string? Jurisdiction { get; set; }
    
    [MaxLength(50)]
    public string? Category { get; set; }
    
    [MaxLength(50)]
    public string? CanonicalType { get; set; }
    
    [Required]
    [MaxLength(50)]
    public string DiscoveryStrategy { get; set; } = string.Empty;
    
    /// <summary>
    /// Discovery configuration as JSON.
    /// </summary>
    [Required]
    [Column(TypeName = "jsonb")]
    public string DiscoveryConfig { get; set; } = "{}";
    
    [MaxLength(20)]
    public string FetchProtocol { get; set; } = "https";
    
    [Column(TypeName = "jsonb")]
    public string? FetchConfig { get; set; }
    
    [Column(TypeName = "jsonb")]
    public string? PipelineConfig { get; set; }
    
    public bool Enabled { get; set; } = true;
    
    // Navigation
    public ICollection<DiscoveredLink> DiscoveredLinks { get; set; } = new List<DiscoveredLink>();
    public ICollection<SourceRefresh> Refreshes { get; set; } = new List<SourceRefresh>();
}

/// <summary>
/// Status of a discovered link in the processing pipeline.
/// </summary>
public enum LinkStatus
{
    Pending,      // Waiting to be processed
    Queued,       // In job queue
    Processing,   // Currently being processed
    Completed,    // Successfully processed
    Failed,       // Failed, may retry
    Skipped,      // Skipped (duplicate, filtered, etc.)
    Stale         // No longer present in source
}

/// <summary>
/// A URL discovered during source refresh.
/// </summary>
[Table("discovered_links")]
[Index(nameof(SourceId), nameof(Status))]
[Index(nameof(ContentHash))]
[Index(nameof(DiscoveredAt))]
public class DiscoveredLink : AuditableEntity
{
    [Key]
    public long Id { get; set; }
    
    [Required]
    [MaxLength(100)]
    public string SourceId { get; set; } = string.Empty;
    
    [ForeignKey(nameof(SourceId))]
    public SourceRegistry Source { get; set; } = null!;
    
    [Required]
    public string Url { get; set; } = string.Empty;
    
    /// <summary>
    /// SHA256 hash of URL for unique constraint.
    /// </summary>
    [Required]
    [MaxLength(64)]
    public string UrlHash { get; set; } = string.Empty;
    
    /// <summary>
    /// When this link was first discovered (immutable).
    /// </summary>
    public DateTime FirstSeenAt { get; set; } = DateTime.UtcNow;
    
    [MaxLength(255)]
    public string? Etag { get; set; }
    
    public DateTime? LastModified { get; set; }
    
    public long? ContentLength { get; set; }
    
    [MaxLength(20)]
    public string Status { get; set; } = LinkStatus.Pending.ToString().ToLowerInvariant();
    
    public DateTime? LastProcessedAt { get; set; }
    
    public int ProcessAttempts { get; set; }
    
    public int MaxAttempts { get; set; } = 3;
    
    [MaxLength(64)]
    public string? ContentHash { get; set; }
    
    [MaxLength(64)]
    public string? LastContentHash { get; set; }
    
    [Column(TypeName = "jsonb")]
    public string Metadata { get; set; } = "{}";
    
    // Navigation
    public ICollection<IngestJob> Jobs { get; set; } = new List<IngestJob>();
    public ICollection<LinkHistory> History { get; set; } = new List<LinkHistory>();
}

/// <summary>
/// Status of a source refresh operation.
/// </summary>
public enum RefreshStatus
{
    Running,
    Completed,
    Failed,
    Cancelled
}

/// <summary>
/// Audit record of a source refresh operation.
/// </summary>
[Table("source_refresh")]
[Index(nameof(SourceId), nameof(StartedAt))]
[Index(nameof(Status), nameof(HeartbeatAt))]
public class SourceRefresh : AuditableEntity
{
    [Key]
    public long Id { get; set; }
    
    [Required]
    [MaxLength(100)]
    public string SourceId { get; set; } = string.Empty;
    
    [ForeignKey(nameof(SourceId))]
    public SourceRegistry Source { get; set; } = null!;
    
    public DateTime StartedAt { get; set; } = DateTime.UtcNow;
    
    public DateTime? CompletedAt { get; set; }
    
    [MaxLength(20)]
    public string Status { get; set; } = RefreshStatus.Running.ToString().ToLowerInvariant();
    
    public int LinksDiscovered { get; set; }
    public int LinksNew { get; set; }
    public int LinksUpdated { get; set; }
    public int LinksRemoved { get; set; }
    
    public string? ErrorMessage { get; set; }
    
    [Column(TypeName = "jsonb")]
    public string? ErrorDetails { get; set; }
    
    public int? DurationMs { get; set; }
    public int? PeakMemoryMb { get; set; }
    
    [MaxLength(100)]
    public string TriggeredBy { get; set; } = "system";
    
    [MaxLength(100)]
    public string? RequestId { get; set; }
    
    [MaxLength(100)]
    public string? WorkerId { get; set; }
    
    public DateTime? HeartbeatAt { get; set; }
}

/// <summary>
/// Job priority levels.
/// </summary>
public enum JobPriority
{
    Critical = 0,
    High = 1,
    Normal = 2,
    Low = 3
}

/// <summary>
/// Job status in the processing queue.
/// </summary>
public enum JobStatus
{
    Pending,
    Queued,
    Processing,
    Completed,
    Failed,
    Dead,
    Cancelled
}

/// <summary>
/// A job in the ingest queue.
/// </summary>
[Table("ingest_jobs")]
[Index(nameof(Status), nameof(Priority), nameof(ScheduledAt), nameof(CreatedAt), Name = "idx_jobs_available")]
[Index(nameof(Status), nameof(WorkerId), nameof(LockedAt))]
[Index(nameof(LinkId))]
[Index(nameof(PayloadHash), IsUnique = true)]
public class IngestJob : AuditableEntity
{
    [Key]
    public long Id { get; set; }
    
    [Required]
    [MaxLength(50)]
    public string JobType { get; set; } = string.Empty;
    
    [Required]
    [Column(TypeName = "jsonb")]
    public string Payload { get; set; } = "{}";
    
    [Required]
    [MaxLength(64)]
    public string PayloadHash { get; set; } = string.Empty;
    
    public long? LinkId { get; set; }
    
    [ForeignKey(nameof(LinkId))]
    public DiscoveredLink? Link { get; set; }
    
    [MaxLength(100)]
    public string? SourceId { get; set; }
    
    [ForeignKey(nameof(SourceId))]
    public SourceRegistry? Source { get; set; }
    
    [MaxLength(20)]
    public string Status { get; set; } = JobStatus.Pending.ToString().ToLowerInvariant();
    
    public int Priority { get; set; } = (int)JobPriority.Normal;
    
    public DateTime ScheduledAt { get; set; } = DateTime.UtcNow;
    
    public DateTime? StartedAt { get; set; }
    
    public DateTime? CompletedAt { get; set; }
    
    public int Attempts { get; set; }
    
    public int MaxAttempts { get; set; } = 3;
    
    public string? LastError { get; set; }
    
    [Column(TypeName = "jsonb")]
    public string? ErrorDetails { get; set; }
    
    public DateTime? RetryAt { get; set; }
    
    [MaxLength(100)]
    public string? WorkerId { get; set; }
    
    public DateTime? LockedAt { get; set; }
    
    public DateTime? LockExpiresAt { get; set; }
    
    public int? ProgressPercent { get; set; }
    
    public string? ProgressMessage { get; set; }
    
    [Column(TypeName = "jsonb")]
    public string? Result { get; set; }
}

/// <summary>
/// Checkpoint state for resumable pipelines.
/// </summary>
[Table("pipeline_state")]
[Index(nameof(SourceId), nameof(StateType))]
[Index(nameof(Status), nameof(UpdatedAt))]
public class PipelineState : AuditableEntity
{
    [Key]
    public long Id { get; set; }
    
    [Required]
    [MaxLength(255)]
    public string StateKey { get; set; } = string.Empty;
    
    [Required]
    [MaxLength(50)]
    public string StateType { get; set; } = string.Empty;
    
    [MaxLength(100)]
    public string? SourceId { get; set; }
    
    [ForeignKey(nameof(SourceId))]
    public SourceRegistry? Source { get; set; }
    
    [Required]
    [Column(TypeName = "jsonb")]
    public string CheckpointData { get; set; } = "{}";
    
    public int CurrentPosition { get; set; }
    
    public int? TotalItems { get; set; }
    
    [MaxLength(20)]
    public string Status { get; set; } = "active";
    
    public DateTime? CompletedAt { get; set; }
    
    [MaxLength(100)]
    public string? WorkerId { get; set; }
}

/// <summary>
/// Generic audit log entry.
/// </summary>
[Table("audit_log")]
[Index(nameof(EntityType), nameof(EntityId), nameof(OccurredAt))]
[Index(nameof(ActorType), nameof(ActorId), nameof(OccurredAt))]
[Index(nameof(EventType), nameof(OccurredAt))]
public class AuditLog
{
    [Key]
    public long Id { get; set; }
    
    [Required]
    [MaxLength(50)]
    public string EventType { get; set; } = string.Empty;
    
    [Required]
    [MaxLength(50)]
    public string EntityType { get; set; } = string.Empty;
    
    [Required]
    [MaxLength(100)]
    public string EntityId { get; set; } = string.Empty;
    
    [Required]
    [MaxLength(20)]
    public string ActorType { get; set; } = string.Empty;
    
    [MaxLength(100)]
    public string? ActorId { get; set; }
    
    [Required]
    [MaxLength(20)]
    public string Action { get; set; } = string.Empty;
    
    [Column(TypeName = "jsonb")]
    public string? OldValues { get; set; }
    
    [Column(TypeName = "jsonb")]
    public string? NewValues { get; set; }
    
    public string? ChangeSummary { get; set; }
    
    public DateTime OccurredAt { get; set; } = DateTime.UtcNow;
    
    [MaxLength(100)]
    public string? RequestId { get; set; }
    
    public IPAddress? SourceIp { get; set; }
    
    public string? UserAgent { get; set; }
    
    [Column(TypeName = "jsonb")]
    public string Metadata { get; set; } = "{}";
}

/// <summary>
/// History of changes to a discovered link.
/// </summary>
[Table("link_history")]
[Index(nameof(LinkId), nameof(ChangedAt))]
public class LinkHistory
{
    [Key]
    public long Id { get; set; }
    
    public long LinkId { get; set; }
    
    [ForeignKey(nameof(LinkId))]
    public DiscoveredLink Link { get; set; } = null!;
    
    [Required]
    public string Url { get; set; } = string.Empty;
    
    [Required]
    [MaxLength(20)]
    public string Status { get; set; } = string.Empty;
    
    [MaxLength(255)]
    public string? Etag { get; set; }
    
    [MaxLength(64)]
    public string? ContentHash { get; set; }
    
    [Column(TypeName = "jsonb")]
    public string? Metadata { get; set; }
    
    public DateTime ChangedAt { get; set; } = DateTime.UtcNow;
    
    [MaxLength(100)]
    public string ChangedBy { get; set; } = "system";
    
    [MaxLength(100)]
    public string? ChangeReason { get; set; }
    
    [MaxLength(20)]
    public string? PreviousStatus { get; set; }
    
    [MaxLength(64)]
    public string? PreviousHash { get; set; }
}
```

### 2.2 Updated DbContext

```csharp
using Gabi.Postgres.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage.ValueConversion;
using System.Net;

namespace Gabi.Postgres;

/// <summary>
/// Main database context for GABI-SYNC persistence layer.
/// </summary>
public class GabiDbContext : DbContext
{
    public GabiDbContext(DbContextOptions<GabiDbContext> options) : base(options)
    {
    }

    // Discovery/Ingest Pipeline Tables
    public DbSet<SourceRegistry> SourceRegistries => Set<SourceRegistry>();
    public DbSet<DiscoveredLink> DiscoveredLinks => Set<DiscoveredLink>();
    public DbSet<SourceRefresh> SourceRefreshes => Set<SourceRefresh>();
    public DbSet<IngestJob> IngestJobs => Set<IngestJob>();
    public DbSet<PipelineState> PipelineStates => Set<PipelineState>();
    public DbSet<LinkHistory> LinkHistories => Set<LinkHistory>();
    
    // Audit
    public DbSet<AuditLog> AuditLogs => Set<AuditLog>();
    
    // Legacy (keep for compatibility during migration)
    public DbSet<DocumentEntity> Documents => Set<DocumentEntity>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);
        
        // Apply configurations
        ConfigureSourceRegistry(modelBuilder);
        ConfigureDiscoveredLinks(modelBuilder);
        ConfigureSourceRefresh(modelBuilder);
        ConfigureIngestJobs(modelBuilder);
        ConfigurePipelineState(modelBuilder);
        ConfigureAuditLog(modelBuilder);
        ConfigureLinkHistory(modelBuilder);
        ConfigureDocumentEntity(modelBuilder);
        
        // Global query filter for soft delete (if needed in future)
        // modelBuilder.Entity<DiscoveredLink>().HasQueryFilter(e => !e.IsDeleted);
    }
    
    private static void ConfigureSourceRegistry(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<SourceRegistry>(entity =>
        {
            entity.ToTable("source_registry");
            entity.HasKey(e => e.Id);
            
            entity.Property(e => e.Id).HasMaxLength(100);
            entity.Property(e => e.Name).HasMaxLength(255).IsRequired();
            entity.Property(e => e.Provider).HasMaxLength(100).IsRequired();
            entity.Property(e => e.Domain).HasMaxLength(100);
            entity.Property(e => e.Jurisdiction).HasMaxLength(10);
            entity.Property(e => e.Category).HasMaxLength(50);
            entity.Property(e => e.CanonicalType).HasMaxLength(50);
            entity.Property(e => e.DiscoveryStrategy).HasMaxLength(50).IsRequired();
            entity.Property(e => e.FetchProtocol).HasMaxLength(20).HasDefaultValue("https");
            
            // JSON columns
            entity.Property(e => e.DiscoveryConfig).HasColumnType("jsonb");
            entity.Property(e => e.FetchConfig).HasColumnType("jsonb");
            entity.Property(e => e.PipelineConfig).HasColumnType("jsonb");
            
            // Concurrency
            entity.Property(e => e.Version).IsRowVersion();
            
            // Indexes
            entity.HasIndex(e => e.Enabled);
            entity.HasIndex(e => e.Provider);
            entity.HasIndex(e => e.Category);
        });
    }
    
    private static void ConfigureDiscoveredLinks(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<DiscoveredLink>(entity =>
        {
            entity.ToTable("discovered_links");
            entity.HasKey(e => e.Id);
            
            entity.Property(e => e.SourceId).HasMaxLength(100).IsRequired();
            entity.Property(e => e.Url).IsRequired();
            entity.Property(e => e.UrlHash).HasMaxLength(64).IsRequired();
            entity.Property(e => e.Etag).HasMaxLength(255);
            entity.Property(e => e.Status).HasMaxLength(20);
            entity.Property(e => e.ContentHash).HasMaxLength(64);
            entity.Property(e => e.LastContentHash).HasMaxLength(64);
            entity.Property(e => e.Metadata).HasColumnType("jsonb");
            
            // Concurrency
            entity.Property(e => e.Version).IsRowVersion();
            
            // Unique constraint
            entity.HasIndex(e => new { e.SourceId, e.UrlHash }).IsUnique();
            
            // Indexes
            entity.HasIndex(e => new { e.SourceId, e.Status });
            entity.HasIndex(e => e.ContentHash);
            entity.HasIndex(e => e.DiscoveredAt);
            entity.HasIndex(e => e.Metadata).HasMethod("GIN");
            
            // Relationships
            entity.HasOne(e => e.Source)
                  .WithMany(s => s.DiscoveredLinks)
                  .HasForeignKey(e => e.SourceId)
                  .OnDelete(DeleteBehavior.Cascade);
        });
    }
    
    private static void ConfigureSourceRefresh(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<SourceRefresh>(entity =>
        {
            entity.ToTable("source_refresh");
            entity.HasKey(e => e.Id);
            
            entity.Property(e => e.SourceId).HasMaxLength(100).IsRequired();
            entity.Property(e => e.Status).HasMaxLength(20);
            entity.Property(e => e.ErrorDetails).HasColumnType("jsonb");
            entity.Property(e => e.TriggeredBy).HasMaxLength(100);
            entity.Property(e => e.RequestId).HasMaxLength(100);
            entity.Property(e => e.WorkerId).HasMaxLength(100);
            
            // Concurrency
            entity.Property(e => e.Version).IsRowVersion();
            
            // Indexes
            entity.HasIndex(e => new { e.SourceId, e.StartedAt });
            entity.HasIndex(e => new { e.Status, e.HeartbeatAt });
            entity.HasIndex(e => e.RequestId);
            
            // Relationships
            entity.HasOne(e => e.Source)
                  .WithMany(s => s.Refreshes)
                  .HasForeignKey(e => e.SourceId)
                  .OnDelete(DeleteBehavior.Cascade);
        });
    }
    
    private static void ConfigureIngestJobs(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<IngestJob>(entity =>
        {
            entity.ToTable("ingest_jobs");
            entity.HasKey(e => e.Id);
            
            entity.Property(e => e.JobType).HasMaxLength(50).IsRequired();
            entity.Property(e => e.Payload).HasColumnType("jsonb").IsRequired();
            entity.Property(e => e.PayloadHash).HasMaxLength(64).IsRequired();
            entity.Property(e => e.SourceId).HasMaxLength(100);
            entity.Property(e => e.Status).HasMaxLength(20);
            entity.Property(e => e.WorkerId).HasMaxLength(100);
            entity.Property(e => e.ErrorDetails).HasColumnType("jsonb");
            entity.Property(e => e.Result).HasColumnType("jsonb");
            
            // Concurrency
            entity.Property(e => e.Version).IsRowVersion();
            
            // Unique constraint for deduplication
            entity.HasIndex(e => e.PayloadHash).IsUnique();
            
            // Critical indexes for queue performance
            entity.HasIndex(e => new { e.Status, e.Priority, e.ScheduledAt, e.CreatedAt })
                  .HasDatabaseName("idx_jobs_available");
            entity.HasIndex(e => new { e.Status, e.WorkerId, e.LockedAt });
            entity.HasIndex(e => e.LinkId);
            entity.HasIndex(e => e.SourceId);
            entity.HasIndex(e => e.RetryAt);
            
            // Relationships
            entity.HasOne(e => e.Link)
                  .WithMany(l => l.Jobs)
                  .HasForeignKey(e => e.LinkId)
                  .OnDelete(DeleteBehavior.SetNull);
                  
            entity.HasOne(e => e.Source)
                  .WithMany()
                  .HasForeignKey(e => e.SourceId)
                  .OnDelete(DeleteBehavior.SetNull);
        });
    }
    
    private static void ConfigurePipelineState(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<PipelineState>(entity =>
        {
            entity.ToTable("pipeline_state");
            entity.HasKey(e => e.Id);
            
            entity.Property(e => e.StateKey).HasMaxLength(255).IsRequired();
            entity.Property(e => e.StateType).HasMaxLength(50).IsRequired();
            entity.Property(e => e.SourceId).HasMaxLength(100);
            entity.Property(e => e.Status).HasMaxLength(20);
            entity.Property(e => e.WorkerId).HasMaxLength(100);
            entity.Property(e => e.CheckpointData).HasColumnType("jsonb").IsRequired();
            
            // Concurrency
            entity.Property(e => e.Version).IsRowVersion();
            
            // Unique constraint
            entity.HasIndex(e => e.StateKey).IsUnique();
            
            // Indexes
            entity.HasIndex(e => new { e.SourceId, e.StateType });
            entity.HasIndex(e => new { e.Status, e.UpdatedAt });
            
            // Relationships
            entity.HasOne(e => e.Source)
                  .WithMany()
                  .HasForeignKey(e => e.SourceId)
                  .OnDelete(DeleteBehavior.Cascade);
        });
    }
    
    private static void ConfigureAuditLog(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<AuditLog>(entity =>
        {
            entity.ToTable("audit_log");
            entity.HasKey(e => e.Id);
            
            entity.Property(e => e.EventType).HasMaxLength(50).IsRequired();
            entity.Property(e => e.EntityType).HasMaxLength(50).IsRequired();
            entity.Property(e => e.EntityId).HasMaxLength(100).IsRequired();
            entity.Property(e => e.ActorType).HasMaxLength(20).IsRequired();
            entity.Property(e => e.ActorId).HasMaxLength(100);
            entity.Property(e => e.Action).HasMaxLength(20).IsRequired();
            entity.Property(e => e.OldValues).HasColumnType("jsonb");
            entity.Property(e => e.NewValues).HasColumnType("jsonb");
            entity.Property(e => e.RequestId).HasMaxLength(100);
            entity.Property(e => e.Metadata).HasColumnType("jsonb");
            
            // IP Address conversion
            var ipConverter = new ValueConverter<IPAddress?, string?>(
                v => v != null ? v.ToString() : null,
                v => v != null ? IPAddress.Parse(v) : null);
            entity.Property(e => e.SourceIp).HasConversion(ipConverter);
            
            // Indexes
            entity.HasIndex(e => new { e.EntityType, e.EntityId, e.OccurredAt });
            entity.HasIndex(e => new { e.ActorType, e.ActorId, e.OccurredAt });
            entity.HasIndex(e => new { e.EventType, e.OccurredAt });
            entity.HasIndex(e => e.OccurredAt);
            entity.HasIndex(e => e.RequestId);
        });
    }
    
    private static void ConfigureLinkHistory(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<LinkHistory>(entity =>
        {
            entity.ToTable("link_history");
            entity.HasKey(e => e.Id);
            
            entity.Property(e => e.Url).IsRequired();
            entity.Property(e => e.Status).HasMaxLength(20).IsRequired();
            entity.Property(e => e.Etag).HasMaxLength(255);
            entity.Property(e => e.ContentHash).HasMaxLength(64);
            entity.Property(e => e.Metadata).HasColumnType("jsonb");
            entity.Property(e => e.ChangedBy).HasMaxLength(100);
            entity.Property(e => e.ChangeReason).HasMaxLength(100);
            entity.Property(e => e.PreviousStatus).HasMaxLength(20);
            entity.Property(e => e.PreviousHash).HasMaxLength(64);
            
            // Indexes
            entity.HasIndex(e => new { e.LinkId, e.ChangedAt });
            entity.HasIndex(e => e.ChangedAt);
            
            // Relationships
            entity.HasOne(e => e.Link)
                  .WithMany(l => l.History)
                  .HasForeignKey(e => e.LinkId)
                  .OnDelete(DeleteBehavior.Cascade);
        });
    }
    
    private static void ConfigureDocumentEntity(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<DocumentEntity>(entity =>
        {
            entity.ToTable("documents");
            entity.HasKey(e => e.Id);
            
            entity.Property(e => e.SourceId).HasMaxLength(100).IsRequired();
            entity.Property(e => e.DocumentId).HasMaxLength(255).IsRequired();
            entity.Property(e => e.Title).HasMaxLength(1000);
            entity.Property(e => e.Fingerprint).HasMaxLength(64).IsRequired();
            entity.Property(e => e.Status).HasMaxLength(20);
            
            entity.HasIndex(e => e.DocumentId).IsUnique();
            entity.HasIndex(e => e.Fingerprint).IsUnique();
            entity.HasIndex(e => e.SourceId);
        });
    }
}
```

---

## 3. Repository Pattern Implementation

### 3.1 Generic Repository Interface

```csharp
namespace Gabi.Postgres.Repositories;

/// <summary>
/// Generic repository interface for basic CRUD operations.
/// </summary>
public interface IRepository<T> where T : class
{
    Task<T?> GetByIdAsync(object id, CancellationToken ct = default);
    Task<IReadOnlyList<T>> GetAllAsync(CancellationToken ct = default);
    Task<T> AddAsync(T entity, CancellationToken ct = default);
    Task<T> UpdateAsync(T entity, CancellationToken ct = default);
    Task DeleteAsync(T entity, CancellationToken ct = default);
}

/// <summary>
/// Generic repository with specification pattern support.
/// </summary>
public interface ISpecificationRepository<T> : IRepository<T> where T : class
{
    Task<IReadOnlyList<T>> ListAsync(ISpecification<T> spec, CancellationToken ct = default);
    Task<int> CountAsync(ISpecification<T> spec, CancellationToken ct = default);
    Task<bool> AnyAsync(ISpecification<T> spec, CancellationToken ct = default);
}

/// <summary>
/// Specification interface for query abstraction.
/// </summary>
public interface ISpecification<T>
{
    Expression<Func<T, bool>> Criteria { get; }
    List<Expression<Func<T, object>>> Includes { get; }
    List<string> IncludeStrings { get; }
    Expression<Func<T, object>>? OrderBy { get; }
    Expression<Func<T, object>>? OrderByDescending { get; }
    int Take { get; }
    int Skip { get; }
    bool IsPagingEnabled { get; }
}
```

### 3.2 Domain-Specific Repository Interfaces

```csharp
namespace Gabi.Postgres.Repositories;

/// <summary>
/// Repository for source registry operations.
/// </summary>
public interface ISourceRegistryRepository : ISpecificationRepository<SourceRegistry>
{
    Task<SourceRegistry?> GetByIdWithLinksAsync(string id, CancellationToken ct = default);
    Task<IReadOnlyList<SourceRegistry>> GetEnabledAsync(CancellationToken ct = default);
    Task<bool> ExistsAsync(string id, CancellationToken ct = default);
    Task UpsertAsync(SourceRegistry source, CancellationToken ct = default);
}

/// <summary>
/// Repository for discovered link operations.
/// </summary>
public interface IDiscoveredLinkRepository : ISpecificationRepository<DiscoveredLink>
{
    Task<DiscoveredLink?> GetBySourceAndUrlAsync(string sourceId, string url, CancellationToken ct = default);
    Task<IReadOnlyList<DiscoveredLink>> GetPendingBySourceAsync(string sourceId, int limit, CancellationToken ct = default);
    Task<IReadOnlyList<DiscoveredLink>> GetFailedAsync(int maxAttempts, int limit, CancellationToken ct = default);
    Task<int> CountByStatusAsync(string sourceId, string status, CancellationToken ct = default);
    Task<int> BulkUpsertAsync(IEnumerable<DiscoveredLink> links, CancellationToken ct = default);
    Task UpdateStatusAsync(long linkId, string status, string? contentHash = null, CancellationToken ct = default);
}

/// <summary>
/// Repository for job queue operations with leasing support.
/// </summary>
public interface IIngestJobRepository : ISpecificationRepository<IngestJob>
{
    /// <summary>
    /// Atomically claim the next available job for processing.
    /// </summary>
    Task<IngestJob?> ClaimNextAsync(
        string workerId, 
        string[] jobTypes, 
        TimeSpan leaseDuration,
        CancellationToken ct = default);
    
    /// <summary>
    /// Renew lease on a job.
    /// </summary>
    Task<bool> RenewLeaseAsync(long jobId, string workerId, TimeSpan leaseDuration, CancellationToken ct = default);
    
    /// <summary>
    /// Release a job back to the queue.
    /// </summary>
    Task ReleaseAsync(long jobId, string workerId, bool success, string? error = null, CancellationToken ct = default);
    
    /// <summary>
    /// Get jobs that have expired leases (for cleanup).
    /// </summary>
    Task<IReadOnlyList<IngestJob>> GetExpiredLeasesAsync(TimeSpan maxAge, CancellationToken ct = default);
    
    /// <summary>
    /// Bulk enqueue jobs with deduplication.
    /// </summary>
    Task<int> BulkEnqueueAsync(IEnumerable<IngestJob> jobs, CancellationToken ct = default);
    
    /// <summary>
    /// Get queue statistics.
    /// </summary>
    Task<QueueStatistics> GetStatisticsAsync(CancellationToken ct = default);
}

/// <summary>
/// Queue statistics.
/// </summary>
public record QueueStatistics(
    int Pending,
    int Queued,
    int Processing,
    int Completed,
    int Failed,
    int Dead,
    TimeSpan? AverageProcessingTime
);

/// <summary>
/// Repository for pipeline state/checkpoint operations.
/// </summary>
public interface IPipelineStateRepository : ISpecificationRepository<PipelineState>
{
    Task<PipelineState?> GetByKeyAsync(string stateKey, CancellationToken ct = default);
    Task<PipelineState> SaveCheckpointAsync(string stateKey, string stateType, JsonElement data, int position, CancellationToken ct = default);
    Task<IReadOnlyList<PipelineState>> GetActiveBySourceAsync(string sourceId, CancellationToken ct = default);
}

/// <summary>
/// Repository for audit log operations.
/// </summary>
public interface IAuditLogRepository
{
    Task LogAsync(AuditLog entry, CancellationToken ct = default);
    Task<IReadOnlyList<AuditLog>> GetByEntityAsync(string entityType, string entityId, int limit, CancellationToken ct = default);
    Task<IReadOnlyList<AuditLog>> GetByActorAsync(string actorType, string actorId, DateTime since, CancellationToken ct = default);
}
```

### 3.3 Repository Implementations

```csharp
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;

namespace Gabi.Postgres.Repositories;

/// <summary>
/// Base repository implementation.
/// </summary>
public abstract class RepositoryBase<T> : IRepository<T> where T : class
{
    protected readonly GabiDbContext _context;
    protected readonly DbSet<T> _dbSet;
    protected readonly ILogger<RepositoryBase<T>> _logger;

    protected RepositoryBase(GabiDbContext context, ILogger<RepositoryBase<T>> logger)
    {
        _context = context;
        _dbSet = context.Set<T>();
        _logger = logger;
    }

    public virtual async Task<T?> GetByIdAsync(object id, CancellationToken ct = default)
    {
        return await _dbSet.FindAsync(new[] { id }, ct);
    }

    public virtual async Task<IReadOnlyList<T>> GetAllAsync(CancellationToken ct = default)
    {
        return await _dbSet.ToListAsync(ct);
    }

    public virtual async Task<T> AddAsync(T entity, CancellationToken ct = default)
    {
        await _dbSet.AddAsync(entity, ct);
        return entity;
    }

    public virtual Task<T> UpdateAsync(T entity, CancellationToken ct = default)
    {
        _dbSet.Update(entity);
        return Task.FromResult(entity);
    }

    public virtual Task DeleteAsync(T entity, CancellationToken ct = default)
    {
        _dbSet.Remove(entity);
        return Task.CompletedTask;
    }
}

/// <summary>
/// Repository for discovered links with optimized queries.
/// </summary>
public class DiscoveredLinkRepository : RepositoryBase<DiscoveredLink>, IDiscoveredLinkRepository
{
    public DiscoveredLinkRepository(GabiDbContext context, ILogger<DiscoveredLinkRepository> logger) 
        : base(context, logger)
    {
    }

    public async Task<DiscoveredLink?> GetBySourceAndUrlAsync(string sourceId, string url, CancellationToken ct = default)
    {
        var urlHash = ComputeHash(url);
        return await _dbSet
            .FirstOrDefaultAsync(l => l.SourceId == sourceId && l.UrlHash == urlHash, ct);
    }

    public async Task<IReadOnlyList<DiscoveredLink>> GetPendingBySourceAsync(string sourceId, int limit, CancellationToken ct = default)
    {
        return await _dbSet
            .Where(l => l.SourceId == sourceId && l.Status == LinkStatus.Pending.ToString().ToLowerInvariant())
            .OrderBy(l => l.DiscoveredAt)
            .Take(limit)
            .ToListAsync(ct);
    }

    public async Task<IReadOnlyList<DiscoveredLink>> GetFailedAsync(int maxAttempts, int limit, CancellationToken ct = default)
    {
        return await _dbSet
            .Where(l => l.Status == LinkStatus.Failed.ToString().ToLowerInvariant() 
                     && l.ProcessAttempts < maxAttempts)
            .OrderBy(l => l.ProcessAttempts)
            .ThenBy(l => l.LastProcessedAt)
            .Take(limit)
            .ToListAsync(ct);
    }

    public async Task<int> CountByStatusAsync(string sourceId, string status, CancellationToken ct = default)
    {
        return await _dbSet
            .CountAsync(l => l.SourceId == sourceId && l.Status == status, ct);
    }

    public async Task<int> BulkUpsertAsync(IEnumerable<DiscoveredLink> links, CancellationToken ct = default)
    {
        var linkList = links.ToList();
        if (!linkList.Any()) return 0;

        // Use PostgreSQL upsert (ON CONFLICT DO UPDATE)
        var sourceId = linkList.First().SourceId;
        
        // Remove existing entries from change tracker to avoid conflicts
        foreach (var link in linkList)
        {
            var existing = await GetBySourceAndUrlAsync(link.SourceId, link.Url, ct);
            if (existing != null)
            {
                _context.Entry(existing).State = EntityState.Detached;
            }
        }

        // Insert new links
        await _dbSet.AddRangeAsync(linkList, ct);
        
        _logger.LogInformation("Bulk upsert prepared for {Count} links in source {SourceId}", 
            linkList.Count, sourceId);
            
        return linkList.Count;
    }

    public async Task UpdateStatusAsync(long linkId, string status, string? contentHash = null, CancellationToken ct = default)
    {
        var link = await GetByIdAsync(linkId, ct);
        if (link == null) return;

        var oldStatus = link.Status;
        link.Status = status;
        
        if (contentHash != null)
        {
            link.LastContentHash = link.ContentHash;
            link.ContentHash = contentHash;
        }

        if (status == LinkStatus.Processing.ToString().ToLowerInvariant())
        {
            link.LastProcessedAt = DateTime.UtcNow;
        }
        else if (status == LinkStatus.Failed.ToString().ToLowerInvariant())
        {
            link.ProcessAttempts++;
        }

        await UpdateAsync(link, ct);
        
        // Add history entry
        var history = new LinkHistory
        {
            LinkId = linkId,
            Url = link.Url,
            Status = status,
            ContentHash = contentHash,
            PreviousStatus = oldStatus,
            PreviousHash = link.LastContentHash,
            ChangeReason = "status_update"
        };
        await _context.LinkHistories.AddAsync(history, ct);
    }

    private static string ComputeHash(string input)
    {
        using var sha256 = System.Security.Cryptography.SHA256.Create();
        var bytes = sha256.ComputeHash(System.Text.Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }
}

/// <summary>
/// Repository for job queue with atomic claim operations.
/// </summary>
public class IngestJobRepository : RepositoryBase<IngestJob>, IIngestJobRepository
{
    public IngestJobRepository(GabiDbContext context, ILogger<IngestJobRepository> logger) 
        : base(context, logger)
    {
    }

    public async Task<IngestJob?> ClaimNextAsync(
        string workerId, 
        string[] jobTypes, 
        TimeSpan leaseDuration,
        CancellationToken ct = default)
    {
        // Use advisory lock for distributed safety (optional enhancement)
        var now = DateTime.UtcNow;
        var expiresAt = now.Add(leaseDuration);

        // Find and claim in single atomic operation
        var job = await _dbSet
            .Where(j => jobTypes.Contains(j.JobType))
            .Where(j => j.Status == JobStatus.Pending.ToString().ToLowerInvariant() 
                     || j.Status == JobStatus.Queued.ToString().ToLowerInvariant())
            .Where(j => j.ScheduledAt <= now)
            .Where(j => j.LockExpiresAt == null || j.LockExpiresAt < now) // Not locked or expired
            .OrderBy(j => j.Priority)
            .ThenBy(j => j.CreatedAt)
            .FirstOrDefaultAsync(ct);

        if (job == null) return null;

        // Claim the job
        job.Status = JobStatus.Processing.ToString().ToLowerInvariant();
        job.WorkerId = workerId;
        job.LockedAt = now;
        job.LockExpiresAt = expiresAt;
        job.StartedAt = now;
        job.Attempts++;

        await UpdateAsync(job, ct);
        
        _logger.LogDebug("Job {JobId} claimed by worker {WorkerId}, expires at {ExpiresAt}", 
            job.Id, workerId, expiresAt);

        return job;
    }

    public async Task<bool> RenewLeaseAsync(long jobId, string workerId, TimeSpan leaseDuration, CancellationToken ct = default)
    {
        var job = await _dbSet.FindAsync(new object[] { jobId }, ct);
        if (job == null || job.WorkerId != workerId) return false;

        job.LockExpiresAt = DateTime.UtcNow.Add(leaseDuration);
        await UpdateAsync(job, ct);
        
        return true;
    }

    public async Task ReleaseAsync(long jobId, string workerId, bool success, string? error = null, CancellationToken ct = default)
    {
        var job = await _dbSet.FindAsync(new object[] { jobId }, ct);
        if (job == null || job.WorkerId != workerId)
        {
            _logger.LogWarning("Attempt to release job {JobId} by non-owner {WorkerId}", jobId, workerId);
            return;
        }

        job.WorkerId = null;
        job.LockedAt = null;
        job.LockExpiresAt = null;
        job.CompletedAt = DateTime.UtcNow;

        if (success)
        {
            job.Status = JobStatus.Completed.ToString().ToLowerInvariant();
            job.ProgressPercent = 100;
        }
        else
        {
            job.LastError = error;
            
            if (job.Attempts >= job.MaxAttempts)
            {
                job.Status = JobStatus.Dead.ToString().ToLowerInvariant();
                _logger.LogError("Job {JobId} moved to dead letter queue after {Attempts} attempts. Error: {Error}",
                    jobId, job.Attempts, error);
            }
            else
            {
                job.Status = JobStatus.Failed.ToString().ToLowerInvariant();
                // Exponential backoff: 2^attempts minutes
                var delay = TimeSpan.FromMinutes(Math.Pow(2, job.Attempts));
                job.RetryAt = DateTime.UtcNow.Add(delay);
                _logger.LogWarning("Job {JobId} failed (attempt {Attempts}/{MaxAttempts}), retry at {RetryAt}. Error: {Error}",
                    jobId, job.Attempts, job.MaxAttempts, job.RetryAt, error);
            }
        }

        await UpdateAsync(job, ct);
    }

    public async Task<IReadOnlyList<IngestJob>> GetExpiredLeasesAsync(TimeSpan maxAge, CancellationToken ct = default)
    {
        var cutoff = DateTime.UtcNow.Subtract(maxAge);
        
        return await _dbSet
            .Where(j => j.Status == JobStatus.Processing.ToString().ToLowerInvariant())
            .Where(j => j.LockExpiresAt < cutoff)
            .ToListAsync(ct);
    }

    public async Task<int> BulkEnqueueAsync(IEnumerable<IngestJob> jobs, CancellationToken ct = default)
    {
        var jobList = jobs.ToList();
        if (!jobList.Any()) return 0;

        await _dbSet.AddRangeAsync(jobList, ct);
        
        _logger.LogInformation("Bulk enqueued {Count} jobs", jobList.Count);
        return jobList.Count;
    }

    public async Task<QueueStatistics> GetStatisticsAsync(CancellationToken ct = default)
    {
        var stats = await _dbSet
            .GroupBy(j => j.Status)
            .Select(g => new { Status = g.Key, Count = g.Count() })
            .ToListAsync(ct);

        var completed = await _dbSet
            .Where(j => j.Status == JobStatus.Completed.ToString().ToLowerInvariant())
            .Where(j => j.CompletedAt.HasValue && j.StartedAt.HasValue)
            .Select(j => EF.Functions.DateDiffMillisecond(j.StartedAt!.Value, j.CompletedAt!.Value))
            .AverageAsync(ct);

        return new QueueStatistics(
            Pending: stats.FirstOrDefault(s => s.Status == JobStatus.Pending.ToString().ToLowerInvariant())?.Count ?? 0,
            Queued: stats.FirstOrDefault(s => s.Status == JobStatus.Queued.ToString().ToLowerInvariant())?.Count ?? 0,
            Processing: stats.FirstOrDefault(s => s.Status == JobStatus.Processing.ToString().ToLowerInvariant())?.Count ?? 0,
            Completed: stats.FirstOrDefault(s => s.Status == JobStatus.Completed.ToString().ToLowerInvariant())?.Count ?? 0,
            Failed: stats.FirstOrDefault(s => s.Status == JobStatus.Failed.ToString().ToLowerInvariant())?.Count ?? 0,
            Dead: stats.FirstOrDefault(s => s.Status == JobStatus.Dead.ToString().ToLowerInvariant())?.Count ?? 0,
            AverageProcessingTime: completed.HasValue ? TimeSpan.FromMilliseconds(completed.Value) : null
        );
    }
}
```

---

## 4. Unit of Work Pattern

### 4.1 Unit of Work Interface

```csharp
namespace Gabi.Postgres.Repositories;

/// <summary>
/// Unit of Work pattern for transaction management.
/// </summary>
public interface IUnitOfWork : IAsyncDisposable
{
    ISourceRegistryRepository SourceRegistries { get; }
    IDiscoveredLinkRepository DiscoveredLinks { get; }
    IIngestJobRepository IngestJobs { get; }
    IPipelineStateRepository PipelineStates { get; }
    IAuditLogRepository AuditLogs { get; }
    IDocumentRepository Documents { get; }
    
    /// <summary>
    /// Save all pending changes.
    /// </summary>
    Task<int> SaveChangesAsync(CancellationToken ct = default);
    
    /// <summary>
    /// Begin a transaction.
    /// </summary>
    Task<IDbContextTransaction> BeginTransactionAsync(CancellationToken ct = default);
    
    /// <summary>
    /// Commit current transaction.
    /// </summary>
    Task CommitTransactionAsync(CancellationToken ct = default);
    
    /// <summary>
    /// Rollback current transaction.
    /// </summary>
    Task RollbackTransactionAsync(CancellationToken ct = default);
    
    /// <summary>
    /// Execute action within a transaction.
    /// </summary>
    Task<T> ExecuteInTransactionAsync<T>(Func<Task<T>> action, CancellationToken ct = default);
}
```

### 4.2 Unit of Work Implementation

```csharp
using Microsoft.EntityFrameworkCore.Storage;

namespace Gabi.Postgres.Repositories;

/// <summary>
/// Unit of Work implementation for GabiDbContext.
/// </summary>
public class UnitOfWork : IUnitOfWork
{
    private readonly GabiDbContext _context;
    private readonly ILogger<UnitOfWork> _logger;
    private IDbContextTransaction? _currentTransaction;
    
    private ISourceRegistryRepository? _sourceRegistries;
    private IDiscoveredLinkRepository? _discoveredLinks;
    private IIngestJobRepository? _ingestJobs;
    private IPipelineStateRepository? _pipelineStates;
    private IAuditLogRepository? _auditLogs;
    private IDocumentRepository? _documents;

    public UnitOfWork(
        GabiDbContext context, 
        ILogger<UnitOfWork> logger,
        ILogger<DiscoveredLinkRepository> linkLogger,
        ILogger<IngestJobRepository> jobLogger)
    {
        _context = context;
        _logger = logger;
        
        // Initialize repositories with their loggers
        _sourceRegistries = new SourceRegistryRepository(context, logger);
        _discoveredLinks = new DiscoveredLinkRepository(context, linkLogger);
        _ingestJobs = new IngestJobRepository(context, jobLogger);
    }

    public ISourceRegistryRepository SourceRegistries => 
        _sourceRegistries ??= new SourceRegistryRepository(_context, _logger);
        
    public IDiscoveredLinkRepository DiscoveredLinks => 
        _discoveredLinks ??= new DiscoveredLinkRepository(_context, _logger);
        
    public IIngestJobRepository IngestJobs => 
        _ingestJobs ??= new IngestJobRepository(_context, _logger);
        
    public IPipelineStateRepository PipelineStates => 
        _pipelineStates ??= new PipelineStateRepository(_context, _logger);
        
    public IAuditLogRepository AuditLogs => 
        _auditLogs ??= new AuditLogRepository(_context, _logger);
        
    public IDocumentRepository Documents => 
        _documents ??= new DocumentRepository(_context, _logger);

    public Task<int> SaveChangesAsync(CancellationToken ct = default)
    {
        return _context.SaveChangesAsync(ct);
    }

    public async Task<IDbContextTransaction> BeginTransactionAsync(CancellationToken ct = default)
    {
        if (_currentTransaction != null)
        {
            throw new InvalidOperationException("A transaction is already in progress");
        }

        _currentTransaction = await _context.Database.BeginTransactionAsync(ct);
        _logger.LogDebug("Transaction started");
        return _currentTransaction;
    }

    public async Task CommitTransactionAsync(CancellationToken ct = default)
    {
        if (_currentTransaction == null)
        {
            throw new InvalidOperationException("No transaction in progress");
        }

        try
        {
            await _currentTransaction.CommitAsync(ct);
            _logger.LogDebug("Transaction committed");
        }
        finally
        {
            await _currentTransaction.DisposeAsync();
            _currentTransaction = null;
        }
    }

    public async Task RollbackTransactionAsync(CancellationToken ct = default)
    {
        if (_currentTransaction == null)
        {
            throw new InvalidOperationException("No transaction in progress");
        }

        try
        {
            await _currentTransaction.RollbackAsync(ct);
            _logger.LogDebug("Transaction rolled back");
        }
        finally
        {
            await _currentTransaction.DisposeAsync();
            _currentTransaction = null;
        }
    }

    public async Task<T> ExecuteInTransactionAsync<T>(Func<Task<T>> action, CancellationToken ct = default)
    {
        await using var transaction = await BeginTransactionAsync(ct);
        
        try
        {
            var result = await action();
            await CommitTransactionAsync(ct);
            return result;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Transaction failed, rolling back");
            await RollbackTransactionAsync(ct);
            throw;
        }
    }

    public async ValueTask DisposeAsync()
    {
        if (_currentTransaction != null)
        {
            await _currentTransaction.DisposeAsync();
        }
        await _context.DisposeAsync();
    }
}
```

---

## 5. Optimistic Concurrency for Distributed Processing

### 5.1 Concurrency Strategy

The design uses PostgreSQL row-level versioning (`xmin` system column) for optimistic concurrency:

```csharp
// In DbContext configuration:
entity.Property(e => e.Version)
    .IsRowVersion()  // Maps to PostgreSQL 'xmin' system column
    .HasColumnName("xmin")
    .HasColumnType("xid");
```

### 5.2 Concurrency-Affected Operations

| Operation | Concurrency Risk | Mitigation |
|-----------|-----------------|------------|
| Job Claim | Multiple workers claim same job | Atomic UPDATE + WHERE, version check |
| Link Update | Concurrent status changes | Version check on update |
| Checkpoint Save | Overwrite progress | Version check, merge strategy |
| Refresh State | Multiple concurrent refreshes | Row-level lock on source_refresh |

### 5.3 Conflict Resolution

```csharp
/// <summary>
/// Handles optimistic concurrency conflicts.
/// </summary>
public class ConcurrencyResolver
{
    private readonly ILogger<ConcurrencyResolver> _logger;

    public ConcurrencyResolver(ILogger<ConcurrencyResolver> logger)
    {
        _logger = logger;
    }

    /// <summary>
    /// Execute with automatic retry on concurrency conflict.
    /// </summary>
    public async Task<T> ExecuteWithRetry<T>(
        Func<Task<T>> operation, 
        int maxRetries = 3,
        CancellationToken ct = default)
    {
        for (int attempt = 1; attempt <= maxRetries; attempt++)
        {
            try
            {
                return await operation();
            }
            catch (DbUpdateConcurrencyException ex)
            {
                if (attempt == maxRetries)
                {
                    _logger.LogError(ex, "Concurrency conflict persisted after {MaxRetries} retries", maxRetries);
                    throw;
                }

                var delay = TimeSpan.FromMilliseconds(100 * Math.Pow(2, attempt));
                _logger.LogWarning("Concurrency conflict on attempt {Attempt}, retrying in {Delay}ms", 
                    attempt, delay.TotalMilliseconds);
                    
                await Task.Delay(delay, ct);
            }
        }

        throw new InvalidOperationException("Should not reach here");
    }
}

/// <summary>
/// Exception for business-level concurrency conflicts.
/// </summary>
public class ConcurrencyException : Exception
{
    public string EntityType { get; }
    public string EntityId { get; }
    public uint ExpectedVersion { get; }
    public uint ActualVersion { get; }

    public ConcurrencyException(
        string entityType, 
        string entityId, 
        uint expectedVersion, 
        uint actualVersion)
        : base($"Concurrency conflict on {entityType} {entityId}: expected v{expectedVersion}, found v{actualVersion}")
    {
        EntityType = entityType;
        EntityId = entityId;
        ExpectedVersion = expectedVersion;
        ActualVersion = actualVersion;
    }
}
```

### 5.4 Distributed Locking (Optional Enhancement)

For operations requiring distributed coordination:

```csharp
/// <summary>
/// PostgreSQL advisory lock implementation.
/// </summary>
public class DistributedLock : IAsyncDisposable
{
    private readonly NpgsqlConnection _connection;
    private readonly long _lockId;
    private readonly ILogger<DistributedLock> _logger;
    private bool _acquired;

    public DistributedLock(
        string connectionString, 
        string lockKey,
        ILogger<DistributedLock> logger)
    {
        _connection = new NpgsqlConnection(connectionString);
        _lockId = ComputeLockId(lockKey);
        _logger = logger;
    }

    public async Task<bool> TryAcquireAsync(TimeSpan timeout, CancellationToken ct = default)
    {
        await _connection.OpenAsync(ct);
        
        // pg_try_advisory_lock is non-blocking
        using var cmd = new NpgsqlCommand(
            "SELECT pg_try_advisory_lock(@lockId)", _connection);
        cmd.Parameters.AddWithValue("lockId", _lockId);
        
        _acquired = (bool)(await cmd.ExecuteScalarAsync(ct))!;
        
        if (_acquired)
        {
            _logger.LogDebug("Acquired distributed lock {LockId} for key {LockKey}", 
                _lockId, _lockKey);
        }
        
        return _acquired;
    }

    public async ValueTask DisposeAsync()
    {
        if (_acquired)
        {
            using var cmd = new NpgsqlCommand(
                "SELECT pg_advisory_unlock(@lockId)", _connection);
            cmd.Parameters.AddWithValue("lockId", _lockId);
            await cmd.ExecuteNonQueryAsync();
            
            _logger.LogDebug("Released distributed lock {LockId}", _lockId);
        }
        
        await _connection.DisposeAsync();
    }

    private static long ComputeLockId(string key)
    {
        // Convert string key to 64-bit integer for pg_advisory_lock
        var hash = System.Security.Cryptography.SHA256.HashData(
            System.Text.Encoding.UTF8.GetBytes(key));
        return BitConverter.ToInt64(hash, 0);
    }
}
```

---

## 6. Dependency Injection Configuration

```csharp
// In Program.cs or Startup.cs:

// DbContext
builder.Services.AddDbContext<GabiDbContext>(options =>
{
    options.UseNpgsql(
        builder.Configuration.GetConnectionString("Default"),
        npgsql =>
        {
            npgsql.MigrationsAssembly("Gabi.Postgres");
            npgsql.MigrationsHistoryTable("__EFMigrationsHistory", "public");
            npgsql.EnableRetryOnFailure(
                maxRetryCount: 3,
                maxRetryDelay: TimeSpan.FromSeconds(30),
                errorCodesToAdd: null);
        });
    
    options.UseQueryTrackingBehavior(QueryTrackingBehavior.NoTrackingWithIdentityResolution);
    
    if (builder.Environment.IsDevelopment())
    {
        options.EnableSensitiveDataLogging();
        options.EnableDetailedErrors();
    }
});

// Repositories
builder.Services.AddScoped<IUnitOfWork, UnitOfWork>();
builder.Services.AddScoped<ISourceRegistryRepository, SourceRegistryRepository>();
builder.Services.AddScoped<IDiscoveredLinkRepository, DiscoveredLinkRepository>();
builder.Services.AddScoped<IIngestJobRepository, IngestJobRepository>();
builder.Services.AddScoped<IPipelineStateRepository, PipelineStateRepository>();
builder.Services.AddScoped<IAuditLogRepository, AuditLogRepository>();

// Concurrency
builder.Services.AddSingleton<ConcurrencyResolver>();
```

---

## 7. Migration Strategy

### 7.1 Initial Migration

```bash
# Create migration
dotnet ef migrations add InitialPersistence \
    --project src/Gabi.Postgres \
    --startup-project src/Gabi.Worker \
    --output-dir Migrations

# Apply to database
dotnet ef database update \
    --project src/Gabi.Postgres \
    --startup-project src/Gabi.Worker
```

### 7.2 Migration Script for Production

```bash
# Generate SQL script for review
dotnet ef migrations script \
    --project src/Gabi.Postgres \
    --startup-project src/Gabi.Worker \
    --output deploy/001_initial_persistence.sql
```

---

## 8. Performance Optimizations

### 8.1 Batching Strategy

| Operation | Batch Size | Strategy |
|-----------|-----------|----------|
| Link Discovery | 1000 | Bulk INSERT with ON CONFLICT |
| Job Enqueue | 500 | Bulk INSERT with dedup check |
| Status Updates | 100 | Batch UPDATE with WHERE IN |
| Audit Log | 1000 | Fire-and-forget background write |

### 8.2 Key Performance Indexes

All critical query paths are covered by indexes:

1. **Job Queue**: Composite index on `(status, priority, scheduled_at, created_at)`
2. **Link Lookup**: Unique index on `(source_id, url_hash)`
3. **Refresh History**: Index on `(source_id, started_at DESC)`
4. **Audit Queries**: Index on `(entity_type, entity_id, occurred_at)`

### 8.3 Connection Pooling

```csharp
// In connection string:
"Host=localhost;Port=5433;Database=gabi;Username=gabi;Password=***;"
"Maximum Pool Size=50;"      // Max connections in pool
"Minimum Pool Size=10;"      // Keep warm
"Connection Idle Lifetime=300;"  // 5 minutes
"Connection Pruning Interval=60;" // Check every minute
```

---

## 9. Resilience Patterns

### 9.1 Retry Policies

```csharp
// Npgsql built-in retry
options.EnableRetryOnFailure(
    maxRetryCount: 3,
    maxRetryDelay: TimeSpan.FromSeconds(30),
    errorCodesToAdd: new[] { "40001" }); // serialization_failure

// Polly for application-level retries
var retryPolicy = Policy
    .Handle<NpgsqlException>(ex => ex.IsTransient)
    .WaitAndRetryAsync(
        retryCount: 3,
        sleepDurationProvider: retryAttempt => 
            TimeSpan.FromSeconds(Math.Pow(2, retryAttempt)),
        onRetry: (exception, timeSpan, retryCount, context) =>
        {
            logger.LogWarning(exception, 
                "Database operation failed (attempt {RetryCount}), retrying in {Delay}s",
                retryCount, timeSpan.TotalSeconds);
        });
```

### 9.2 Circuit Breaker (for degraded database)

```csharp
var circuitBreaker = Policy
    .Handle<NpgsqlException>()
    .CircuitBreakerAsync(
        exceptionsAllowedBeforeBreaking: 5,
        durationOfBreak: TimeSpan.FromMinutes(1),
        onBreak: (exception, duration) =>
            logger.LogError("Database circuit broken for {Duration}s", duration),
        onReset: () =>
            logger.LogInformation("Database circuit reset"));
```

---

## 10. Implementation Roadmap

### Phase 1: Core Schema (Week 1)
- [ ] Create EF Core entities
- [ ] Generate initial migration
- [ ] Implement base repositories
- [ ] Unit tests for repositories

### Phase 2: Repository Layer (Week 1-2)
- [ ] SourceRegistry repository
- [ ] DiscoveredLink repository with bulk ops
- [ ] Unit of Work implementation
- [ ] Integration tests

### Phase 3: Job Queue (Week 2)
- [ ] IngestJob repository with claim/release
- [ ] Queue worker implementation
- [ ] Lease management and cleanup
- [ ] Dead letter queue handling

### Phase 4: Migration (Week 3)
- [ ] Update SourceCatalogService to use persistence
- [ ] Migrate in-memory dictionaries
- [ ] Data migration scripts
- [ ] Backward compatibility layer

### Phase 5: Production Hardening (Week 3-4)
- [ ] Performance testing
- [ ] Concurrency stress tests
- [ ] Audit logging integration
- [ ] Monitoring and alerts

---

## 11. Appendix: SQL Scripts

### Create Database

```sql
-- Create database (run as postgres superuser)
CREATE DATABASE gabi WITH 
    ENCODING = 'UTF8'
    LC_COLLATE = 'en_US.UTF-8'
    LC_CTYPE = 'en_US.UTF-8';

-- Create application user
CREATE USER gabi_app WITH PASSWORD 'secure_password';
GRANT ALL PRIVILEGES ON DATABASE gabi TO gabi_app;

-- After connecting to gabi database:
GRANT ALL ON SCHEMA public TO gabi_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO gabi_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO gabi_app;
```

### Health Check Query

```sql
-- Quick health check for monitoring
SELECT 
    (SELECT COUNT(*) FROM source_registry WHERE enabled) as enabled_sources,
    (SELECT COUNT(*) FROM discovered_links WHERE status = 'pending') as pending_links,
    (SELECT COUNT(*) FROM ingest_jobs WHERE status = 'pending') as pending_jobs,
    (SELECT COUNT(*) FROM ingest_jobs WHERE status = 'processing') as processing_jobs,
    (SELECT COUNT(*) FROM ingest_jobs WHERE status = 'failed') as failed_jobs,
    (SELECT COUNT(*) FROM ingest_jobs WHERE status = 'dead') as dead_jobs;
```

---

*Document version: 1.0*  
*Next review: 2026-03-12*
