import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { TrendingUp, TrendingDown, ArrowRight } from "lucide-react";
import { useHighlights } from "@/hooks/useHighlights";
import { cn } from "@/lib/utils";
import { SECTION_COLORS, type AnalyticsData, type DOSection } from "@/types";
import { getTopSearches, type TopSearch } from "@/lib/api";
import { getRecentSearches } from "@/lib/history";
import { SearchBar } from "@/components/SearchBar";
import { useI18n } from "@/hooks/useI18n";
import { readCachedValue, writeCachedValue } from "@/lib/clientCache";
import { formatDate } from "@/lib/intl";

const TOP_SEARCHES_CACHE_KEY = "top-searches-week";
const TOP_SEARCHES_CACHE_TTL_MS = 10 * 60 * 1000;
const ANALYTICS_CACHE_KEY = "analytics-summary";

export default function HomePage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [topSearches, setTopSearches] = useState<TopSearch[]>(() => readCachedValue<TopSearch[]>(TOP_SEARCHES_CACHE_KEY) ?? []);
  const [topSearchesLoading, setTopSearchesLoading] = useState(false);
  const { data: featured, isLoading: featuredLoading } = useHighlights();
  const cachedAnalytics = useMemo(
    () => readCachedValue<AnalyticsData>(ANALYTICS_CACHE_KEY),
    []
  );

  useEffect(() => {
    const view = typeof window !== "undefined" ? window : undefined;
    const schedule =
      view && "requestIdleCallback" in view
        ? view.requestIdleCallback.bind(view)
        : (callback: IdleRequestCallback) => globalThis.setTimeout(() => callback({ didTimeout: false, timeRemaining: () => 0 } as IdleDeadline), 120);

    const handle = schedule(async () => {
      try {
        setTopSearchesLoading(true);
        const items = await getTopSearches(8, "week");
        setTopSearches(items);
        writeCachedValue(TOP_SEARCHES_CACHE_KEY, items, TOP_SEARCHES_CACHE_TTL_MS);
      } catch {
        setTopSearches((current) => current);
      } finally {
        setTopSearchesLoading(false);
      }
    });

    return () => {
      if (view && "cancelIdleCallback" in view) {
        view.cancelIdleCallback(handle as number);
      } else {
        globalThis.clearTimeout(handle as number);
      }
    };
  }, []);

  const chipItems = useMemo(
    () =>
      topSearches.length
        ? topSearches.map((item) => ({ query: item.query, count: item.count }))
        : getRecentSearches().map((item) => ({ query: item, count: undefined })),
    [topSearches]
  );

  const submitSearch = (term?: string) => {
    const value = (term ?? query).trim();
    if (!value) return;
    navigate(`/busca?q=${encodeURIComponent(value)}`);
  };

  return (
    <div className="px-4 md:px-8 py-6 md:py-10 max-w-4xl mx-auto space-y-8">
      {/* Header */}
      <div className="space-y-1">
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground">
          GABI <span className="text-primary">DOU</span>
        </h1>
        <p className="text-text-secondary text-sm">{t("home.subtitle")}</p>
      </div>

      <SearchBar
        defaultValue={query}
        onQueryChange={setQuery}
        onSearch={submitSearch}
        placeholder={t("searchBar.placeholder")}
        visualState={topSearchesLoading ? "searching" : query.trim() ? "typing" : chipItems.length > 0 ? "settled" : "idle"}
        statusText={topSearchesLoading ? t("home.searchStatusUpdating") : chipItems.length > 0 ? t("home.searchStatusReady") : undefined}
      />

      {chipItems.length > 0 ? (
        <div className="flex gap-2 overflow-x-auto scrollbar-thin pb-1 -mx-4 px-4 md:mx-0 md:px-0">
          {chipItems.map((chip, i) => (
            <button
              key={chip.query}
              onClick={() => submitSearch(chip.query)}
              className={cn(
                "shrink-0 px-4 py-1.5 rounded-full text-xs font-medium border transition-colors",
                i === 0
                  ? "bg-primary text-primary-foreground border-primary"
                  : "bg-surface-elevated text-text-secondary border-border hover:border-primary/40 hover:text-foreground"
              )}
            >
              {chip.query}
              {chip.count ? <span className="ml-1 text-primary-foreground/80">({chip.count})</span> : null}
            </button>
          ))}
        </div>
      ) : null}

      {/* Featured */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wider">{t("home.highlights")}</h2>
          <Link to="/busca" className="text-xs text-primary hover:underline flex items-center gap-1">
            {t("common.actions.viewAll")} <ArrowRight className="w-3 h-3" />
          </Link>
        </div>

        {featuredLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-28 rounded-xl bg-surface-elevated animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="space-y-3">
            {featured?.map((doc) => (
              <Link
                key={doc.id}
                to={`/documento/${doc.id}`}
                className="block rounded-xl border border-border bg-surface-elevated p-4 hover:border-primary/30 hover:shadow-md transition-all group"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="space-y-1.5 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={cn("text-[10px] font-bold px-2 py-0.5 rounded-md border", SECTION_COLORS[doc.section])}>
                        {doc.section}
                      </span>
                      <span className="text-[11px] text-text-tertiary">{doc.organ}</span>
                      <span className="text-[11px] text-text-tertiary ml-auto">
                        {formatDate(doc.publishedAt)}
                      </span>
                    </div>
                    <h3 className="text-sm font-semibold text-foreground leading-snug line-clamp-2 group-hover:text-primary transition-colors">
                      {doc.title}
                    </h3>
                    <p className="text-xs text-text-tertiary line-clamp-2">{doc.summary}</p>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>

      {/* KPI Cards */}
      {cachedAnalytics?.kpis ? (
        <section className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wider">{t("home.indicators")}</h2>
            <Link to="/analytics" className="text-xs text-primary hover:underline flex items-center gap-1">
              {t("common.actions.openAnalytics")} <ArrowRight className="w-3 h-3" />
            </Link>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {cachedAnalytics.kpis.map((kpi) => (
              <div key={kpi.label} className="rounded-xl border border-border bg-surface-elevated p-4 space-y-2">
                <p className="text-xs text-text-tertiary font-medium">{kpi.label}</p>
                <div className="flex items-end justify-between">
                  <span className="text-2xl font-bold text-foreground">{kpi.value}</span>
                  {typeof kpi.change === "number" ? (
                    <div className={cn("flex items-center gap-0.5 text-xs font-medium", kpi.change > 0 ? "text-do3" : "text-destructive")}>
                      {kpi.change > 0 ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                      {Math.abs(kpi.change)}%
                    </div>
                  ) : (
                    <span className="text-xs font-medium text-text-tertiary">{kpi.changeLabel || t("common.states.currentBase")}</span>
                  )}
                </div>
                {/* Sparkline */}
                <svg viewBox="0 0 100 24" className="w-full h-6" preserveAspectRatio="none">
                  <polyline
                    fill="none"
                    stroke="hsl(var(--primary))"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    points={(() => {
                      const max = Math.max(...kpi.sparkline);
                      const min = Math.min(...kpi.sparkline);
                      const range = max - min || 1;
                      return kpi.sparkline
                        .map((v, i) => {
                          const x = (i / (kpi.sparkline.length - 1)) * 100;
                          const y = 22 - ((v - min) / range) * 20;
                          return `${x},${y}`;
                        })
                        .join(" ");
                    })()}
                  />
                </svg>
              </div>
            ))}
          </div>
        </section>
      ) : (
        <section className="space-y-3">
          <div className="flex items-center justify-between gap-3 rounded-xl border border-dashed border-border bg-surface-elevated/60 p-4">
            <div className="space-y-1">
              <h2 className="text-sm font-semibold text-foreground">{t("home.analyticsOnDemandTitle")}</h2>
              <p className="text-xs text-text-tertiary">
                {t("home.analyticsOnDemandBody")}
              </p>
            </div>
            <Link to="/analytics" className="shrink-0 rounded-full border border-primary/30 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10">
              {t("common.actions.viewAnalytics")}
            </Link>
          </div>
        </section>
      )}
    </div>
  );
}
