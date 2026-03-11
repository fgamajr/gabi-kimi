import type {
  HealthStatus,
  RegistryStatus,
  MonthData,
  RegistryStats,
  SchedulerStatus,
  FileRecord,
  PipelineRun,
  LogEntry,
  CatalogMonth,
  WatchdogStatus,
  PlantStatus,
} from "@/types/pipeline";
import { resolveApiUrl } from "@/lib/runtimeConfig";

const BASE = resolveApiUrl("/api/worker");

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    ...init,
  });
  if (!res.ok) {
    let detail = `Worker API error: ${res.status}`;
    try {
      const text = await res.text();
      if (text) {
        try {
          const payload = JSON.parse(text) as { error?: string; detail?: string };
          detail = payload.detail || payload.error || text;
        } catch {
          detail = text;
        }
      }
    } catch {
      // Ignore body parsing failures and keep the status-only error.
    }
    throw new Error(detail);
  }
  return res.json();
}

export const workerApi = {
  getHealth: () => fetchJson<HealthStatus>("/health"),
  getRegistryStatus: () => fetchJson<RegistryStatus>("/registry/status"),
  getRegistryStats: () => fetchJson<RegistryStats>("/registry/stats"),
  getMonths: (year?: number) =>
    fetchJson<MonthData[]>(`/registry/months${year ? `?year=${year}` : ""}`),
  getCatalogMonths: (year?: number) =>
    fetchJson<CatalogMonth[]>(`/registry/catalog-months${year ? `?year=${year}` : ""}`),
  getFile: (id: number) => fetchJson<FileRecord>(`/registry/files/${id}`),
  getRuns: (limit = 50) =>
    fetchJson<PipelineRun[]>(`/pipeline/runs?limit=${limit}`),
  getScheduler: () => fetchJson<SchedulerStatus>("/pipeline/scheduler"),
  getWatchdog: () => fetchJson<WatchdogStatus>("/pipeline/watchdog"),
  getLogs: (params: {
    run_id?: string;
    file_id?: number;
    level?: string;
    limit?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params.run_id) qs.set("run_id", params.run_id);
    if (params.file_id) qs.set("file_id", String(params.file_id));
    if (params.level) qs.set("level", params.level);
    if (params.limit) qs.set("limit", String(params.limit));
    return fetchJson<LogEntry[]>(`/pipeline/logs?${qs}`);
  },
  triggerPhase: (phase: string) =>
    fetchJson<{ triggered: string }>(`/pipeline/trigger/${phase}`, {
      method: "POST",
    }),
  retryFile: (fileId: number) =>
    fetchJson<{ retried: number }>(`/pipeline/retry/${fileId}`, {
      method: "POST",
    }),
  pause: () =>
    fetchJson<{ paused: boolean }>("/pipeline/pause", { method: "POST" }),
  resume: () =>
    fetchJson<{ paused: boolean }>("/pipeline/resume", { method: "POST" }),
  setJobEnabled: (jobId: string, enabled: boolean) =>
    fetchJson<{ job_id: string; enabled: boolean }>(
      `/pipeline/jobs/${jobId}/${enabled ? "enable" : "disable"}`,
      { method: "POST" }
    ),

  // Plant Status (SCADA Dashboard)
  getPlantStatus: () => fetchJson<PlantStatus>("/registry/plant-status"),
  stagePause: (name: string) =>
    fetchJson<{ job_id: string; enabled: boolean }>(
      `/pipeline/stage/${name}/pause`,
      { method: "POST" }
    ),
  stageResume: (name: string) =>
    fetchJson<{ job_id: string; enabled: boolean }>(
      `/pipeline/stage/${name}/resume`,
      { method: "POST" }
    ),
  stageTrigger: (name: string) =>
    fetchJson<{ triggered: string }>(
      `/pipeline/stage/${name}/trigger`,
      { method: "POST" }
    ),
  pauseAll: () =>
    fetchJson<{ paused: boolean }>("/pipeline/pause-all", { method: "POST" }),
  resumeAll: () =>
    fetchJson<{ paused: boolean }>("/pipeline/resume-all", { method: "POST" }),
};
