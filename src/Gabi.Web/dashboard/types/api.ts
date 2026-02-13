// Contratos da API GABI

export interface Source {
  id: string;
  description: string;
  source_type: string;
  enabled: boolean;
  document_count: number;
}

export interface SourceDetails {
  id: string;
  name: string;
  description: string | null;
  provider: string;
  discoveryStrategy: string;
  enabled: boolean;
  totalLinks: number;
  lastRefresh: string | null;
  statistics: {
    linksByStatus: Record<string, number>;
    totalDocuments: number;
    lastDiscoveryAt: string | null;
  };
}

export interface DiscoveredLink {
  id: number;
  sourceId: string;
  url: string;
  status: string;
  discoveredAt: string;
  lastModified: string | null;
  etag: string | null;
  contentLength: number | null;
  contentHash: string | null;
  documentCount: number;
  processAttempts: number;
  metadata: Record<string, unknown> | null;
  pipeline: LinkPipelineStatus;
}

export interface LinkPipelineStatus {
  discovery: PipelineStageStatus;
  ingest: PipelineStageStatus;
  processing: PipelineStageStatus;
  embedding: PipelineStageStatus;
  indexing: PipelineStageStatus;
}

export interface PipelineStageStatus {
  status: 'completed' | 'planned' | 'active' | 'error' | 'pending';
  availability: 'available' | 'coming_soon';
  completedAt: string | null;
  message: string | null;
}

export interface PipelineStage {
  name: 'discovery' | 'ingest' | 'processing' | 'embedding' | 'indexing';
  label: string;
  description: string;
  count: number;
  total: number;
  status: 'active' | 'idle' | 'error';
  availability: 'available' | 'coming_soon';
  message: string | null;
  lastActivity: string | null;
}

export interface LinkListResponse {
  data: DiscoveredLink[];
  pagination: {
    page: number;
    pageSize: number;
    totalItems: number;
    totalPages: number;
  };
}

export interface DashboardStats {
  sources: Source[];
  total_documents: number;
  elasticsearch_available: boolean;
  sync_status?: SyncStatus;
  throughput?: Throughput;
  rag_stats?: RagStats;
}

export interface SyncStatus {
  synced_count: number;
  processing_count: number;
  total_count: number;
}

export interface Throughput {
  docs_per_min: number;
  eta_minutes: number | null;
}

export interface RagStats {
  indexed_count: number;
  indexed_percentage: number;
  vector_chunks_count: number;
  index_size_mb: number;
}

export interface SafraResponse {
  years: SafraYearStats[];
  throughput_docs_min: number;
  rag_percentage: number;
}

export interface SafraYearStats {
  year: number;
  sync_count: number;
  sync_total: number;
  index_count: number;
  index_total: number;
  rag_count: number;
  rag_total: number;
  status: 'completed' | 'active' | 'pending';
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  success: boolean;
  token: string | null;
  error: string | null;
  role: string | null;
}

export interface JobsResponse {
  jobs: Array<{
    id: string;
    type: string;
    status: string;
    progress: number;
    createdAt: string;
    updatedAt: string;
  }>;
}

export interface RefreshResponse {
  success: boolean;
  message: string;
}
