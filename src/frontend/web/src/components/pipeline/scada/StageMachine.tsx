import { Search, Download, FileText, Database, Cpu, CheckCircle, ArrowDownToLine } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { PlantStage } from "@/types/pipeline";
import { STATE_STYLES, STAGE_NAMES, deriveStageState, relativeTime } from "./scada-theme";
import { useStagePause, useStageResume } from "@/hooks/usePipeline";
import { cn } from "@/lib/utils";

const STAGE_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  discovery: Search,
  backfill_missing: ArrowDownToLine,
  download: Download,
  extract: FileText,
  bm25: Database,
  embed: Cpu,
  verify: CheckCircle,
};

interface StageMachineProps {
  stage: PlantStage;
  focused: boolean;
  onExpand: () => void;
}

export default function StageMachine({ stage, focused, onExpand }: StageMachineProps) {
  const state = deriveStageState(stage);
  const style = STATE_STYLES[state];
  const Icon = STAGE_ICONS[stage.id] ?? Database;
  const name = STAGE_NAMES[stage.id] ?? stage.id;
  const isDisabled = !stage.enabled;

  const pauseMut = useStagePause();
  const resumeMut = useStageResume();

  const handleToggle = (checked: boolean) => {
    if (checked) {
      resumeMut.mutate(stage.id);
    } else {
      pauseMut.mutate(stage.id);
    }
  };

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={onExpand}
          className={cn(
            "relative flex flex-col items-center gap-2 rounded-lg border-2 p-3 transition-all",
            "min-w-[120px] cursor-pointer select-none",
            style.border,
            style.glow,
            style.bg,
            focused && `ring-2 ${style.ring}`,
            isDisabled && "opacity-40"
          )}
          style={{ fontFamily: "'JetBrains Mono', monospace" }}
        >
          {/* State dot */}
          <div className="absolute right-2 top-2 flex items-center gap-1.5">
            <span className={cn("h-2 w-2 rounded-full", style.dot)} />
          </div>

          {/* Icon */}
          <Icon className={cn("h-6 w-6", style.label)} />

          {/* Name */}
          <span className="text-xs font-semibold text-gray-200 uppercase tracking-wider">
            {name}
          </span>
          {isDisabled && (
            <span className="text-[10px] text-gray-500 italic">disabled</span>
          )}

          {/* Metrics row */}
          <div className="flex items-center gap-3 text-[10px] text-gray-400">
            {stage.queue_depth > 0 && (
              <span className="rounded bg-gray-700/60 px-1.5 py-0.5">
                Q:{stage.queue_depth}
              </span>
            )}
            {stage.throughput !== null && stage.throughput > 0 && (
              <span>{stage.throughput}/h</span>
            )}
            {stage.failed_count > 0 && (
              <span className="text-red-400">{stage.failed_count} err</span>
            )}
          </div>

          {/* Valve toggle */}
          {stage.enabled && (
            <div
              className="mt-1"
              onClick={(e) => e.stopPropagation()}
              onKeyDown={(e) => e.stopPropagation()}
            >
              <Switch
                checked={state !== "PAUSED"}
                onCheckedChange={handleToggle}
                className="scale-75"
              />
            </div>
          )}
        </button>
      </TooltipTrigger>
      <TooltipContent
        side="bottom"
        className="max-w-xs text-xs"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        <div className="space-y-1">
          <p><span className="text-gray-400">State:</span> {state}</p>
          {stage.last_run && (
            <>
              <p><span className="text-gray-400">Last run:</span> {relativeTime(stage.last_run.started_at)}</p>
              <p><span className="text-gray-400">Success:</span> {stage.last_run.files_succeeded}/{stage.last_run.files_processed}</p>
            </>
          )}
          {stage.next_run && (
            <p><span className="text-gray-400">Next:</span> {relativeTime(stage.next_run)}</p>
          )}
        </div>
      </TooltipContent>
    </Tooltip>
  );
}
