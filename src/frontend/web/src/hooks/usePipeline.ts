import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { workerApi } from "@/lib/workerApi";

const REFRESH_INTERVAL = 30_000;
const FAST_QUERY_OPTIONS = {
  refetchInterval: REFRESH_INTERVAL,
  retry: false,
} as const;

const MEDIUM_QUERY_OPTIONS = {
  refetchInterval: 60_000,
  retry: false,
} as const;

const STATIC_QUERY_OPTIONS = {
  staleTime: 120_000,
  refetchInterval: false,
  retry: false,
} as const;

export function useWorkerHealth() {
  return useQuery({
    queryKey: ["worker", "health"],
    queryFn: workerApi.getHealth,
    ...FAST_QUERY_OPTIONS,
  });
}

export function usePipelineStatus() {
  return useQuery({
    queryKey: ["pipeline", "status"],
    queryFn: workerApi.getRegistryStatus,
    ...FAST_QUERY_OPTIONS,
  });
}

export function usePipelineStats() {
  return useQuery({
    queryKey: ["pipeline", "stats"],
    queryFn: workerApi.getRegistryStats,
    ...MEDIUM_QUERY_OPTIONS,
  });
}

export function usePipelineMonths(year?: number) {
  return useQuery({
    queryKey: ["pipeline", "months", year],
    queryFn: () => workerApi.getMonths(year),
    ...STATIC_QUERY_OPTIONS,
  });
}

export function useCatalogMonths(year?: number) {
  return useQuery({
    queryKey: ["pipeline", "catalog-months", year],
    queryFn: () => workerApi.getCatalogMonths(year),
    ...STATIC_QUERY_OPTIONS,
  });
}

export function useWatchdog() {
  return useQuery({
    queryKey: ["pipeline", "watchdog"],
    queryFn: workerApi.getWatchdog,
    ...MEDIUM_QUERY_OPTIONS,
  });
}

export function usePipelineRuns(limit = 50) {
  return useQuery({
    queryKey: ["pipeline", "runs", limit],
    queryFn: () => workerApi.getRuns(limit),
    ...FAST_QUERY_OPTIONS,
  });
}

export function usePipelineScheduler() {
  return useQuery({
    queryKey: ["pipeline", "scheduler"],
    queryFn: workerApi.getScheduler,
    ...FAST_QUERY_OPTIONS,
  });
}

export function usePipelineLogs(params: Parameters<typeof workerApi.getLogs>[0]) {
  return useQuery({
    queryKey: ["pipeline", "logs", params],
    queryFn: () => workerApi.getLogs(params),
    refetchInterval: 15_000,
    retry: false,
  });
}

export function useFileDetail(fileId: number | null) {
  return useQuery({
    queryKey: ["pipeline", "file", fileId],
    queryFn: () => workerApi.getFile(fileId!),
    enabled: fileId !== null,
    ...MEDIUM_QUERY_OPTIONS,
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

export function useSetPipelineJobEnabled() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, enabled }: { jobId: string; enabled: boolean }) =>
      workerApi.setJobEnabled(jobId, enabled),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["worker"] });
      qc.invalidateQueries({ queryKey: ["pipeline"] });
    },
  });
}

// --- Plant Status (SCADA Dashboard) ---

export function usePlantStatus() {
  return useQuery({
    queryKey: ["plant", "status"],
    queryFn: workerApi.getPlantStatus,
    refetchInterval: 15_000,
    retry: false,
  });
}

export function useStagePause() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: workerApi.stagePause,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plant"] });
      qc.invalidateQueries({ queryKey: ["pipeline"] });
    },
  });
}

export function useStageResume() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: workerApi.stageResume,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plant"] });
      qc.invalidateQueries({ queryKey: ["pipeline"] });
    },
  });
}

export function useStageTrigger() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: workerApi.stageTrigger,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plant"] });
      qc.invalidateQueries({ queryKey: ["pipeline"] });
    },
  });
}

export function usePauseAll() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: workerApi.pauseAll,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plant"] });
      qc.invalidateQueries({ queryKey: ["pipeline"] });
      qc.invalidateQueries({ queryKey: ["worker"] });
    },
  });
}

export function useResumeAll() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: workerApi.resumeAll,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plant"] });
      qc.invalidateQueries({ queryKey: ["pipeline"] });
      qc.invalidateQueries({ queryKey: ["worker"] });
    },
  });
}
