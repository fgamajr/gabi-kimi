/**
 * GABI Sources React Query Hooks
 * 
 * Copy this file to: frontend/src/hooks/useSources.ts
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { sourcesApi } from '@/lib/api/sources';
import { DASHBOARD_KEYS } from './useDashboard';
import { toast } from 'sonner';

// Query keys
const SOURCES_KEYS = {
  all: ['sources'] as const,
  list: (params?: object) => [...SOURCES_KEYS.all, 'list', params] as const,
  detail: (id: string) => [...SOURCES_KEYS.all, 'detail', id] as const,
  status: (id: string) => [...SOURCES_KEYS.all, 'status', id] as const,
};

/**
 * List all sources
 */
export function useSourcesList(params?: { status?: string; include_deleted?: boolean }) {
  return useQuery({
    queryKey: SOURCES_KEYS.list(params),
    queryFn: () => sourcesApi.listSources(params),
    refetchInterval: 30000,
    staleTime: 15000,
  });
}

/**
 * Get single source details
 */
export function useSource(sourceId: string) {
  return useQuery({
    queryKey: SOURCES_KEYS.detail(sourceId),
    queryFn: () => sourcesApi.getSource(sourceId),
    enabled: !!sourceId,
  });
}

/**
 * Get source status
 */
export function useSourceStatus(sourceId: string) {
  return useQuery({
    queryKey: SOURCES_KEYS.status(sourceId),
    queryFn: () => sourcesApi.getSourceStatus(sourceId),
    enabled: !!sourceId,
    refetchInterval: 10000, // Poll every 10s for active syncs
  });
}

/**
 * Sync source mutation
 */
export function useSyncSource() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      sourceId,
      mode,
      force,
    }: {
      sourceId: string;
      mode: 'full' | 'incremental';
      force?: boolean;
    }) => sourcesApi.syncSource(sourceId, { mode, force }),

    onMutate: async ({ sourceId }) => {
      // Cancel any outgoing refetches
      await queryClient.cancelQueries({ queryKey: SOURCES_KEYS.all });
      await queryClient.cancelQueries({ queryKey: DASHBOARD_KEYS.all });

      // Show optimistic toast
      toast.loading(`Starting sync for ${sourceId}...`);

      return { sourceId };
    },

    onSuccess: (data, variables) => {
      toast.dismiss();
      toast.success(`Sync started: ${data.message}`);

      // Invalidate queries to refresh data
      queryClient.invalidateQueries({ queryKey: SOURCES_KEYS.all });
      queryClient.invalidateQueries({ queryKey: DASHBOARD_KEYS.all });
    },

    onError: (error: any, variables) => {
      toast.dismiss();
      toast.error(`Sync failed for ${variables.sourceId}: ${error.message}`);
    },
  });
}

/**
 * Toggle source enabled status (optimistic update)
 */
export function useToggleSourceStatus() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      sourceId,
      enabled,
    }: {
      sourceId: string;
      enabled: boolean;
    }) => {
      // This would be a PUT/PATCH request in a full implementation
      // For now, we'll just invalidate the cache
      return { sourceId, enabled };
    },

    onMutate: async ({ sourceId, enabled }) => {
      await queryClient.cancelQueries({ queryKey: SOURCES_KEYS.all });

      // Snapshot previous value
      const previousSources = queryClient.getQueryData(SOURCES_KEYS.all);

      // Optimistically update
      queryClient.setQueryData(SOURCES_KEYS.all, (old: any) => {
        if (!old) return old;
        return {
          ...old,
          sources: old.sources.map((s: any) =>
            s.id === sourceId ? { ...s, enabled } : s
          ),
        };
      });

      return { previousSources };
    },

    onError: (err, variables, context) => {
      // Rollback on error
      if (context?.previousSources) {
        queryClient.setQueryData(SOURCES_KEYS.all, context.previousSources);
      }
      toast.error('Failed to update source status');
    },

    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: SOURCES_KEYS.all });
    },
  });
}
