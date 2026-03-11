import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import { useQueryClient } from "@tanstack/react-query";
import { Calendar, FileText, Gauge, LayoutDashboard, Play, Settings } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { usePausePipeline, useResumePipeline, useWorkerHealth } from "@/hooks/usePipeline";
import { cn } from "@/lib/utils";
import WorkerUnavailableState from "@/components/pipeline/WorkerUnavailableState";

const PipelineOverview = lazy(() => import("@/components/pipeline/PipelineOverview"));
const PipelineTimeline = lazy(() => import("@/components/pipeline/PipelineTimeline"));
const PipelineScheduler = lazy(() => import("@/components/pipeline/PipelineScheduler"));
const PipelineLogs = lazy(() => import("@/components/pipeline/PipelineLogs"));
const PipelineSettings = lazy(() => import("@/components/pipeline/PipelineSettings"));
const PlantDashboard = lazy(() => import("@/components/pipeline/scada/PlantDashboard"));

const TAB_CONFIG = [
  { value: "scada", label: "Control Panel", icon: Gauge },
  { value: "overview", label: "Overview", icon: LayoutDashboard },
  { value: "timeline", label: "Timeline", icon: Calendar },
  { value: "pipeline", label: "Pipeline", icon: Play },
  { value: "logs", label: "Logs", icon: FileText },
  { value: "settings", label: "Settings", icon: Settings },
] as const;

function TabFallback() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-28 rounded-2xl bg-surface-elevated" />
      <div className="h-56 rounded-2xl bg-surface-elevated" />
    </div>
  );
}

export default function PipelinePage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialTab = searchParams.get("tab");
  const validInitialTab = useMemo(
    () => TAB_CONFIG.some((item) => item.value === initialTab) ? initialTab! : "scada",
    [initialTab]
  );
  const [activeTab, setActiveTab] = useState(validInitialTab);
  const { data: health, isError: healthError } = useWorkerHealth();
  const pauseMut = usePausePipeline();
  const resumeMut = useResumePipeline();

  useEffect(() => {
    setActiveTab(validInitialTab);
  }, [validInitialTab]);

  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    next.set("tab", activeTab);
    setSearchParams(next, { replace: true });
  }, [activeTab, searchParams, setSearchParams]);

  useEffect(() => {
    const handleKeyDown = async (event: KeyboardEvent) => {
      const tag = (event.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      if (event.key >= "1" && event.key <= "6") {
        event.preventDefault();
        setActiveTab(TAB_CONFIG[Number(event.key) - 1].value);
        return;
      }

      if (event.key === "r" || event.key === "R") {
        event.preventDefault();
        await queryClient.invalidateQueries({ queryKey: ["pipeline"] });
        await queryClient.invalidateQueries({ queryKey: ["worker"] });
        toast.success("Dashboard atualizado.");
        return;
      }

      if (event.key === "p" || event.key === "P") {
        event.preventDefault();
        try {
          if (health?.scheduler_paused) {
            await resumeMut.mutateAsync();
            toast.success("Pipeline retomado.");
          } else {
            await pauseMut.mutateAsync();
            toast.success("Pipeline pausado.");
          }
        } catch (error) {
          toast.error(`Falha ao alternar scheduler: ${(error as Error).message}`);
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [health?.scheduler_paused, pauseMut, queryClient, resumeMut]);

  const statusLabel = healthError
    ? "Offline"
    : health?.scheduler_paused
      ? "Paused"
      : health?.status === "ok"
        ? "Healthy"
        : "Loading";

  return (
    <div className="mx-auto max-w-7xl space-y-6 px-4 py-6 md:px-8 md:py-10">
      <header className="flex flex-col gap-4 rounded-[28px] border border-border bg-surface-elevated p-6 shadow-sm md:flex-row md:items-end md:justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold text-text-primary md:text-3xl">Pipeline</h1>
            <span
              className={cn(
                "inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold",
                statusLabel === "Healthy" && "bg-emerald-500/10 text-emerald-300",
                statusLabel === "Paused" && "bg-amber-500/10 text-amber-300",
                statusLabel === "Offline" && "bg-red-500/10 text-red-300",
                statusLabel === "Loading" && "bg-muted text-text-secondary"
              )}
            >
              <span
                className={cn(
                  "h-2 w-2 rounded-full",
                  statusLabel === "Healthy" && "bg-emerald-400",
                  statusLabel === "Paused" && "bg-amber-400",
                  statusLabel === "Offline" && "bg-red-400",
                  statusLabel === "Loading" && "bg-text-secondary"
                )}
              />
              {statusLabel}
            </span>
          </div>
          <p className="max-w-2xl text-sm text-text-secondary">
            Painel de observabilidade do worker autônomo. O objetivo é confirmar que o organismo continua saudável,
            não conduzir o fluxo manualmente.
          </p>
        </div>
        <div className="grid gap-1 text-xs text-text-tertiary">
          <span>Atalhos: `1-6` alternam tabs, `R` atualiza, `P` pausa/retoma.</span>
          <span>Horários sempre em UTC no backend; leitura operacional deve considerar BRT no contexto do DOU.</span>
        </div>
      </header>

      {healthError ? (
        <WorkerUnavailableState message="O web está no ar, mas a integração com o worker falhou. Verifique `WORKER_URL`, o processo HTTP do worker ou o fallback local embutido." />
      ) : null}

      <Tabs.Root value={activeTab} onValueChange={setActiveTab}>
        <Tabs.List className="flex gap-2 overflow-x-auto rounded-2xl border border-border bg-surface-elevated p-2 shadow-sm">
          {TAB_CONFIG.map(({ value, label, icon: Icon }) => (
            <Tabs.Trigger
              key={value}
              value={value}
              className={cn(
                "inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium transition-colors",
                "text-text-secondary hover:bg-background/60 hover:text-text-primary",
                "data-[state=active]:bg-primary data-[state=active]:text-primary-foreground"
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Tabs.Trigger>
          ))}
        </Tabs.List>

        <div className="pt-4">
          <Tabs.Content value="scada">
            {activeTab === "scada" ? (
              <Suspense fallback={<TabFallback />}>
                <PlantDashboard />
              </Suspense>
            ) : null}
          </Tabs.Content>

          <Tabs.Content value="overview">
            {activeTab === "overview" ? (
              <Suspense fallback={<TabFallback />}>
                <PipelineOverview />
              </Suspense>
            ) : null}
          </Tabs.Content>

          <Tabs.Content value="timeline">
            {activeTab === "timeline" ? (
              <Suspense fallback={<TabFallback />}>
                <PipelineTimeline />
              </Suspense>
            ) : null}
          </Tabs.Content>

          <Tabs.Content value="pipeline">
            {activeTab === "pipeline" ? (
              <Suspense fallback={<TabFallback />}>
                <PipelineScheduler />
              </Suspense>
            ) : null}
          </Tabs.Content>

          <Tabs.Content value="logs">
            {activeTab === "logs" ? (
              <Suspense fallback={<TabFallback />}>
                <PipelineLogs />
              </Suspense>
            ) : null}
          </Tabs.Content>

          <Tabs.Content value="settings">
            {activeTab === "settings" ? (
              <Suspense fallback={<TabFallback />}>
                <PipelineSettings />
              </Suspense>
            ) : null}
          </Tabs.Content>
        </div>
      </Tabs.Root>
    </div>
  );
}
