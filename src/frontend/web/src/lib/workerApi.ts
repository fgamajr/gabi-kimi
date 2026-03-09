import type {
  HealthStatus,
  RegistryStatus,
  MonthData,
  FileRecord,
  PipelineRun,
  LogEntry,
} from "@/types/pipeline";

const BASE = "/api/worker";

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) throw new Error(`Worker API error: ${res.status}`);
  return res.json();
}

export const workerApi = {
  getHealth: () => fetchJson<HealthStatus>("/health"),
  getRegistryStatus: () => fetchJson<RegistryStatus>("/registry/status"),
  getMonths: (year?: number) =>
    fetchJson<MonthData[]>(`/registry/months${year ? `?year=${year}` : ""}`),
  getFile: (id: number) => fetchJson<FileRecord>(`/registry/files/${id}`),
  getRuns: (limit = 50) =>
    fetchJson<PipelineRun[]>(`/pipeline/runs?limit=${limit}`),
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
};
