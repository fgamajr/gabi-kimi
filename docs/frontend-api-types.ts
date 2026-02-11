/**
 * GABI API TypeScript Types
 * 
 * These types mirror the backend Pydantic schemas exactly.
 * Copy this file to: frontend/src/lib/api/types.ts
 */

// ============================================================================
// Enums
// ============================================================================

export type SourceStatus = 'active' | 'inactive' | 'disabled' | 'error';
export type SourceType = 'csv_http' | 'api_rest' | 'web_scraper' | 'ftp' | 'database';

export type PipelinePhase = 
  | 'discovery' 
  | 'change_detection' 
  | 'fetch' 
  | 'parse' 
  | 'fingerprint' 
  | 'deduplication' 
  | 'chunking' 
  | 'embedding' 
  | 'indexing';

export type StageStatus = 'active' | 'idle' | 'error';
export type OverallStatus = 'healthy' | 'degraded' | 'stalled' | 'unhealthy';
export type Severity = 'info' | 'warning' | 'error' | 'critical';

// ============================================================================
// Dashboard Stats
// ============================================================================

export interface DashboardSourceSummary {
  id: string;
  name: string;
  description?: string;
  source_type: SourceType;
  status: SourceStatus;
  enabled: boolean;
  document_count: number;
  last_sync_at?: string;
  last_success_at?: string;
  consecutive_errors: number;
}

export interface DashboardStatsResponse {
  sources: DashboardSourceSummary[];
  total_documents: number;
  total_chunks: number;
  total_indexed: number;
  total_embeddings: number;
  active_sources: number;
  documents_last_24h: number;
  dlq_pending: number;
  elasticsearch_available: boolean;
  total_elastic_docs?: number;
  generated_at: string;
}

// ============================================================================
// Pipeline
// ============================================================================

export interface PipelineStageInfo {
  name: PipelinePhase;
  label: string;
  description: string;
  count: number;
  total: number;
  failed: number;
  status: StageStatus;
  last_activity?: string;
}

export interface DashboardPipelineResponse {
  stages: PipelineStageInfo[];
  overall_status: OverallStatus;
  generated_at: string;
}

// ============================================================================
// Activity
// ============================================================================

export interface ActivityEvent {
  id: string;
  timestamp: string;
  event_type: string;
  severity: Severity;
  source_id?: string;
  description: string;
  details?: Record<string, unknown>;
  run_id?: string;
}

export interface DashboardActivityResponse {
  events: ActivityEvent[];
  total: number;
  has_more: boolean;
  generated_at: string;
}

// ============================================================================
// Health
// ============================================================================

export interface ComponentHealth {
  name: string;
  status: 'online' | 'degraded' | 'offline';
  latency_ms?: number;
  version?: string;
  details: Record<string, unknown>;
}

export interface DashboardHealthResponse {
  status: OverallStatus;
  uptime_seconds: number;
  components: ComponentHealth[];
  generated_at: string;
}

// ============================================================================
// Sources
// ============================================================================

export interface SourceListResponse {
  total: number;
  sources: DashboardSourceSummary[];
}

export interface SourceSyncRequest {
  mode: 'full' | 'incremental';
  force?: boolean;
  triggered_by?: string;
}

export interface SourceSyncResponse {
  success: boolean;
  source_id: string;
  run_id: string;
  message: string;
  started_at: string;
}

export interface TriggerIngestionResponse {
  message: string;
  source_id: string;
  source_name: string;
  status: 'queued' | 'already_running';
  timestamp: string;
}

// ============================================================================
// Frontend-Mapped Types (for backward compatibility)
// ============================================================================

/**
 * Frontend pipeline stage (4 stages)
 * Maps from backend's 9 stages
 */
export interface FrontendPipelineStage {
  name: 'harvest' | 'sync' | 'ingest' | 'index';
  label: string;
  description: string;
  count: number;
  total: number;
  status: StageStatus;
  lastActivity?: string;
}

/**
 * Frontend activity job format
 * Maps from backend's audit events
 */
export interface FrontendActivityJob {
  source: string;
  year: number;
  status: 'synced' | 'pending' | 'failed' | 'in_progress';
  updated_at: string | null;
}

/**
 * Legacy Source interface (matches existing dashboard-data.ts)
 */
export interface LegacySource {
  id: string;
  description: string;
  source_type: string;
  enabled: boolean;
  document_count: number;
}
