import { useMemo } from "react";
import { Clock3, PlayCircle, RefreshCw, SearchCheck } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { usePipelineRuns, usePipelineScheduler, usePipelineStats, useTriggerPipeline, useWorkerHealth } from "@/hooks/usePipeline";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import WorkerUnavailableState from "./WorkerUnavailableState";

const FALLBACK_SCHEDULES: Record<string, string> = {
  discovery: "23:00 UTC",
  download: "23:30 UTC",
  extract: "23:45 UTC",
  bm25: "00:00 UTC",
  embed: "00:30 UTC",
  verify: "01:00 UTC",
  retry: "06:00 UTC",
  snapshot: "02:00 UTC",
  heartbeat: "a cada 60s",
};

function formatUptime(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function formatRelativeFuture(dateStr: string | null): string {
  if (!dateStr) return "sem agenda";
  const diff = new Date(dateStr).getTime() - Date.now();
  const minutes = Math.round(diff / 60000);
  if (minutes <= 0) return "agora";
  if (minutes < 60) return `em ${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const rem = minutes % 60;
  return rem > 0 ? `em ${hours}h ${rem}m` : `em ${hours}h`;
}

function formatDuration(startedAt: string, completedAt: string | null): string {
  const diff = Math.max(0, new Date(completedAt ?? new Date().toISOString()).getTime() - new Date(startedAt).getTime());
  const seconds = Math.round(diff / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rem = seconds % 60;
  return `${minutes}m ${rem}s`;
}

export default function PipelineScheduler() {
  const { data: health, isError: healthError, error: healthFailure } = useWorkerHealth();
  const { data: scheduler, isError: schedulerError, error: schedulerFailure } = usePipelineScheduler();
  const { data: runs, isError: runsError, error: runsFailure } = usePipelineRuns(20);
  const { data: stats } = usePipelineStats();
  const triggerMut = useTriggerPipeline();
  const [, setSearchParams] = useSearchParams();

  const schedulerJobs = useMemo(
    () => (scheduler?.jobs?.length ? scheduler.jobs : health?.scheduler_jobs?.length ? health.scheduler_jobs : []),
    [health?.scheduler_jobs, scheduler?.jobs]
  );

  const statusBadge = health?.scheduler_paused
    ? "bg-amber-500/10 text-amber-300"
    : health?.scheduler_running
      ? "bg-emerald-500/10 text-emerald-300"
      : "bg-red-500/10 text-red-300";
  const bootstrappedWithoutRealRuns = (stats?.total_files ?? 0) > 0 && !(runs?.length);

  const handleTrigger = async (phase: string) => {
    try {
      await triggerMut.mutateAsync(phase);
      toast.success(`Fase "${phase}" enviada ao scheduler.`);
    } catch (error) {
      toast.error(`Falha ao disparar ${phase}: ${(error as Error).message}`);
    }
  };

  if (healthError || schedulerError || runsError) {
    const message = [healthFailure, schedulerFailure, runsFailure].find(Boolean);
    return (
      <WorkerUnavailableState
        title="Scheduler indisponível"
        message={(message as Error | undefined)?.message}
      />
    );
  }

  return (
    <div className="space-y-6">
      <section className="grid gap-4 lg:grid-cols-[0.95fr_1.05fr]">
        <div className="rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-text-primary">Scheduler</h2>
              <p className="text-xs text-text-secondary">Loop contínuo do worker interno.</p>
            </div>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${statusBadge}`}>
              {health?.scheduler_paused ? "Paused" : health?.scheduler_running ? "Running" : "Stopped"}
            </span>
          </div>
          <dl className="grid gap-3 text-sm">
            <div className="flex items-center justify-between rounded-xl bg-background/40 px-4 py-3">
              <dt className="text-text-secondary">Uptime</dt>
              <dd className="font-medium text-text-primary">{formatUptime(health?.uptime_seconds ?? 0)}</dd>
            </div>
            <div className="flex items-center justify-between rounded-xl bg-background/40 px-4 py-3">
              <dt className="text-text-secondary">Último heartbeat</dt>
              <dd className="font-medium text-text-primary">{health?.last_heartbeat ?? "-"}</dd>
            </div>
          </dl>
          <div className="mt-4 flex flex-wrap gap-2">
            {["full", "discovery", "download", "extract", "bm25", "embed", "verify"].map((phase) => (
              <Button
                key={phase}
                variant="outline"
                size="sm"
                disabled={triggerMut.isPending}
                onClick={() => handleTrigger(phase)}
              >
                <PlayCircle className="h-3.5 w-3.5" />
                {phase === "full" ? "full cycle" : phase}
              </Button>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-text-primary">Próximas execuções</h2>
              <p className="text-xs text-text-secondary">Jobs agendados expostos pelo worker.</p>
            </div>
            <Clock3 className="h-4 w-4 text-primary" />
          </div>
          <div className="space-y-3">
            {schedulerJobs.map((job) => (
              <div key={job.id} className="flex items-center justify-between rounded-xl bg-background/40 px-4 py-3 text-sm">
                <div>
                  <p className="font-medium capitalize text-text-primary">{job.id}</p>
                  <p className="text-xs text-text-secondary">{FALLBACK_SCHEDULES[job.id] ?? "agendamento interno"}</p>
                </div>
                <div className="text-right">
                  <p className="font-medium text-text-primary">{formatRelativeFuture(job.next_run_time)}</p>
                  <p className="text-xs text-text-secondary">{job.next_run_time ?? "sem next_run_time"}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-text-primary">Histórico de execução</h2>
            <p className="text-xs text-text-secondary">Clique em uma execução para abrir o tab de logs filtrado.</p>
          </div>
          <RefreshCw className="h-4 w-4 text-primary" />
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Phase</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Started</TableHead>
              <TableHead>Duration</TableHead>
              <TableHead>Files</TableHead>
              <TableHead className="text-right">Logs</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {runs?.length ? runs.map((run) => (
              <TableRow key={run.id}>
                <TableCell className="font-medium capitalize text-text-primary">{run.phase}</TableCell>
                <TableCell>
                  <span className="rounded-full bg-muted px-2 py-1 text-[11px] uppercase tracking-wide text-text-secondary">
                    {run.status}
                  </span>
                </TableCell>
                <TableCell>{run.started_at}</TableCell>
                <TableCell>{formatDuration(run.started_at, run.completed_at)}</TableCell>
                <TableCell>{run.files_processed}/{run.files_succeeded}/{run.files_failed}</TableCell>
                <TableCell className="text-right">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setSearchParams({ tab: "logs", run: run.id })}
                  >
                    <SearchCheck className="h-3.5 w-3.5" />
                    Abrir
                  </Button>
                </TableCell>
              </TableRow>
            )) : (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-text-tertiary">
                  {bootstrappedWithoutRealRuns
                    ? "Catálogo já foi carregado no registry; ainda não houve execução real do pipeline."
                    : "Nenhuma execução encontrada."}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </section>
    </div>
  );
}
