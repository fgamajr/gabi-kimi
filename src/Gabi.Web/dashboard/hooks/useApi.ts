import { useState, useEffect, useCallback } from 'react';
import { api } from '../lib/api-client';

interface UseApiState<T> {
  data: T | null;
  isLoading: boolean;
  error: string | null;
}

interface UseApiReturn<T> extends UseApiState<T> {
  refetch: () => Promise<void>;
}

export function useApi<T>(
  fetchFn: () => Promise<T>,
  deps: React.DependencyList = []
): UseApiReturn<T> {
  const [state, setState] = useState<UseApiState<T>>({
    data: null,
    isLoading: true,
    error: null,
  });

  const fetchData = useCallback(async () => {
    setState(prev => ({ ...prev, isLoading: true, error: null }));

    try {
      const data = await fetchFn();
      setState({ data, isLoading: false, error: null });
    } catch (err) {
      setState({
        data: null,
        isLoading: false,
        error: err instanceof Error ? err.message : 'Unknown error',
      });
    }
  }, [fetchFn]);

  useEffect(() => {
    fetchData();
  }, deps);

  return {
    ...state,
    refetch: fetchData,
  };
}

// Hooks específicos para a API GABI
export function useDashboardStats() {
  return useApi(() => api.getStats(), []);
}

export function usePipeline() {
  return useApi(() => api.getPipeline(), []);
}

export function useJobs() {
  return useApi(() => api.getJobs(), []);
}

export function useSources() {
  return useApi(() => api.getSources(), []);
}

export function useSourceDetails(sourceId: string | null) {
  return useApi(
    () => (sourceId ? api.getSourceDetails(sourceId) : Promise.resolve(null)),
    [sourceId]
  );
}

export function useSourceLinks(
  sourceId: string | null,
  page: number = 1,
  pageSize: number = 20,
  status?: string
) {
  return useApi(
    () => (sourceId ? api.getSourceLinks(sourceId, page, pageSize, status) : Promise.resolve(null)),
    [sourceId, page, pageSize, status]
  );
}

export function useSafra(sourceId?: string) {
  return useApi(
    () => api.getSafra(sourceId),
    [sourceId]
  );
}
