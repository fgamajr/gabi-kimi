/**
 * GABI Sources API
 * 
 * Copy this file to: frontend/src/lib/api/sources.ts
 */

import { apiClient } from './client';
import type {
  SourceListResponse,
  SourceSyncRequest,
  SourceSyncResponse,
  DashboardSourceSummary,
} from './types';

// Extended source detail interface
export interface SourceDetail extends DashboardSourceSummary {
  config_hash: string;
  config_json: Record<string, unknown>;
  last_document_at?: string;
  last_error_message?: string;
  last_error_at?: string;
  retention_days: number;
  created_at: string;
  updated_at: string;
}

export interface SourceStatusResponse {
  source_id: string;
  status: string;
  is_healthy: boolean;
  document_count: number;
  last_success_at?: string;
  next_scheduled_sync?: string;
  consecutive_errors: number;
  success_rate: number;
  checked_at: string;
}

/**
 * Sources API functions
 */
export const sourcesApi = {
  // GET /sources
  listSources: async (params?: {
    status?: string;
    include_deleted?: boolean;
  }): Promise<SourceListResponse> => {
    const response = await apiClient.get<SourceListResponse>('/sources', { params });
    return response.data;
  },

  // GET /sources/:id
  getSource: async (sourceId: string): Promise<SourceDetail> => {
    const response = await apiClient.get<SourceDetail>(`/sources/${sourceId}`);
    return response.data;
  },

  // POST /sources/:id/sync
  syncSource: async (
    sourceId: string,
    request: SourceSyncRequest
  ): Promise<SourceSyncResponse> => {
    const response = await apiClient.post<SourceSyncResponse>(
      `/sources/${sourceId}/sync`,
      request
    );
    return response.data;
  },

  // GET /sources/:id/status
  getSourceStatus: async (sourceId: string): Promise<SourceStatusResponse> => {
    const response = await apiClient.get<SourceStatusResponse>(
      `/sources/${sourceId}/status`
    );
    return response.data;
  },

  // DELETE /sources/:id (soft delete)
  deleteSource: async (sourceId: string): Promise<void> => {
    await apiClient.delete(`/sources/${sourceId}`);
  },

  // PUT /sources/:id/enable
  enableSource: async (sourceId: string): Promise<void> => {
    await apiClient.put(`/sources/${sourceId}/enable`);
  },

  // PUT /sources/:id/disable
  disableSource: async (sourceId: string): Promise<void> => {
    await apiClient.put(`/sources/${sourceId}/disable`);
  },
};
