import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { workerApi } from "@/lib/workerApi";

const REFRESH_INTERVAL = 30_000;
const DEFAULT_QUERY_OPTIONS = {
  refetchInterval: REFRESH_INTERVAL,
  retry: false,
} as const;

export function useWorkerHealth() {
  return useQuery({
    queryKey: ["worker", "health"],
    queryFn: workerApi.getHealth,
    ...DEFAULT_QUERY_OPTIONS,
  });
}

export function usePipelineStatus() {
  return useQuery({
    queryKey: ["pipeline", "status"],
    queryFn: workerApi.getRegistryStatus,
    ...DEFAULT_QUERY_OPTIONS,
  });
}

export function usePipelineStats() {
  return useQuery({
    queryKey: ["pipeline", "stats"],
    queryFn: workerApi.getRegistryStats,
    ...DEFAULT_QUERY_OPTIONS,
  });
}

export function usePipelineMonths(year?: number) {
  return useQuery({
    queryKey: ["pipeline", "months", year],
    queryFn: () => workerApi.getMonths(year),
    ...DEFAULT_QUERY_OPTIONS,
  });
}

export function useCatalogMonths(year?: number) {
  return useQuery({
    queryKey: ["pipeline", "catalog-months", year],
    queryFn: () => workerApi.getCatalogMonths(year),
    ...DEFAULT_QUERY_OPTIONS,
  });
}

export function useWatchdog() {
  return useQuery({
    queryKey: ["pipeline", "watchdog"],
    queryFn: workerApi.getWatchdog,
    ...DEFAULT_QUERY_OPTIONS,
  });
}

export function usePipelineRuns(limit = 50) {
  return useQuery({
    queryKey: ["pipeline", "runs", limit],
    queryFn: () => workerApi.getRuns(limit),
    ...DEFAULT_QUERY_OPTIONS,
  });
}

export function usePipelineScheduler() {
  return useQuery({
    queryKey: ["pipeline", "scheduler"],
    queryFn: workerApi.getScheduler,
    ...DEFAULT_QUERY_OPTIONS,
  });
}

export function usePipelineLogs(params: Parameters<typeof workerApi.getLogs>[0]) {
  return useQuery({
    queryKey: ["pipeline", "logs", params],
    queryFn: () => workerApi.getLogs(params),
    ...DEFAULT_QUERY_OPTIONS,
  });
}

export function useFileDetail(fileId: number | null) {
  return useQuery({
    queryKey: ["pipeline", "file", fileId],
    queryFn: () => workerApi.getFile(fileId!),
    enabled: fileId !== null,
    ...DEFAULT_QUERY_OPTIONS,
  });
}

export function useTriggerPipeline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: workerApi.triggerPhase,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline"] });
      qc.invalidateQueries({ queryKey: ["worker"] });
    },
  });
}

export function useRetryFile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: workerApi.retryFile,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline"] });
      qc.invalidateQueries({ queryKey: ["worker"] });
    },
  });
}

export function usePausePipeline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: workerApi.pause,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["worker"] });
      qc.invalidateQueries({ queryKey: ["pipeline"] });
    },
  });
}

export function useResumePipeline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: workerApi.resume,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["worker"] });
      qc.invalidateQueries({ queryKey: ["pipeline"] });
    },
  });
}
