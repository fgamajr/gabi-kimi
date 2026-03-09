import { usePipelineStatus, usePipelineMonths, usePipelineRuns, useTriggerPipeline } from "@/hooks/usePipeline";
import type { FileStatus, RegistryStatus } from "@/types/pipeline";
import { toast } from "sonner";
import { Files, CheckCircle2, Clock, AlertTriangle, Rocket } from "lucide-react";
import CoverageChart from "./CoverageChart";

const PENDING_STATES: FileStatus[] = [
  "DISCOVERED", "QUEUED", "DOWNLOADING", "DOWNLOADED",
  "EXTRACTING", "EXTRACTED", "INGESTING",
];

const FAILED_STATES: FileStatus[] = [
  "DOWNLOAD_FAILED", "EXTRACT_FAILED", "INGEST_FAILED", "VERIFY_FAILED",
];

function sumStatuses(status: RegistryStatus | undefined, keys: FileStatus[]): number {
  if (!status) return 0;
  return keys.reduce((acc, k) => acc + (status[k] ?? 0), 0);
}

function totalFiles(status: RegistryStatus | undefined): number {
  if (!status) return 0;
  return Object.values(status).reduce((a, b) => a + b, 0);
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

export default function PipelineOverview() {
  const { data: status, isLoading: statusLoading } = usePipelineStatus();
  const { data: months, isLoading: monthsLoading } = usePipelineMonths();
  const { data: runs } = usePipelineRuns(5);
  const triggerMut = useTriggerPipeline();

  const total = totalFiles(status);
  const verified = status?.VERIFIED ?? 0;
  const pending = sumStatuses(status, PENDING_STATES);
  const failed = sumStatuses(status, FAILED_STATES);
  const verifiedPct = total > 0 ? Math.round((verified / total) * 100) : 0;

  const handleTrigger = (phase: string) => {
    triggerMut.mutate(phase, {
      onSuccess: () => toast.success(`Pipeline phase "${phase}" triggered.`),
      onError: (err) => toast.error(`Failed to trigger: ${(err as Error).message}`),
    });
  };

  if (statusLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-24 rounded-xl bg-surface-elevated animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Metric cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <MetricCard
          icon={<Files className="w-4 h-4 text-blue-400" />}
          label="Total Files"
          value={total.toLocaleString()}
        />
        <MetricCard
          icon={<CheckCircle2 className="w-4 h-4 text-emerald-400" />}
          label="Verified"
          value={verified.toLocaleString()}
          sub={`${verifiedPct}%`}
        />
        <MetricCard
          icon={<Clock className="w-4 h-4 text-yellow-400" />}
          label="Pending"
          value={pending.toLocaleString()}
        />
        <MetricCard
          icon={<AlertTriangle className="w-4 h-4 text-red-400" />}
          label="Failed"
          value={failed.toLocaleString()}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Recent activity */}
        <div className="rounded-xl border border-border bg-surface-elevated p-4">
          <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-3">
            Recent Activity
          </h3>
          {runs && runs.length > 0 ? (
            <ul className="space-y-2">
              {runs.map((run) => (
                <li
                  key={run.id}
                  className="flex items-center justify-between text-sm py-1.5 border-b border-border/50 last:border-0"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="font-medium text-text-primary truncate">
                      {run.phase}
                    </span>
                    <span
                      className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${
                        run.status === "completed"
                          ? "bg-emerald-500/15 text-emerald-400"
                          : run.status === "failed"
                          ? "bg-red-500/15 text-red-400"
                          : "bg-yellow-500/15 text-yellow-400"
                      }`}
                    >
                      {run.status}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-text-tertiary shrink-0">
                    <span>{formatRelativeTime(run.started_at)}</span>
                    <span>{formatDuration(run.started_at, run.completed_at)}</span>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-text-tertiary">No recent runs.</p>
          )}
        </div>

        {/* Coverage chart */}
        <div className="rounded-xl border border-border bg-surface-elevated p-4">
          <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-3">
            Coverage by Year
          </h3>
          {monthsLoading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-6 rounded bg-muted animate-pulse" />
              ))}
            </div>
          ) : months ? (
            <CoverageChart months={months} />
          ) : (
            <p className="text-sm text-text-tertiary">No data.</p>
          )}
        </div>
      </div>

      {/* Quick actions */}
      <div className="rounded-xl border border-border bg-surface-elevated p-4">
        <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-3">
          Quick Actions
        </h3>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => handleTrigger("discovery")}
            disabled={triggerMut.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm font-medium text-text-secondary hover:bg-muted hover:text-text-primary transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Rocket className="w-3.5 h-3.5" />
            Run Discovery
          </button>
          <button
            onClick={() => handleTrigger("download")}
            disabled={triggerMut.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm font-medium text-text-secondary hover:bg-muted hover:text-text-primary transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Rocket className="w-3.5 h-3.5" />
            Run Download
          </button>
          <button
            onClick={() => handleTrigger("discovery")}
            disabled={triggerMut.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg border border-primary/40 px-3 py-2 text-sm font-medium text-primary hover:bg-primary/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Rocket className="w-3.5 h-3.5" />
            Run Full Pipeline
          </button>
        </div>
      </div>
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-xl bg-surface-elevated p-4 border border-border">
      <div className="flex items-center gap-2 mb-2">
        {icon}
        <span className="text-xs text-text-tertiary font-medium">{label}</span>
      </div>
      <div className="flex items-end gap-1.5">
        <span className="text-2xl font-bold text-foreground">{value}</span>
        {sub && <span className="text-xs text-text-secondary mb-0.5">{sub}</span>}
      </div>
    </div>
  );
}
