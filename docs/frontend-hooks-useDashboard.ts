/**
 * GABI Dashboard React Query Hooks
 * 
 * Copy this file to: frontend/src/hooks/useDashboard.ts
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { dashboardApi } from '@/lib/api/dashboard';
import { sourcesApi } from '@/lib/api/sources';
import { toast } from 'sonner';

// Query keys for cache management
export const DASHBOARD_KEYS = {
  all: ['dashboard'] as const,
  stats: () => [...DASHBOARD_KEYS.all, 'stats'] as const,
  pipeline: () => [...DASHBOARD_KEYS.all, 'pipeline'] as const,
  activity: (params?: object) => [...DASHBOARD_KEYS.all, 'activity', params] as const,
  health: () => [...DASHBOARD_KEYS.all, 'health'] as const,
  sources: () => ['sources'] as const,
};

// ============================================================================
// Individual Queries
// ============================================================================

/**
 * Dashboard stats query
 * Refetches every 30 seconds
 */
export function useDashboardStats() {
  return useQuery({
    queryKey: DASHBOARD_KEYS.stats(),
    queryFn: dashboardApi.getStats,
    refetchInterval: 30000, // 30s
    staleTime: 15000,
    retry: 3,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
  });
}

/**
 * Pipeline status query
 * Refetches every 10 seconds when healthy, 30s when stalled
 */
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
    retry: 2,
  });
}

/**
 * Activity feed query
 * Refetches every minute
 */
export function useActivity(params?: { limit?: number }) {
  return useQuery({
    queryKey: DASHBOARD_KEYS.activity(params),
    queryFn: () => dashboardApi.getActivity(params),
    refetchInterval: 60000, // 1 minute
    staleTime: 30000,
  });
}

/**
 * System health query
 * Refetches every minute
 */
export function useHealth() {
  return useQuery({
    queryKey: DASHBOARD_KEYS.health(),
    queryFn: dashboardApi.getHealth,
    refetchInterval: 60000, // 1 minute
    staleTime: 30000,
  });
}

/**
 * Sources list query
 * Refetches every 30 seconds
 */
export function useSources() {
  return useQuery({
    queryKey: DASHBOARD_KEYS.sources(),
    queryFn: sourcesApi.listSources,
    refetchInterval: 30000,
    staleTime: 15000,
  });
}

// ============================================================================
// Mutations
// ============================================================================

/**
 * Trigger ingestion mutation (admin only)
 */
export function useTriggerIngestion() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: dashboardApi.triggerIngestion,
    onSuccess: (data) => {
      toast.success(data.message);
      // Invalidate relevant queries to refresh data
      queryClient.invalidateQueries({ queryKey: DASHBOARD_KEYS.stats() });
      queryClient.invalidateQueries({ queryKey: DASHBOARD_KEYS.pipeline() });
      queryClient.invalidateQueries({ queryKey: DASHBOARD_KEYS.activity() });
    },
    onError: (error: any) => {
      toast.error(`Failed to trigger ingestion: ${error.message}`);
    },
  });
}

/**
 * Sync source mutation
 */
export function useSyncSource() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ sourceId, mode }: { sourceId: string; mode: 'full' | 'incremental' }) =>
      sourcesApi.syncSource(sourceId, { mode }),
    onSuccess: (data) => {
      toast.success(data.message);
      queryClient.invalidateQueries({ queryKey: DASHBOARD_KEYS.sources() });
      queryClient.invalidateQueries({ queryKey: DASHBOARD_KEYS.stats() });
      queryClient.invalidateQueries({ queryKey: DASHBOARD_KEYS.pipeline() });
    },
    onError: (error: any) => {
      toast.error(`Sync failed: ${error.message}`);
    },
  });
}

// ============================================================================
// Combined Hook (Recommended for Dashboard page)
// ============================================================================

/**
 * Combined dashboard data hook
 * Returns all dashboard data with loading states
 */
export function useDashboardData() {
  const stats = useDashboardStats();
  const pipeline = usePipeline();
  const activity = useActivity({ limit: 50 });
  const health = useHealth();
  const sources = useSources();

  // Combined loading state
  const isLoading =
    stats.isLoading || 
    pipeline.isLoading || 
    activity.isLoading || 
    sources.isLoading;

  // Combined error state
  const isError = 
    stats.isError || 
    pipeline.isError || 
    activity.isError || 
    sources.isError;

  // Combined refreshing state (background refetch)
  const isRefreshing = 
    stats.isFetching || 
    pipeline.isFetching || 
    activity.isFetching;

  // Transform data for frontend components
  const frontendPipeline = pipeline.data
    ? dashboardApi.transformPipelineStages(pipeline.data)
    : [];

  const frontendJobs = activity.data
    ? dashboardApi.transformActivityToJobs(activity.data)
    : [];

  const elasticsearchAvailable = health.data
    ? dashboardApi.mapElasticsearchStatus(health.data)
    : false;

  return {
    // Raw data from API
    stats: stats.data,
    pipeline: pipeline.data,
    activity: activity.data,
    health: health.data,
    sources: sources.data,

    // Transformed data for components
    frontendPipeline,
    frontendJobs,
    elasticsearchAvailable,

    // Status flags
    isLoading,
    isError,
    isRefreshing,

    // Individual error states (for granular error handling)
    errors: {
      stats: stats.error,
      pipeline: pipeline.error,
      activity: activity.error,
      sources: sources.error,
      health: health.error,
    },

    // Refetch functions
    refetch: () => {
      stats.refetch();
      pipeline.refetch();
      activity.refetch();
      health.refetch();
      sources.refetch();
    },

    refetchStats: stats.refetch,
    refetchPipeline: pipeline.refetch,
    refetchActivity: activity.refetch,

    // Last update timestamp
    lastUpdate: stats.data?.generated_at || new Date().toISOString(),
  };
}
