import { useCallback, useState } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  usePlantStatus,
  useStagePause,
  useStageResume,
  useStageTrigger,
  usePauseAll,
  useResumeAll,
} from "@/hooks/usePipeline";
import { SCADA_COLORS } from "./scada-theme";
import SummaryBar from "./SummaryBar";
import MasterValve from "./MasterValve";
import StageMachine from "./StageMachine";
import PipeConnection from "./PipeConnection";
import StorageTanks from "./StorageTanks";
import StageDetail from "./StageDetail";
import { useKeyboardShortcuts } from "./useKeyboardShortcuts";
import type { PlantStage } from "@/types/pipeline";
import { cn } from "@/lib/utils";

function derivePipeState(left: PlantStage | undefined, right: PlantStage | undefined) {
  if (!left || !right) return "empty" as const;
  if (!left.enabled || !right.enabled) return "empty" as const;
  if (left.failed_count > 0 || right.failed_count > 0) return "blocked" as const;
  if (left.state === "PAUSED" || right.state === "PAUSED") return "empty" as const;
  return "active" as const;
}

/** Skeleton loader for the pipeline flow. */
function SkeletonFlow() {
  return (
    <div className="flex items-center justify-center gap-3 py-12">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <div className="h-28 w-28 animate-pulse rounded-lg bg-gray-800 border border-gray-700" />
          {i < 5 && <div className="h-0.5 w-8 animate-pulse bg-gray-700 rounded" />}
        </div>
      ))}
    </div>
  );
}

export default function PlantDashboard() {
  const { data: status, isLoading, isError, refetch } = usePlantStatus();
  const [expandedStage, setExpandedStage] = useState<string | null>(null);

  const pauseMut = useStagePause();
  const resumeMut = useStageResume();
  const triggerMut = useStageTrigger();
  const pauseAllMut = usePauseAll();
  const resumeAllMut = useResumeAll();

  const stages = status?.stages ?? [];

  const handlePause = useCallback(
    (index: number) => {
      const stage = stages[index];
      if (stage?.enabled) pauseMut.mutate(stage.id);
    },
    [stages, pauseMut],
  );

  const handleResume = useCallback(
    (index: number) => {
      const stage = stages[index];
      if (stage?.enabled) resumeMut.mutate(stage.id);
    },
    [stages, resumeMut],
  );

  const handleTrigger = useCallback(
    (index: number) => {
      const stage = stages[index];
      if (stage?.enabled) triggerMut.mutate(stage.id);
    },
    [stages, triggerMut],
  );

  const handleMasterToggle = useCallback(() => {
    if (status?.master_paused) {
      resumeAllMut.mutate();
    } else {
      pauseAllMut.mutate();
    }
  }, [status?.master_paused, pauseAllMut, resumeAllMut]);

  const { focusedIndex } = useKeyboardShortcuts({
    stageCount: stages.length,
    onPause: handlePause,
    onResume: handleResume,
    onTrigger: handleTrigger,
    onMasterToggle: handleMasterToggle,
  });

  // Separate main flow stages from the disabled embed branch
  const mainFlowIds = ["discovery", "backfill_missing", "download", "extract", "bm25", "verify"];
  const mainStages = stages.filter((s) => mainFlowIds.includes(s.id));
  const embedStage = stages.find((s) => s.id === "embed");

  return (
    <div
      className="min-h-screen rounded-2xl"
      style={{
        backgroundColor: SCADA_COLORS.bg,
        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      }}
    >
      <div className="mx-auto max-w-7xl space-y-4 p-4 md:p-6">
        {/* Summary Bar */}
        {status && <SummaryBar status={status} />}

        {/* Error state */}
        {isError && (
          <div className="flex flex-col items-center gap-3 rounded-lg border border-red-700/50 bg-red-900/20 p-6">
            <AlertTriangle className="h-8 w-8 text-red-400" />
            <p className="text-sm text-red-300">Failed to load plant status</p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => refetch()}
              className="border-red-600 text-red-300 hover:bg-red-900/40"
            >
              <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
              Retry
            </Button>
          </div>
        )}

        {/* Loading skeleton */}
        {isLoading && <SkeletonFlow />}

        {/* Main layout: MasterValve | Pipeline Flow | StorageTanks */}
        {status && !isError && (
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
            {/* Master Valve */}
            <div className="shrink-0">
              <MasterValve paused={status.master_paused} />
            </div>

            {/* Pipeline Flow */}
            <div className="flex-1 min-w-0">
              {/* Desktop: single row */}
              <div className="hidden lg:flex items-start justify-center gap-1 flex-wrap">
                {mainStages.map((stage, i) => {
                  const globalIdx = stages.indexOf(stage);
                  return (
                    <div key={stage.id} className="flex items-start">
                      <div className="flex flex-col">
                        <StageMachine
                          stage={stage}
                          focused={focusedIndex === globalIdx}
                          onExpand={() =>
                            setExpandedStage(expandedStage === stage.id ? null : stage.id)
                          }
                        />
                        {expandedStage === stage.id && (
                          <StageDetail
                            stage={stage}
                            onClose={() => setExpandedStage(null)}
                          />
                        )}
                      </div>
                      {i < mainStages.length - 1 && (
                        <PipeConnection
                          state={derivePipeState(stage, mainStages[i + 1])}
                        />
                      )}
                    </div>
                  );
                })}
              </div>

              {/* Embed branch (desktop) */}
              {embedStage && (
                <div className="hidden lg:flex justify-center mt-3">
                  <div className="flex flex-col items-center">
                    <PipeConnection state="empty" vertical />
                    <StageMachine
                      stage={embedStage}
                      focused={focusedIndex === stages.indexOf(embedStage)}
                      onExpand={() =>
                        setExpandedStage(
                          expandedStage === embedStage.id ? null : embedStage.id,
                        )
                      }
                    />
                    {expandedStage === embedStage.id && (
                      <StageDetail
                        stage={embedStage}
                        onClose={() => setExpandedStage(null)}
                      />
                    )}
                  </div>
                </div>
              )}

              {/* Tablet: 2-row grid */}
              <div className="hidden md:grid lg:hidden grid-cols-4 gap-3">
                {stages.map((stage, i) => (
                  <div key={stage.id} className="flex flex-col">
                    <StageMachine
                      stage={stage}
                      focused={focusedIndex === i}
                      onExpand={() =>
                        setExpandedStage(expandedStage === stage.id ? null : stage.id)
                      }
                    />
                    {expandedStage === stage.id && (
                      <StageDetail
                        stage={stage}
                        onClose={() => setExpandedStage(null)}
                      />
                    )}
                  </div>
                ))}
              </div>

              {/* Mobile: vertical stack */}
              <div className="flex flex-col items-center gap-2 md:hidden">
                {stages.map((stage, i) => (
                  <div key={stage.id} className="flex flex-col items-center w-full max-w-[200px]">
                    <StageMachine
                      stage={stage}
                      focused={focusedIndex === i}
                      onExpand={() =>
                        setExpandedStage(expandedStage === stage.id ? null : stage.id)
                      }
                    />
                    {expandedStage === stage.id && (
                      <StageDetail
                        stage={stage}
                        onClose={() => setExpandedStage(null)}
                      />
                    )}
                    {i < stages.length - 1 && (
                      <PipeConnection
                        state={derivePipeState(stage, stages[i + 1])}
                        vertical
                      />
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Storage Tanks */}
            <div className="shrink-0">
              <StorageTanks storage={status.storage} />
            </div>
          </div>
        )}

        {/* Keyboard shortcuts legend */}
        <div className="text-center text-[10px] text-gray-600 pt-2">
          <span className={cn("px-1 py-0.5 rounded bg-gray-800 text-gray-500 mr-1")}>1-7</span> focus stage
          <span className="mx-2">|</span>
          <span className="px-1 py-0.5 rounded bg-gray-800 text-gray-500 mr-1">P</span> pause
          <span className="mx-2">|</span>
          <span className="px-1 py-0.5 rounded bg-gray-800 text-gray-500 mr-1">R</span> resume
          <span className="mx-2">|</span>
          <span className="px-1 py-0.5 rounded bg-gray-800 text-gray-500 mr-1">T</span> trigger
          <span className="mx-2">|</span>
          <span className="px-1 py-0.5 rounded bg-gray-800 text-gray-500 mr-1">Space</span> master valve
          <span className="mx-2">|</span>
          <span className="px-1 py-0.5 rounded bg-gray-800 text-gray-500 mr-1">Esc</span> clear
        </div>
      </div>
    </div>
  );
}
