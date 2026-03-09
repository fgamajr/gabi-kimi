import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { workerApi } from "@/lib/workerApi";

const REFRESH_INTERVAL = 30_000;

export function useWorkerHealth() {
  return useQuery({
    queryKey: ["worker", "health"],
    queryFn: workerApi.getHealth,
    refetchInterval: REFRESH_INTERVAL,
  });
}

export function usePipelineStatus() {
  return useQuery({
    queryKey: ["pipeline", "status"],
    queryFn: workerApi.getRegistryStatus,
    refetchInterval: REFRESH_INTERVAL,
  });
}

export function usePipelineMonths(year?: number) {
  return useQuery({
    queryKey: ["pipeline", "months", year],
    queryFn: () => workerApi.getMonths(year),
    refetchInterval: REFRESH_INTERVAL,
  });
}

export function usePipelineRuns(limit = 50) {
  return useQuery({
    queryKey: ["pipeline", "runs", limit],
    queryFn: () => workerApi.getRuns(limit),
    refetchInterval: REFRESH_INTERVAL,
  });
}

export function usePipelineLogs(params: Parameters<typeof workerApi.getLogs>[0]) {
  return useQuery({
    queryKey: ["pipeline", "logs", params],
    queryFn: () => workerApi.getLogs(params),
    refetchInterval: REFRESH_INTERVAL,
  });
}

export function useFileDetail(fileId: number | null) {
  return useQuery({
    queryKey: ["pipeline", "file", fileId],
    queryFn: () => workerApi.getFile(fileId!),
    enabled: fileId !== null,
    refetchInterval: REFRESH_INTERVAL,
  });
}

export function useTriggerPipeline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: workerApi.triggerPhase,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pipeline"] }),
  });
}

export function useRetryFile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: workerApi.retryFile,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pipeline"] }),
  });
}

export function usePausePipeline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: workerApi.pause,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["worker"] }),
  });
}

export function useResumePipeline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: workerApi.resume,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["worker"] }),
  });
}
