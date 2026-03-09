import { useState } from "react";
import {
  useWorkerHealth,
  usePipelineRuns,
  useTriggerPipeline,
} from "@/hooks/usePipeline";
import type { PipelineRun } from "@/types/pipeline";
import { toast } from "sonner";
import {
  Play,
  Pause,
  CircleOff,
  Rocket,
  Clock,
  Timer,
} from "lucide-react";
import { cn } from "@/lib/utils";

const SCHEDULE = [
  { phase: "discovery", label: "Discovery", cron: "23:00 UTC", icon: "🔍" },
  { phase: "download", label: "Download", cron: "23:30 UTC", icon: "⬇️" },
  { phase: "ingest", label: "Ingest", cron: "00:00 UTC", icon: "📥" },
  { phase: "verify", label: "Verify", cron: "01:00 UTC", icon: "✅" },
  { phase: "retry", label: "Retry", cron: "06:00 UTC", icon: "🔄" },
];

const TRIGGER_PHASES = ["discovery", "download", "extract", "ingest", "verify"];

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  if (days > 0) return `${days}d ${hours}h`;
  const mins = Math.floor((seconds % 3600) / 60);
  return hours > 0 ? `${hours}h ${mins}m` : `${mins}m`;
}

function formatDuration(startedAt: string, completedAt: string | null): string {
  const start = new Date(startedAt).getTime();
  const end = completedAt ? new Date(completedAt).getTime() : Date.now();
  const seconds = Math.round((end - start) / 1000);
  if (seconds < 60) return `${seconds}s`;
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}m ${secs}s`;
}

function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function nextRunRelative(cronUtcHour: string): string {
  const [h, m] = cronUtcHour.split(":").map(Number);
  const now = new Date();
  const next = new Date(now);
  next.setUTCHours(h, m, 0, 0);
  if (next <= now) next.setUTCDate(next.getUTCDate() + 1);
  const diffMs = next.getTime() - now.getTime();
  const diffH = Math.floor(diffMs / 3_600_000);
  const diffM = Math.floor((diffMs % 3_600_000) / 60_000);
  if (diffH > 0) return `in ${diffH}h ${diffM}m`;
  return `in ${diffM}m`;
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full",
        status === "completed" && "bg-emerald-500/15 text-emerald-400",
        status === "failed" && "bg-red-500/15 text-red-400",
        status === "running" && "bg-yellow-500/15 text-yellow-400 animate-pulse"
      )}
    >
      {status}
    </span>
  );
}

export default function PipelineScheduler() {
  const { data: health } = useWorkerHealth();
  const { data: runs, isLoading: runsLoading } = usePipelineRuns(20);
  const triggerMut = useTriggerPipeline();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  const schedulerStatus = health?.scheduler_paused
    ? "paused"
    : health?.scheduler_running
    ? "running"
    : "stopped";

  const handleTrigger = (phase: string) => {
    triggerMut.mutate(phase, {
      onSuccess: () => toast.success(`Phase "${phase}" triggered`),
      onError: (err) =>
        toast.error(`Trigger failed: ${(err as Error).message}`),
    });
  };

  return (
    <div className="space-y-6">
      {/* Scheduler status */}
      <div className="rounded-xl border border-border bg-surface-elevated p-4">
        <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-3">
          Scheduler Status
        </h3>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            {schedulerStatus === "running" ? (
              <Play className="w-4 h-4 text-emerald-400" />
            ) : schedulerStatus === "paused" ? (
              <Pause className="w-4 h-4 text-yellow-400" />
            ) : (
              <CircleOff className="w-4 h-4 text-red-400" />
            )}
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium capitalize",
                schedulerStatus === "running" &&
                  "bg-emerald-500/15 text-emerald-400",
                schedulerStatus === "paused" &&
                  "bg-yellow-500/15 text-yellow-400",
                schedulerStatus === "stopped" && "bg-red-500/15 text-red-400"
              )}
            >
              {schedulerStatus}
            </span>
          </div>
          {health && (
            <div className="flex items-center gap-1.5 text-xs text-text-tertiary">
              <Timer className="w-3.5 h-3.5" />
              Uptime: {formatUptime(health.uptime_seconds)}
            </div>
          )}
        </div>
      </div>

      {/* Next run times */}
      <div className="rounded-xl border border-border bg-surface-elevated p-4">
        <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-3">
          Schedule
        </h3>
        <div className="space-y-2">
          {SCHEDULE.map((s) => (
            <div
              key={s.phase}
              className="flex items-center justify-between py-1.5 border-b border-border/50 last:border-0"
            >
              <div className="flex items-center gap-2 text-sm">
                <span>{s.icon}</span>
                <span className="font-medium text-text-primary">{s.label}</span>
              </div>
              <div className="flex items-center gap-3 text-xs text-text-tertiary">
                <span className="font-mono">{s.cron}</span>
                <span className="text-text-secondary">
                  <Clock className="w-3 h-3 inline mr-0.5" />
                  {nextRunRelative(s.cron)}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Manual triggers */}
      <div className="rounded-xl border border-border bg-surface-elevated p-4">
        <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-3">
          Manual Trigger
        </h3>
        <div className="flex flex-wrap gap-2">
          {TRIGGER_PHASES.map((phase) => (
            <button
              key={phase}
              onClick={() => handleTrigger(phase)}
              disabled={triggerMut.isPending}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm font-medium text-text-secondary hover:bg-muted hover:text-text-primary transition-colors disabled:opacity-50 disabled:cursor-not-allowed capitalize"
            >
              <Rocket className="w-3.5 h-3.5" />
              {phase}
            </button>
          ))}
        </div>
      </div>

      {/* Execution history */}
      <div className="rounded-xl border border-border bg-surface-elevated p-4">
        <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-3">
          Execution History
        </h3>
        {runsLoading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-8 rounded bg-muted animate-pulse"
              />
            ))}
          </div>
        ) : runs && runs.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-text-tertiary uppercase border-b border-border">
                  <th className="text-left py-2 pr-3 font-medium">Phase</th>
                  <th className="text-left py-2 pr-3 font-medium">Status</th>
                  <th className="text-left py-2 pr-3 font-medium">Started</th>
                  <th className="text-left py-2 pr-3 font-medium">Duration</th>
                  <th className="text-right py-2 font-medium">Files</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run: PipelineRun) => (
                  <tr
                    key={run.id}
                    onClick={() => setSelectedRunId(run.id)}
                    className={cn(
                      "border-b border-border/50 last:border-0 cursor-pointer hover:bg-muted/50 transition-colors",
                      selectedRunId === run.id && "bg-muted/30"
                    )}
                  >
                    <td className="py-2 pr-3 font-medium text-text-primary capitalize">
                      {run.phase}
                    </td>
                    <td className="py-2 pr-3">
                      <StatusBadge status={run.status} />
                    </td>
                    <td className="py-2 pr-3 text-text-tertiary text-xs">
                      {formatRelativeTime(run.started_at)}
                    </td>
                    <td className="py-2 pr-3 text-text-tertiary text-xs font-mono">
                      {formatDuration(run.started_at, run.completed_at)}
                    </td>
                    <td className="py-2 text-right text-xs">
                      <span className="text-emerald-400">
                        {run.files_succeeded}
                      </span>
                      <span className="text-text-tertiary">/</span>
                      <span className="text-text-primary">
                        {run.files_processed}
                      </span>
                      {run.files_failed > 0 && (
                        <span className="text-red-400 ml-1">
                          ({run.files_failed} failed)
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-text-tertiary">No execution history yet.</p>
        )}
        {selectedRunId && (
          <p className="text-xs text-text-tertiary mt-2">
            Selected run: <code className="font-mono text-primary">{selectedRunId}</code>{" "}
            — switch to Logs tab to see detailed logs for this run.
          </p>
        )}
      </div>
    </div>
  );
}
