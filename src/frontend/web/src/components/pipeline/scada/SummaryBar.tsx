import type { PlantStatus } from "@/types/pipeline";
import { Badge } from "@/components/ui/badge";
import { formatUptime, relativeTime } from "./scada-theme";
import { cn } from "@/lib/utils";

interface SummaryBarProps {
  status: PlantStatus;
}

export default function SummaryBar({ status }: SummaryBarProps) {
  const hasErrors = status.stages.some((s) => s.failed_count > 0);
  const healthColor = status.master_paused
    ? "bg-amber-400"
    : hasErrors
      ? "bg-red-400"
      : "bg-green-400";
  const healthLabel = status.master_paused
    ? "PAUSED"
    : hasErrors
      ? "ALERT"
      : "ONLINE";

  return (
    <div
      className="flex flex-wrap items-center gap-4 rounded-lg border border-gray-700/50 bg-gray-900/60 px-4 py-2.5"
      style={{ fontFamily: "'JetBrains Mono', monospace" }}
    >
      {/* Health indicator */}
      <div className="flex items-center gap-2">
        <span className={cn("h-2.5 w-2.5 rounded-full", healthColor)} />
        <span className="text-xs font-semibold text-gray-300">{healthLabel}</span>
      </div>

      <div className="h-4 w-px bg-gray-700" />

      {/* Counts */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge variant="outline" className="border-gray-600 text-gray-300 font-mono">
          {status.totals.total_files.toLocaleString()} files
        </Badge>
        <Badge variant="outline" className="border-green-700 text-green-400 font-mono">
          {status.totals.verified.toLocaleString()} verified
        </Badge>
        {status.totals.failed > 0 && (
          <Badge variant="outline" className="border-red-700 text-red-400 font-mono">
            {status.totals.failed} failed
          </Badge>
        )}
        {status.totals.in_transit > 0 && (
          <Badge variant="outline" className="border-blue-700 text-blue-400 font-mono">
            {status.totals.in_transit} in-transit
          </Badge>
        )}
      </div>

      <div className="ml-auto flex items-center gap-3 text-[10px] text-gray-500">
        <span>Up {formatUptime(status.uptime_seconds)}</span>
        <span>{relativeTime(status.last_heartbeat)}</span>
      </div>
    </div>
  );
}
