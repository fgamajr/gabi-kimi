import {
  useWorkerHealth,
  usePausePipeline,
  useResumePipeline,
} from "@/hooks/usePipeline";
import { toast } from "sonner";
import {
  AlertTriangle,
  HardDrive,
  Clock,
  Info,
  Pause,
  Play,
} from "lucide-react";
import { cn } from "@/lib/utils";

const SCHEDULE_CONFIG = [
  {
    name: "Discovery",
    cron: "0 23 * * *",
    description: "Scan DOU catalog for new file listings",
  },
  {
    name: "Download",
    cron: "30 23 * * *",
    description: "Download discovered ZIP/XML files from DOU",
  },
  {
    name: "Ingest",
    cron: "0 0 * * *",
    description: "Extract and index articles into Elasticsearch",
  },
  {
    name: "Verify",
    cron: "0 1 * * *",
    description: "Verify ingested articles match source files",
  },
  {
    name: "Retry",
    cron: "0 6 * * *",
    description: "Retry previously failed files",
  },
];

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export default function PipelineSettings() {
  const { data: health } = useWorkerHealth();
  const pauseMut = usePausePipeline();
  const resumeMut = useResumePipeline();

  const isPaused = health?.scheduler_paused ?? false;
  const diskUsage = health?.disk_usage;
  const dbSizeBytes = diskUsage?.db_size_bytes ?? 0;
  const totalBytes = diskUsage?.total_bytes ?? 200 * 1024 * 1024;
  const freeBytes = diskUsage?.free_bytes ?? totalBytes;
  const usedBytes = totalBytes - freeBytes;
  const dbSizeWarning = dbSizeBytes > 100 * 1024 * 1024; // 100MB threshold

  const handlePause = () => {
    if (!window.confirm("Are you sure you want to pause the pipeline scheduler? No new phases will execute until resumed.")) {
      return;
    }
    pauseMut.mutate(undefined, {
      onSuccess: () => toast.success("Pipeline paused"),
      onError: (err) =>
        toast.error(`Failed to pause: ${(err as Error).message}`),
    });
  };

  const handleResume = () => {
    resumeMut.mutate(undefined, {
      onSuccess: () => toast.success("Pipeline resumed"),
      onError: (err) =>
        toast.error(`Failed to resume: ${(err as Error).message}`),
    });
  };

  return (
    <div className="space-y-6">
      {/* Schedule configuration */}
      <div className="rounded-xl border border-border bg-surface-elevated p-4">
        <div className="flex items-center gap-2 mb-1">
          <Clock className="w-4 h-4 text-text-tertiary" />
          <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
            Schedule Configuration
          </h3>
        </div>

        <div className="flex items-start gap-2 rounded-lg bg-blue-500/10 border border-blue-500/20 px-3 py-2 mb-4 mt-3">
          <Info className="w-3.5 h-3.5 text-blue-400 mt-0.5 shrink-0" />
          <p className="text-xs text-blue-300/80">
            Cron schedules are configured at deploy time. Changing schedules requires a redeployment of the worker process.
          </p>
        </div>

        <div className="space-y-2">
          {SCHEDULE_CONFIG.map((s) => (
            <div
              key={s.name}
              className="flex items-center justify-between py-2 border-b border-border/50 last:border-0"
            >
              <div>
                <span className="text-sm font-medium text-text-primary">
                  {s.name}
                </span>
                <p className="text-xs text-text-tertiary mt-0.5">
                  {s.description}
                </p>
              </div>
              <code className="text-xs font-mono text-text-secondary bg-muted px-2 py-1 rounded shrink-0 ml-3">
                {s.cron}
              </code>
            </div>
          ))}
        </div>
      </div>

      {/* Disk usage */}
      <div className="rounded-xl border border-border bg-surface-elevated p-4">
        <div className="flex items-center gap-2 mb-3">
          <HardDrive className="w-4 h-4 text-text-tertiary" />
          <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
            Disk Usage
          </h3>
        </div>

        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-text-secondary">registry.db size</span>
            <span
              className={cn(
                "text-sm font-mono font-medium",
                dbSizeWarning ? "text-yellow-400" : "text-text-primary"
              )}
            >
              {formatBytes(dbSizeBytes)}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-sm text-text-secondary">Volume usage</span>
            <span className="text-sm font-mono font-medium text-text-primary">
              {formatBytes(usedBytes)} / {formatBytes(totalBytes)}
            </span>
          </div>

          {/* Usage bar */}
          <div className="h-2 rounded-full bg-muted overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-500",
                dbSizeWarning ? "bg-yellow-500" : "bg-primary"
              )}
              style={{
                width: `${Math.min(
                  (usedBytes / totalBytes) * 100,
                  100
                )}%`,
              }}
            />
          </div>
          <p className="text-[10px] text-text-tertiary">
            Free: {formatBytes(freeBytes)}
          </p>

          {dbSizeWarning && (
            <div className="flex items-start gap-2 rounded-lg bg-yellow-500/10 border border-yellow-500/20 px-3 py-2">
              <AlertTriangle className="w-3.5 h-3.5 text-yellow-400 mt-0.5 shrink-0" />
              <p className="text-xs text-yellow-300/80">
                Database size exceeds 100 MB. Consider running VACUUM or expanding the volume.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Danger zone */}
      <div className="rounded-xl border border-red-500/30 bg-surface-elevated p-4">
        <div className="flex items-center gap-2 mb-1">
          <AlertTriangle className="w-4 h-4 text-red-400" />
          <h3 className="text-xs font-semibold text-red-400 uppercase tracking-wider">
            Danger Zone
          </h3>
        </div>
        <p className="text-xs text-text-tertiary mb-4">
          These actions affect the pipeline scheduler. Use with caution.
        </p>

        <div className="space-y-3">
          {/* Current state */}
          <div className="flex items-center gap-2 text-sm">
            <span className="text-text-secondary">Scheduler is currently:</span>
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
                isPaused
                  ? "bg-yellow-500/15 text-yellow-400"
                  : "bg-emerald-500/15 text-emerald-400"
              )}
            >
              {isPaused ? (
                <>
                  <Pause className="w-3 h-3" /> Paused
                </>
              ) : (
                <>
                  <Play className="w-3 h-3" /> Running
                </>
              )}
            </span>
          </div>

          <div className="flex gap-2">
            <button
              onClick={handlePause}
              disabled={isPaused || pauseMut.isPending}
              className="inline-flex items-center gap-1.5 rounded-lg border border-red-500/40 px-3 py-2 text-sm font-medium text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Pause className="w-3.5 h-3.5" />
              {pauseMut.isPending ? "Pausing..." : "Pause Pipeline"}
            </button>
            <button
              onClick={handleResume}
              disabled={!isPaused || resumeMut.isPending}
              className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 px-3 py-2 text-sm font-medium text-emerald-400 hover:bg-emerald-500/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Play className="w-3.5 h-3.5" />
              {resumeMut.isPending ? "Resuming..." : "Resume Pipeline"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
