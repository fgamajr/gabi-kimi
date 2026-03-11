import { X, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import type { PlantStage } from "@/types/pipeline";
import { STAGE_NAMES, deriveStageState, relativeTime } from "./scada-theme";
import { useStagePause, useStageResume, useStageTrigger } from "@/hooks/usePipeline";
import { cn } from "@/lib/utils";

interface StageDetailProps {
  stage: PlantStage;
  onClose: () => void;
}

export default function StageDetail({ stage, onClose }: StageDetailProps) {
  const state = deriveStageState(stage);
  const name = STAGE_NAMES[stage.id] ?? stage.id;

  const pauseMut = useStagePause();
  const resumeMut = useStageResume();
  const triggerMut = useStageTrigger();

  const handleToggle = (checked: boolean) => {
    if (checked) resumeMut.mutate(stage.id);
    else pauseMut.mutate(stage.id);
  };

  return (
    <div
      className="mt-2 rounded-lg border border-gray-700 bg-gray-900/80 p-4"
      style={{ fontFamily: "'JetBrains Mono', monospace" }}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-200">{name}</h3>
        <button type="button" onClick={onClose} className="text-gray-500 hover:text-gray-300">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3 text-xs text-gray-400">
        <div>
          <span className="text-gray-600">State:</span>{" "}
          <span className={cn(
            state === "AUTO" && "text-green-400",
            state === "PAUSED" && "text-amber-400",
            state === "ERROR" && "text-red-400",
            state === "IDLE" && "text-gray-500",
          )}>{state}</span>
        </div>
        <div>
          <span className="text-gray-600">Queue:</span> {stage.queue_depth}
        </div>
        <div>
          <span className="text-gray-600">Failed:</span>{" "}
          <span className={stage.failed_count > 0 ? "text-red-400" : ""}>{stage.failed_count}</span>
        </div>
        <div>
          <span className="text-gray-600">Throughput:</span> {stage.throughput ?? "N/A"}/h
        </div>
        {stage.last_run?.error_message && (
          <div className="col-span-2 text-red-400 text-[10px] truncate">
            Error: {stage.last_run.error_message}
          </div>
        )}
        {stage.next_run && (
          <div className="col-span-2">
            <span className="text-gray-600">Next run:</span> {relativeTime(stage.next_run)}
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="mt-3 flex items-center gap-3">
        {stage.enabled && (
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-gray-500">Valve</span>
            <Switch
              checked={state !== "PAUSED"}
              onCheckedChange={handleToggle}
              className="scale-75"
            />
          </div>
        )}
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs border-gray-600 text-gray-300 hover:bg-gray-800"
          onClick={() => triggerMut.mutate(stage.id)}
          disabled={!stage.enabled || triggerMut.isPending}
        >
          <Play className="h-3 w-3 mr-1" />
          Trigger Now
        </Button>
      </div>
    </div>
  );
}
