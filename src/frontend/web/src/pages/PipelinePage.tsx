import { useState, useEffect, lazy, Suspense } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import { useQueryClient } from "@tanstack/react-query";
import { useWorkerHealth } from "@/hooks/usePipeline";
import {
  LayoutDashboard,
  Calendar,
  Play,
  FileText,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";

const PipelineOverview = lazy(() => import("@/components/pipeline/PipelineOverview"));
const PipelineTimeline = lazy(() => import("@/components/pipeline/PipelineTimeline"));
const PipelineScheduler = lazy(() => import("@/components/pipeline/PipelineScheduler"));
const PipelineLogs = lazy(() => import("@/components/pipeline/PipelineLogs"));
const PipelineSettings = lazy(() => import("@/components/pipeline/PipelineSettings"));

const TAB_CONFIG = [
  { value: "overview", label: "Overview", icon: LayoutDashboard },
  { value: "timeline", label: "Timeline", icon: Calendar },
  { value: "pipeline", label: "Pipeline", icon: Play },
  { value: "logs", label: "Logs", icon: FileText },
  { value: "settings", label: "Settings", icon: Settings },
] as const;

function TabFallback() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-24 rounded-xl bg-surface-elevated" />
      <div className="h-48 rounded-xl bg-surface-elevated" />
    </div>
  );
}

export default function PipelinePage() {
  const [activeTab, setActiveTab] = useState("overview");
  const queryClient = useQueryClient();
  const { data: health, isError: healthError } = useWorkerHealth();

  // Keyboard shortcuts: 1-5 switch tabs, R refreshes
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // Skip when focused on input elements
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      if (e.key >= "1" && e.key <= "5") {
        e.preventDefault();
        const idx = parseInt(e.key, 10) - 1;
        setActiveTab(TAB_CONFIG[idx].value);
      } else if (e.key === "r" || e.key === "R") {
        e.preventDefault();
        queryClient.invalidateQueries({ queryKey: ["pipeline"] });
        queryClient.invalidateQueries({ queryKey: ["worker"] });
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [queryClient]);

  const isHealthy = health?.status === "ok" && !healthError;

  return (
    <div className="px-4 md:px-8 py-6 md:py-10 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <h1 className="text-xl md:text-2xl font-bold text-foreground">Pipeline</h1>
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
            isHealthy
              ? "bg-emerald-500/15 text-emerald-400"
              : "bg-red-500/15 text-red-400"
          )}
        >
          <span
            className={cn(
              "h-2 w-2 rounded-full",
              isHealthy ? "bg-emerald-400" : "bg-red-400"
            )}
          />
          {healthError ? "Offline" : isHealthy ? "Healthy" : "Loading..."}
        </span>
      </div>

      {/* Tabs */}
      <Tabs.Root value={activeTab} onValueChange={setActiveTab}>
        <Tabs.List className="flex gap-1 border-b border-border pb-px overflow-x-auto">
          {TAB_CONFIG.map(({ value, label, icon: Icon }) => (
            <Tabs.Trigger
              key={value}
              value={value}
              className={cn(
                "inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium rounded-t-lg transition-colors whitespace-nowrap",
                "text-text-tertiary hover:text-text-secondary",
                "data-[state=active]:text-primary data-[state=active]:border-b-2 data-[state=active]:border-primary data-[state=active]:-mb-px"
              )}
            >
              <Icon className="w-4 h-4" />
              {label}
            </Tabs.Trigger>
          ))}
        </Tabs.List>

        <div className="pt-4">
          <Tabs.Content value="overview" forceMount={activeTab === "overview" ? undefined : undefined}>
            {activeTab === "overview" && (
              <Suspense fallback={<TabFallback />}>
                <PipelineOverview />
              </Suspense>
            )}
          </Tabs.Content>

          <Tabs.Content value="timeline">
            {activeTab === "timeline" && (
              <Suspense fallback={<TabFallback />}>
                <PipelineTimeline />
              </Suspense>
            )}
          </Tabs.Content>

          <Tabs.Content value="pipeline">
            {activeTab === "pipeline" && (
              <Suspense fallback={<TabFallback />}>
                <PipelineScheduler />
              </Suspense>
            )}
          </Tabs.Content>

          <Tabs.Content value="logs">
            {activeTab === "logs" && (
              <Suspense fallback={<TabFallback />}>
                <PipelineLogs />
              </Suspense>
            )}
          </Tabs.Content>

          <Tabs.Content value="settings">
            {activeTab === "settings" && (
              <Suspense fallback={<TabFallback />}>
                <PipelineSettings />
              </Suspense>
            )}
          </Tabs.Content>
        </div>
      </Tabs.Root>
    </div>
  );
}
