/**
 * GABI Dashboard API
 * 
 * API functions and transformers for dashboard endpoints.
 * Copy this file to: frontend/src/lib/api/dashboard.ts
 */

import { apiClient } from './client';
import type {
  DashboardStatsResponse,
  DashboardPipelineResponse,
  DashboardActivityResponse,
  DashboardHealthResponse,
  TriggerIngestionResponse,
  FrontendPipelineStage,
  FrontendActivityJob,
} from './types';

// Map 9 backend pipeline stages to 4 frontend stages
const PIPELINE_STAGE_MAPPING: Record<string, string> = {
  discovery: 'harvest',
  change_detection: 'harvest',
  fetch: 'harvest',
  parse: 'sync',
  fingerprint: 'sync',
  deduplication: 'sync',
  chunking: 'ingest',
  embedding: 'ingest',
  indexing: 'index',
};

const STAGE_LABELS: Record<string, { label: string; description: string }> = {
  harvest: { label: 'Harvest', description: 'Download from sources' },
  sync: { label: 'Sync', description: 'PostgreSQL ingestion' },
  ingest: { label: 'Ingest', description: 'Document processing' },
  index: { label: 'Index', description: 'Elasticsearch indexing' },
};

/**
 * Dashboard API functions
 */
export const dashboardApi = {
  // GET /dashboard/stats
  getStats: async (): Promise<DashboardStatsResponse> => {
    const response = await apiClient.get<DashboardStatsResponse>('/dashboard/stats');
    return response.data;
  },

  // GET /dashboard/pipeline
  getPipeline: async (): Promise<DashboardPipelineResponse> => {
    const response = await apiClient.get<DashboardPipelineResponse>('/dashboard/pipeline');
    return response.data;
  },

  // GET /dashboard/activity
  getActivity: async (params?: {
    limit?: number;
    severity?: string;
    event_type?: string;
    source_id?: string;
  }): Promise<DashboardActivityResponse> => {
    const response = await apiClient.get<DashboardActivityResponse>('/dashboard/activity', {
      params,
    });
    return response.data;
  },

  // GET /dashboard/health
  getHealth: async (): Promise<DashboardHealthResponse> => {
    const response = await apiClient.get<DashboardHealthResponse>('/dashboard/health');
    return response.data;
  },

  // POST /dashboard/trigger-ingestion
  triggerIngestion: async (sourceId: string): Promise<TriggerIngestionResponse> => {
    const response = await apiClient.post<TriggerIngestionResponse>(
      '/dashboard/trigger-ingestion',
      null,
      { params: { source_id: sourceId } }
    );
    return response.data;
  },

  // ============================================================================
  // Transformers (Backend → Frontend format)
  // ============================================================================

  /**
   * Transform 9 backend pipeline stages to 4 frontend stages
   * Uses minimum count as bottleneck for each group
   */
  transformPipelineStages(backendData: DashboardPipelineResponse): FrontendPipelineStage[] {
    const { stages } = backendData;
    const total = stages[0]?.total || 0;

    // Group counts by frontend stage
    const grouped = new Map<string, number[]>();
    for (const stage of stages) {
      const frontendName = PIPELINE_STAGE_MAPPING[stage.name];
      if (!grouped.has(frontendName)) {
        grouped.set(frontendName, []);
      }
      grouped.get(frontendName)!.push(stage.count);
    }

    // Create frontend stages
    const frontendStages: FrontendPipelineStage[] = [];
    for (const [name, counts] of grouped) {
      const minCount = Math.min(...counts);
      const relatedBackendStages = stages.filter(
        (s) => PIPELINE_STAGE_MAPPING[s.name] === name
      );
      
      const hasActive = relatedBackendStages.some((s) => s.status === 'active');
      const hasError = relatedBackendStages.some((s) => s.status === 'error');
      
      // Get most recent activity timestamp
      const lastActivity = relatedBackendStages
        .map((s) => s.last_activity)
        .filter((t): t is string => !!t)
        .sort()
        .pop();

      frontendStages.push({
        name: name as FrontendPipelineStage['name'],
        label: STAGE_LABELS[name].label,
        description: STAGE_LABELS[name].description,
        count: minCount,
        total,
        status: hasError ? 'error' : hasActive ? 'active' : 'idle',
        lastActivity,
      });
    }

    // Ensure correct order
    const order = ['harvest', 'sync', 'ingest', 'index'];
    return order
      .map((name) => frontendStages.find((s) => s.name === name))
      .filter((s): s is FrontendPipelineStage => s !== undefined);
  },

  /**
   * Transform activity events to legacy job format
   */
  transformActivityToJobs(backendData: DashboardActivityResponse): FrontendActivityJob[] {
    return backendData.events.slice(0, 10).map((event) => ({
      source: event.source_id || 'system',
      year: new Date(event.timestamp).getFullYear(),
      status: mapEventToStatus(event.severity, event.event_type),
      updated_at: event.timestamp,
    }));
  },

  /**
   * Map component health to simple boolean
   */
  mapElasticsearchStatus(health: DashboardHealthResponse): boolean {
    const esComponent = health.components.find((c) => c.name === 'elasticsearch');
    return esComponent?.status === 'online';
  },
};

// Helper function to map event type/severity to job status
function mapEventToStatus(
  severity: string,
  eventType: string
): FrontendActivityJob['status'] {
  if (eventType.includes('FAILED') || severity === 'error' || severity === 'critical') {
    return 'failed';
  }
  if (eventType.includes('COMPLETED')) {
    return 'synced';
  }
  if (eventType.includes('STARTED')) {
    return 'in_progress';
  }
  return 'pending';
}
