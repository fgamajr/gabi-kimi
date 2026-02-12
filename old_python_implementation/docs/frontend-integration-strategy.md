# GABI Frontend-Backend Integration Strategy

## Executive Summary

This document outlines the cleanest integration approach between the React frontend (`user-first-view`) and FastAPI backend (`gabi-kimi`) with minimal changes to existing components.

## 1. API Service Layer Structure

### Directory Structure
```
frontend/src/
├── lib/
│   ├── api/
│   │   ├── client.ts          # Axios instance with interceptors
│   │   ├── types.ts           # TypeScript interfaces matching backend schemas
│   │   ├── dashboard.ts       # Dashboard API endpoints
│   │   ├── sources.ts         # Sources API endpoints
│   │   └── index.ts           # Barrel exports
│   └── dashboard-data.ts      # Keep for formatters, remove mocks
├── hooks/
│   ├── useDashboard.ts        # React Query hooks for dashboard
│   ├── useSources.ts          # React Query hooks for sources
│   └── useRealtime.ts         # WebSocket/polling hook
└── components/
    └── error/
        ├── ErrorBoundary.tsx  # Global error boundary
        └── ApiErrorFallback.tsx
```

### 1.1 API Client (`lib/api/client.ts`)

```typescript
import axios, { AxiosError, AxiosInstance, InternalAxiosRequestConfig } from 'axios';
import { toast } from 'sonner';

// Environment configuration
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

// Custom error class for API errors
export class ApiError extends Error {
  constructor(
    public statusCode: number,
    public code: string,
    message: string,
    public requestId?: string
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

// Token management
class TokenManager {
  private token: string | null = null;

  getToken(): string | null {
    if (!this.token) {
      this.token = localStorage.getItem('gabi_access_token');
    }
    return this.token;
  }

  setToken(token: string): void {
    this.token = token;
    localStorage.setItem('gabi_access_token', token);
  }

  clearToken(): void {
    this.token = null;
    localStorage.removeItem('gabi_access_token');
  }
}

export const tokenManager = new TokenManager();

// Create axios instance
export const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor - add auth token
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = tokenManager.getToken();
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor - handle errors
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response) {
      const data = error.response.data as any;
      const apiError = new ApiError(
        error.response.status,
        data?.error?.code || 'UNKNOWN_ERROR',
        data?.error?.message || data?.message || 'An error occurred',
        data?.error?.request_id
      );

      // Handle specific error cases
      switch (error.response.status) {
        case 401:
          tokenManager.clearToken();
          window.location.href = '/login';
          break;
        case 403:
          toast.error('Permission denied');
          break;
        case 429:
          toast.error('Rate limit exceeded. Please try again later.');
          break;
        case 500:
          toast.error('Server error. Please try again later.');
          break;
      }

      return Promise.reject(apiError);
    }

    // Network errors
    if (error.code === 'ECONNABORTED') {
      toast.error('Request timeout. Please check your connection.');
    } else if (!error.response) {
      toast.error('Network error. Please check your connection.');
    }

    return Promise.reject(error);
  }
);
```

### 1.2 TypeScript Types (`lib/api/types.ts`)

```typescript
// Enums matching backend
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

// Dashboard Stats
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

// Pipeline
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

// Activity
export interface ActivityEvent {
  id: string;
  timestamp: string;
  event_type: string;
  severity: Severity;
  source_id?: string;
  description: string;
  details?: Record<string, any>;
  run_id?: string;
}

export interface DashboardActivityResponse {
  events: ActivityEvent[];
  total: number;
  has_more: boolean;
  generated_at: string;
}

// Health
export interface ComponentHealth {
  name: string;
  status: 'online' | 'degraded' | 'offline';
  latency_ms?: number;
  version?: string;
  details: Record<string, any>;
}

export interface DashboardHealthResponse {
  status: OverallStatus;
  uptime_seconds: number;
  components: ComponentHealth[];
  generated_at: string;
}

// Sources
export interface SourceListItem extends DashboardSourceSummary {}

export interface SourceListResponse {
  total: number;
  sources: SourceListItem[];
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

// Frontend-specific mapped types (for backward compatibility)
export interface FrontendPipelineStage {
  name: 'harvest' | 'sync' | 'ingest' | 'index';
  label: string;
  description: string;
  count: number;
  total: number;
  status: StageStatus;
  lastActivity?: string;
}

export interface FrontendActivityJob {
  source: string;
  year: number;
  status: 'synced' | 'pending' | 'failed' | 'in_progress';
  updated_at: string | null;
}
```

### 1.3 Dashboard API (`lib/api/dashboard.ts`)

```typescript
import { apiClient } from './client';
import {
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

  // Transformers for frontend compatibility
  transformPipelineStages(backendStages: DashboardPipelineResponse): FrontendPipelineStage[] {
    const grouped = new Map<string, number[]>();
    const total = backendStages.stages[0]?.total || 0;

    // Group counts by frontend stage
    for (const stage of backendStages.stages) {
      const frontendName = PIPELINE_STAGE_MAPPING[stage.name];
      if (!grouped.has(frontendName)) {
        grouped.set(frontendName, []);
      }
      grouped.get(frontendName)!.push(stage.count);
    }

    // Create frontend stages (use minimum count as the bottleneck)
    const frontendStages: FrontendPipelineStage[] = [];
    for (const [name, counts] of grouped) {
      const minCount = Math.min(...counts);
      const relatedBackendStages = backendStages.stages.filter(
        (s) => PIPELINE_STAGE_MAPPING[s.name] === name
      );
      const hasActive = relatedBackendStages.some((s) => s.status === 'active');
      const hasError = relatedBackendStages.some((s) => s.status === 'error');
      const lastActivity = relatedBackendStages
        .map((s) => s.last_activity)
        .filter(Boolean)
        .sort()
        .pop();

      frontendStages.push({
        name: name as FrontendPipelineStage['name'],
        label: STAGE_LABELS[name].label,
        description: STAGE_LABELS[name].description,
        count: minCount,
        total,
        status: hasError ? 'error' : hasActive ? 'active' : 'idle',
        lastActivity: lastActivity || undefined,
      });
    }

    // Ensure correct order
    const order = ['harvest', 'sync', 'ingest', 'index'];
    return order
      .map((name) => frontendStages.find((s) => s.name === name))
      .filter((s): s is FrontendPipelineStage => s !== undefined);
  },

  // Transform activity events to jobs format
  transformActivityToJobs(events: DashboardActivityResponse): FrontendActivityJob[] {
    return events.events.slice(0, 10).map((event) => ({
      source: event.source_id || 'system',
      year: new Date(event.timestamp).getFullYear(),
      status: this.mapSeverityToStatus(event.severity, event.event_type),
      updated_at: event.timestamp,
    }));
  },

  mapSeverityToStatus(severity: string, eventType: string): FrontendActivityJob['status'] {
    if (eventType.includes('FAILED')) return 'failed';
    if (eventType.includes('COMPLETED')) return 'synced';
    if (eventType.includes('STARTED')) return 'in_progress';
    if (severity === 'error' || severity === 'critical') return 'failed';
    return 'pending';
  },
};
```

### 1.4 Sources API (`lib/api/sources.ts`)

```typescript
import { apiClient } from './client';
import { SourceListResponse, SourceSyncRequest, SourceSyncResponse } from './types';

export const sourcesApi = {
  // GET /sources
  listSources: async (params?: {
    status?: string;
    include_deleted?: boolean;
  }): Promise<SourceListResponse> => {
    const response = await apiClient.get<SourceListResponse>('/sources', { params });
    return response.data;
  },

  // POST /sources/:id/sync
  syncSource: async (sourceId: string, request: SourceSyncRequest): Promise<SourceSyncResponse> => {
    const response = await apiClient.post<SourceSyncResponse>(`/sources/${sourceId}/sync`, request);
    return response.data;
  },

  // GET /sources/:id/status
  getSourceStatus: async (sourceId: string) => {
    const response = await apiClient.get(`/sources/${sourceId}/status`);
    return response.data;
  },
};
```

## 2. React Query Hooks

### 2.1 Dashboard Hooks (`hooks/useDashboard.ts`)

```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { dashboardApi } from '@/lib/api/dashboard';
import { sourcesApi } from '@/lib/api/sources';
import { toast } from 'sonner';

const DASHBOARD_KEYS = {
  all: ['dashboard'] as const,
  stats: () => [...DASHBOARD_KEYS.all, 'stats'] as const,
  pipeline: () => [...DASHBOARD_KEYS.all, 'pipeline'] as const,
  activity: (params?: object) => [...DASHBOARD_KEYS.all, 'activity', params] as const,
  health: () => [...DASHBOARD_KEYS.all, 'health'] as const,
  sources: () => ['sources'] as const,
};

// Stats query - refetch every 30 seconds
export function useDashboardStats() {
  return useQuery({
    queryKey: DASHBOARD_KEYS.stats(),
    queryFn: dashboardApi.getStats,
    refetchInterval: 30000, // 30s
    staleTime: 15000,
    retry: 3,
  });
}

// Pipeline query - refetch every 10 seconds when active
export function usePipeline() {
  return useQuery({
    queryKey: DASHBOARD_KEYS.pipeline(),
    queryFn: dashboardApi.getPipeline,
    refetchInterval: (query) => {
      const data = query.state.data;
      // Poll faster when pipeline is active
      if (data?.overall_status === 'healthy') return 10000; // 10s
      return 30000; // 30s when stalled
    },
    staleTime: 5000,
  });
}

// Activity query
export function useActivity(params?: { limit?: number }) {
  return useQuery({
    queryKey: DASHBOARD_KEYS.activity(params),
    queryFn: () => dashboardApi.getActivity(params),
    refetchInterval: 60000, // 1 minute
  });
}

// Health query - less frequent
export function useHealth() {
  return useQuery({
    queryKey: DASHBOARD_KEYS.health(),
    queryFn: dashboardApi.getHealth,
    refetchInterval: 60000, // 1 minute
    staleTime: 30000,
  });
}

// Sources query
export function useSources() {
  return useQuery({
    queryKey: DASHBOARD_KEYS.sources(),
    queryFn: sourcesApi.listSources,
    refetchInterval: 30000,
  });
}

// Trigger ingestion mutation
export function useTriggerIngestion() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: dashboardApi.triggerIngestion,
    onSuccess: (data) => {
      toast.success(data.message);
      // Invalidate relevant queries
      queryClient.invalidateQueries({ queryKey: DASHBOARD_KEYS.stats() });
      queryClient.invalidateQueries({ queryKey: DASHBOARD_KEYS.pipeline() });
      queryClient.invalidateQueries({ queryKey: DASHBOARD_KEYS.activity() });
    },
    onError: (error: any) => {
      toast.error(`Failed to trigger ingestion: ${error.message}`);
    },
  });
}

// Sync source mutation
export function useSyncSource() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ sourceId, mode }: { sourceId: string; mode: 'full' | 'incremental' }) =>
      sourcesApi.syncSource(sourceId, { mode }),
    onSuccess: (data) => {
      toast.success(data.message);
      queryClient.invalidateQueries({ queryKey: DASHBOARD_KEYS.sources() });
      queryClient.invalidateQueries({ queryKey: DASHBOARD_KEYS.stats() });
    },
    onError: (error: any) => {
      toast.error(`Sync failed: ${error.message}`);
    },
  });
}

// Combined hook for dashboard data
export function useDashboardData() {
  const stats = useDashboardStats();
  const pipeline = usePipeline();
  const activity = useActivity({ limit: 50 });
  const health = useHealth();
  const sources = useSources();

  const isLoading =
    stats.isLoading || pipeline.isLoading || activity.isLoading || sources.isLoading;
  const isError = stats.isError || pipeline.isError || activity.isError || sources.isError;

  // Transform data for components
  const transformedPipeline = pipeline.data
    ? dashboardApi.transformPipelineStages(pipeline.data)
    : [];

  const transformedJobs = activity.data
    ? dashboardApi.transformActivityToJobs(activity.data)
    : [];

  return {
    // Raw data
    stats: stats.data,
    pipeline: pipeline.data,
    activity: activity.data,
    health: health.data,
    sources: sources.data,

    // Transformed data for components
    frontendPipeline: transformedPipeline,
    frontendJobs: transformedJobs,

    // Status
    isLoading,
    isError,
    isRefreshing: stats.isFetching || pipeline.isFetching,

    // Refetch functions
    refetch: () => {
      stats.refetch();
      pipeline.refetch();
      activity.refetch();
      health.refetch();
      sources.refetch();
    },

    // Last update timestamp
    lastUpdate: stats.data?.generated_at || new Date().toISOString(),
  };
}
```

## 3. Real-time Updates Strategy

### 3.1 Polling Approach (Recommended for MVP)

```typescript
// hooks/useRealtime.ts
import { useEffect, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';

interface UsePollingOptions {
  interval?: number;
  enabled?: boolean;
  onData?: (data: any) => void;
}

export function usePolling(
  queryKey: string[],
  fetchFn: () => Promise<any>,
  options: UsePollingOptions = {}
) {
  const { interval = 10000, enabled = true, onData } = options;
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!enabled) return;

    const poll = async () => {
      try {
        const data = await fetchFn();
        queryClient.setQueryData(queryKey, data);
        onData?.(data);
      } catch (error) {
        console.error('Polling error:', error);
      }
    };

    const id = setInterval(poll, interval);
    return () => clearInterval(id);
  }, [queryKey, fetchFn, interval, enabled, onData, queryClient]);
}

// Optimistic polling based on pipeline state
export function useAdaptivePolling() {
  const queryClient = useQueryClient();

  const startAdaptivePolling = useCallback(() => {
    let currentInterval = 10000; // Start with 10s

    const poll = async () => {
      try {
        // Fetch pipeline status
        const response = await fetch('/api/v1/dashboard/pipeline');
        const data = await response.json();

        // Update cache
        queryClient.setQueryData(['dashboard', 'pipeline'], data);

        // Adjust interval based on activity
        const isActive = data.overall_status === 'healthy';
        const targetInterval = isActive ? 5000 : 30000;

        // Smooth transition
        currentInterval = currentInterval * 0.8 + targetInterval * 0.2;

        setTimeout(poll, currentInterval);
      } catch (error) {
        // Back off on error
        setTimeout(poll, Math.min(currentInterval * 2, 60000));
      }
    };

    poll();
  }, [queryClient]);

  return { startAdaptivePolling };
}
```

### 3.2 WebSocket Approach (Future Enhancement)

```typescript
// hooks/useWebSocket.ts
import { useEffect, useRef, useState, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';

interface WebSocketMessage {
  type: 'pipeline_update' | 'activity_event' | 'stats_update' | 'health_update';
  data: any;
  timestamp: string;
}

export function useDashboardWebSocket(enabled: boolean = true) {
  const ws = useRef<WebSocket | null>(null);
  const queryClient = useQueryClient();
  const [isConnected, setIsConnected] = useState(false);
  const reconnectTimeout = useRef<NodeJS.Timeout>();

  const connect = useCallback(() => {
    const wsUrl = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws/dashboard';

    ws.current = new WebSocket(wsUrl);

    ws.current.onopen = () => {
      setIsConnected(true);
      console.log('WebSocket connected');
    };

    ws.current.onmessage = (event) => {
      try {
        const message: WebSocketMessage = JSON.parse(event.data);

        switch (message.type) {
          case 'pipeline_update':
            queryClient.setQueryData(['dashboard', 'pipeline'], message.data);
            break;
          case 'stats_update':
            queryClient.setQueryData(['dashboard', 'stats'], message.data);
            break;
          case 'activity_event':
            // Append to activity list
            queryClient.setQueryData(['dashboard', 'activity'], (old: any) => {
              if (!old) return { events: [message.data], total: 1, has_more: false };
              return {
                ...old,
                events: [message.data, ...old.events].slice(0, 50),
                total: old.total + 1,
              };
            });
            break;
          case 'health_update':
            queryClient.setQueryData(['dashboard', 'health'], message.data);
            break;
        }
      } catch (error) {
        console.error('WebSocket message error:', error);
      }
    };

    ws.current.onclose = () => {
      setIsConnected(false);
      // Reconnect after 5 seconds
      reconnectTimeout.current = setTimeout(connect, 5000);
    };

    ws.current.onerror = (error) => {
      console.error('WebSocket error:', error);
    };
  }, [queryClient]);

  useEffect(() => {
    if (enabled) {
      connect();
    }

    return () => {
      if (reconnectTimeout.current) {
        clearTimeout(reconnectTimeout.current);
      }
      ws.current?.close();
    };
  }, [enabled, connect]);

  return { isConnected };
}
```

## 4. Error Boundaries and Loading States

### 4.1 Global Error Boundary

```typescript
// components/error/ErrorBoundary.tsx
import React, { Component, ErrorInfo, ReactNode } from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught error:', error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      return (
        this.props.fallback || (
          <div className="min-h-screen flex items-center justify-center p-4">
            <div className="max-w-md w-full space-y-4 text-center">
              <div className="flex justify-center">
                <div className="w-16 h-16 rounded-full bg-destructive/10 flex items-center justify-center">
                  <AlertCircle className="h-8 w-8 text-destructive" />
                </div>
              </div>
              <h1 className="text-xl font-semibold">Something went wrong</h1>
              <p className="text-muted-foreground text-sm">
                {this.state.error?.message || 'An unexpected error occurred'}
              </p>
              <Button
                onClick={() => window.location.reload()}
                className="gap-2"
              >
                <RefreshCw className="h-4 w-4" />
                Reload Page
              </Button>
            </div>
          </div>
        )
      );
    }

    return this.props.children;
  }
}
```

### 4.2 API Error Fallback Component

```typescript
// components/error/ApiErrorFallback.tsx
import { AlertCircle, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface ApiErrorFallbackProps {
  error: Error;
  reset: () => void;
  title?: string;
}

export function ApiErrorFallback({
  error,
  reset,
  title = 'Failed to load data',
}: ApiErrorFallbackProps) {
  const isAuthError = error.message?.includes('401') || error.message?.includes('Unauthorized');

  return (
    <div className="rounded-xl border border-destructive/20 bg-destructive/5 p-6">
      <div className="flex items-start gap-4">
        <div className="w-10 h-10 rounded-full bg-destructive/10 flex items-center justify-center shrink-0">
          <AlertCircle className="h-5 w-5 text-destructive" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="font-medium text-destructive">{title}</h3>
          <p className="text-sm text-muted-foreground mt-1">
            {isAuthError
              ? 'Your session has expired. Please log in again.'
              : error.message || 'An error occurred while fetching data'}
          </p>
          <div className="mt-4 flex gap-2">
            {!isAuthError && (
              <Button onClick={reset} variant="outline" size="sm" className="gap-2">
                <RefreshCw className="h-4 w-4" />
                Try Again
              </Button>
            )}
            {isAuthError && (
              <Button onClick={() => (window.location.href = '/login')} size="sm">
                Log In
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
```

### 4.3 Loading Skeletons

```typescript
// components/loading/DashboardSkeleton.tsx
import { Skeleton } from '@/components/ui/skeleton';

export function DashboardSkeleton() {
  return (
    <div className="p-6 space-y-6">
      {/* Metrics row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="rounded-xl border bg-card p-5 space-y-4">
            <Skeleton className="h-10 w-10 rounded-lg" />
            <Skeleton className="h-8 w-24" />
            <Skeleton className="h-4 w-32" />
          </div>
        ))}
      </div>

      {/* Pipeline */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="rounded-xl border bg-card p-5 space-y-4">
            <div className="flex items-center gap-3">
              <Skeleton className="h-10 w-10 rounded-lg" />
              <div className="space-y-2">
                <Skeleton className="h-4 w-20" />
                <Skeleton className="h-3 w-32" />
              </div>
            </div>
            <Skeleton className="h-8 w-20" />
            <Skeleton className="h-2 w-full" />
          </div>
        ))}
      </div>

      {/* Bottom section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1 rounded-xl border bg-card p-5 space-y-4">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="flex items-center gap-3">
              <Skeleton className="h-8 w-8 rounded-full" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-3 w-20" />
              </div>
            </div>
          ))}
        </div>
        <div className="lg:col-span-2 rounded-xl border bg-card p-5">
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    </div>
  );
}
```

## 5. Updated Dashboard Component

```typescript
// pages/Dashboard.tsx (minimal changes)
import { useDashboardData, useTriggerIngestion } from '@/hooks/useDashboard';
import { DashboardSkeleton } from '@/components/loading/DashboardSkeleton';
import { ApiErrorFallback } from '@/components/error/ApiErrorFallback';
import { PipelineOverview } from '@/components/dashboard/PipelineOverview';
import { MetricCard } from '@/components/dashboard/MetricCard';
import { ActivityFeed } from '@/components/dashboard/ActivityFeed';
import { SourcesTable } from '@/components/dashboard/SourcesTable';
import { SystemHealth } from '@/components/dashboard/SystemHealth';
import { formatNumber } from '@/lib/dashboard-data';

export default function Dashboard() {
  const {
    stats,
    frontendPipeline,
    frontendJobs,
    sources,
    isLoading,
    isError,
    isRefreshing,
    refetch,
    lastUpdate,
  } = useDashboardData();

  if (isLoading) {
    return <DashboardSkeleton />;
  }

  if (isError) {
    return (
      <ApiErrorFallback
        error={new Error('Failed to load dashboard data')}
        reset={refetch}
      />
    );
  }

  // Calculate metrics from real data
  const activeSources = stats?.active_sources || 0;
  const totalDocs = stats?.total_documents || 0;
  const indexedDocs = stats?.total_elastic_docs || 0;

  return (
    <div className="min-h-screen flex bg-background">
      {/* ... sidebar stays the same ... */}

      <main className="flex-1 min-h-screen ml-60">
        <header className="sticky top-0 z-40 bg-background/80 backdrop-blur-sm border-b">
          <div className="flex items-center justify-between px-6 h-16">
            <div>
              <h1 className="text-xl font-semibold text-foreground">Dashboard</h1>
              <p className="text-sm text-muted-foreground">
                Monitor your document processing pipeline
              </p>
            </div>
            <SystemHealth
              elasticsearch={stats?.elasticsearch_available ?? false}
              lastUpdate={lastUpdate}
              isRefreshing={isRefreshing}
              onRefresh={refetch}
            />
          </div>
        </header>

        <div className="p-6 space-y-6">
          {/* Metrics */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard
              title="Total Documents"
              value={formatNumber(totalDocs)}
              subtitle={`${totalDocs.toLocaleString('pt-BR')} total`}
              icon={Files}
              variant="primary"
            />
            <MetricCard
              title="Indexed Documents"
              value={formatNumber(indexedDocs)}
              subtitle="in Elasticsearch"
              icon={Search}
              variant="success"
            />
            <MetricCard
              title="Active Sources"
              value={activeSources}
              subtitle={`of ${stats?.sources.length || 0} configured`}
              icon={Database}
              variant="default"
            />
            <MetricCard
              title="Documents (24h)"
              value={formatNumber(stats?.documents_last_24h || 0)}
              subtitle="newly ingested"
              icon={Activity}
              variant="default"
            />
          </div>

          {/* Pipeline */}
          <PipelineOverview stages={frontendPipeline} />

          {/* Activity + Sources */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-1">
              <ActivityFeed jobs={frontendJobs} />
            </div>
            <div className="lg:col-span-2">
              <SourcesTable sources={stats?.sources || []} />
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
```

## 6. FastAPI CORS and Auth Configuration

### 6.1 Environment Variables (`.env`)

```bash
# API Configuration
GABI_API_HOST=0.0.0.0
GABI_API_PORT=8000

# CORS Configuration
GABI_CORS_ORIGINS=http://localhost:3000,http://localhost:5173,https://gabi.tcu.gov.br
GABI_CORS_ALLOW_CREDENTIALS=true
GABI_CORS_ALLOW_METHODS=GET,POST,PUT,DELETE,OPTIONS
GABI_CORS_ALLOW_HEADERS=Authorization,Content-Type,X-Request-ID,X-Requested-With

# Auth Configuration
GABI_AUTH_ENABLED=true
GABI_JWT_ISSUER=https://auth.tcu.gov.br/realms/tcu
GABI_JWT_AUDIENCE=gabi-api
GABI_JWT_JWKS_URL=https://auth.tcu.gov.br/realms/tcu/protocol/openid-connect/certs

# Public paths (no auth required)
GABI_AUTH_PUBLIC_PATHS=/health,/health/live,/health/ready,/docs,/openapi.json,/metrics
```

### 6.2 CORS Validation for Production

The backend already validates CORS configuration in production (see `config.py` lines 215-224):

```python
@model_validator(mode="after")
def validate_cors_in_production(self):
    """Valida configurações CORS em produção."""
    if self.environment == Environment.PRODUCTION:
        origins = self.cors_origins_list
        if "*" in origins:
            raise ValueError("CORS wildcard not allowed in production")
        if any("http://" in origin for origin in origins):
            raise ValueError("HTTP origins not allowed in production (use HTTPS)")
    return self
```

### 6.3 WebSocket Configuration (Future)

```python
# Add to main.py for WebSocket support
from fastapi import WebSocket, WebSocketDisconnect

@app.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # Send updates every 10 seconds
            stats = await get_dashboard_stats_cached()
            await websocket.send_json({
                "type": "stats_update",
                "data": stats,
                "timestamp": datetime.utcnow().isoformat()
            })
            await asyncio.sleep(10)
    except WebSocketDisconnect:
        pass
```

## 7. Implementation Checklist

### Phase 1: API Layer (Day 1)
- [ ] Install `axios` in frontend
- [ ] Create `lib/api/client.ts` with interceptors
- [ ] Create `lib/api/types.ts` matching backend schemas
- [ ] Create `lib/api/dashboard.ts` and `lib/api/sources.ts`

### Phase 2: React Query Hooks (Day 1-2)
- [ ] Create `hooks/useDashboard.ts` with all queries
- [ ] Create `hooks/useRealtime.ts` for polling
- [ ] Update `App.tsx` QueryClient configuration

### Phase 3: Component Updates (Day 2)
- [ ] Update `Dashboard.tsx` to use hooks
- [ ] Create loading skeletons
- [ ] Create error boundaries
- [ ] Test all data transformations

### Phase 4: Backend CORS (Day 2)
- [ ] Update `.env` with frontend origin
- [ ] Test CORS preflight requests
- [ ] Verify auth token flow

### Phase 5: Polish (Day 3)
- [ ] Add toast notifications for mutations
- [ ] Implement optimistic updates
- [ ] Add retry logic
- [ ] Performance testing

## 8. Minimal Changes Summary

### Files to Create (New)
- `src/lib/api/client.ts`
- `src/lib/api/types.ts`
- `src/lib/api/dashboard.ts`
- `src/lib/api/sources.ts`
- `src/hooks/useDashboard.ts`
- `src/hooks/useRealtime.ts`
- `src/components/error/ErrorBoundary.tsx`
- `src/components/error/ApiErrorFallback.tsx`
- `src/components/loading/DashboardSkeleton.tsx`

### Files to Modify (Minimal)
- `src/App.tsx` - Update QueryClient config
- `src/pages/Dashboard.tsx` - Replace mock data with hooks
- `src/lib/dashboard-data.ts` - Remove mocks, keep formatters

### Backend Changes (None Required)
- CORS already configured in `main.py`
- Auth middleware already in place
- All dashboard endpoints exist

## 9. Security Considerations

1. **Token Storage**: Use `localStorage` for access tokens (backend validates via Keycloak)
2. **CORS**: Strict origin validation in production (no wildcards)
3. **Rate Limiting**: Backend already has rate limiting middleware
4. **HTTPS**: Required in production for all origins
5. **Auth Headers**: Always sent with `Authorization: Bearer <token>`

---

**Note**: This integration strategy prioritizes:
1. Minimal changes to existing UI components
2. Type safety with full TypeScript coverage
3. Clean separation of concerns (API layer, hooks, components)
4. Graceful error handling and loading states
5. Efficient polling for real-time updates
