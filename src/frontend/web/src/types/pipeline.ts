export type FileStatus =
  | "DISCOVERED" | "QUEUED" | "DOWNLOADING" | "DOWNLOADED"
  | "EXTRACTING" | "EXTRACTED"
  | "BM25_INDEXING" | "BM25_INDEXED" | "EMBEDDING" | "EMBEDDED" | "VERIFYING" | "VERIFIED"
  | "DOWNLOAD_FAILED" | "EXTRACT_FAILED" | "BM25_INDEX_FAILED" | "EMBEDDING_FAILED" | "VERIFY_FAILED";

export interface FileRecord {
  id: number;
  filename: string;
  section: string;
  year_month: string;
  folder_id: number | null;
  file_url: string | null;
  status: FileStatus;
  retry_count: number;
  doc_count: number | null;
  file_size_bytes: number | null;
  sha256: string | null;
  error_message: string | null;
  discovered_at: string;
  queued_at: string | null;
  downloaded_at: string | null;
  extracted_at: string | null;
  ingested_at: string | null;
  bm25_indexed_at: string | null;
  embedded_at: string | null;
  verified_at: string | null;
  updated_at: string;
}

export interface PipelineRun {
  id: string;
  phase: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  files_processed: number;
  files_succeeded: number;
  files_failed: number;
  error_message: string | null;
}

export interface LogEntry {
  id: number;
  run_id: string | null;
  file_id: number | null;
  level: string;
  message: string;
  created_at: string;
}

export type RegistryStatus = Record<FileStatus, number>;

export interface SchedulerJob {
  id: string;
  next_run_time: string | null;
}

export interface SchedulerStatus {
  running: boolean;
  paused: boolean;
  jobs: SchedulerJob[];
}

export interface HealthStatus {
  status: string;
  uptime_seconds: number;
  scheduler_running: boolean;
  scheduler_paused: boolean;
  scheduler_jobs: SchedulerJob[];
  last_heartbeat: string;
  disk_usage: {
    db_size_bytes: number;
    tmp_size_bytes: number;
    free_bytes: number;
    total_bytes: number;
  };
}

export interface TimelineFile {
  id: number;
  filename: string;
  year_month: string;
  section: string;
  status: FileStatus;
  retry_count: number;
  doc_count: number | null;
  file_size_bytes: number | null;
  error_message: string | null;
  discovered_at: string | null;
  queued_at: string | null;
  downloaded_at: string | null;
  extracted_at: string | null;
  ingested_at: string | null;
  bm25_indexed_at: string | null;
  embedded_at: string | null;
  verified_at: string | null;
  updated_at: string;
}

export interface RegistryStats {
  total_files: number;
  verified_files: number;
  failed_files: number;
  active_files: number;
  total_docs: number;
  last_verified_at: string | null;
  last_activity_at: string | null;
  max_retry_count: number | null;
  retry_backlog: number;
  status_counts: RegistryStatus;
  disk_usage: {
    db_size_bytes: number;
    tmp_size_bytes: number;
    free_bytes: number;
    total_bytes: number;
  };
  latest_run: PipelineRun | null;
}

export type MonthData = TimelineFile;
