import { lazy, Suspense } from "react";
import { useAnalytics } from "@/hooks/useAnalytics";
import { useI18n } from "@/hooks/useI18n";
import { cn } from "@/lib/utils";
const AnalyticsCharts = lazy(() => import("@/components/analytics/AnalyticsCharts"));

export default function AnalyticsPage() {
  const { t } = useI18n();
  const { data, isLoading } = useAnalytics();

  if (isLoading || !data) {
    return (
      <div className="px-4 md:px-8 py-6 md:py-10 max-w-5xl mx-auto">
        <div className="grid gap-4">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className="h-48 rounded-xl bg-surface-elevated animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  const Panel = ({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) => (
    <div className={cn("rounded-xl border border-border bg-surface-elevated p-4 md:p-5", className)}>
      <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-4">{title}</h3>
      {children}
    </div>
  );

  return (
    <div className="px-4 md:px-8 py-6 md:py-10 max-w-5xl mx-auto space-y-6">
      <h1 className="text-xl md:text-2xl font-bold text-foreground">{t("analytics.title")}</h1>

      {/* KPI row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {data.kpis.map((kpi) => (
          <div key={kpi.label} className="rounded-xl border border-border bg-surface-elevated p-4 space-y-1">
            <p className="text-xs text-text-tertiary font-medium">{kpi.label}</p>
            <div className="flex items-end justify-between">
              <span className="text-2xl font-bold text-foreground">{kpi.value}</span>
              {typeof kpi.change === "number" ? (
                <span className={cn("text-xs font-medium", kpi.change > 0 ? "text-do3" : "text-destructive")}>
                  {kpi.change > 0 ? "+" : ""}{kpi.change}%
                </span>
              ) : (
                <span className="text-xs font-medium text-text-tertiary">{kpi.changeLabel || t("common.states.currentBase")}</span>
              )}
            </div>
            {typeof kpi.change === "number" && kpi.changeLabel ? (
              <p className="text-[11px] text-text-tertiary">{kpi.changeLabel}</p>
            ) : null}
          </div>
        ))}
      </div>

      <Suspense
        fallback={
          <div className="grid gap-4">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-48 rounded-xl bg-surface-elevated animate-pulse" />
            ))}
          </div>
        }
      >
        <AnalyticsCharts data={data} />
      </Suspense>
    </div>
  );
}
