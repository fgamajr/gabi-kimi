import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { SearchBar } from "@/components/SearchBar";
import { SectionBadge } from "@/components/Badges";
import { Icons } from "@/components/Icons";
import { SkeletonBlock } from "@/components/Skeletons";
import { getAnalytics, getSearchExamples, getStats, getTopSearches } from "@/lib/api";
import type { AnalyticsResponse, SearchExample, StatsResponse, TopSearch } from "@/lib/api";
import { getRecentDocuments, type RecentDocumentItem } from "@/lib/history";
import { navigateToDocument } from "@/lib/navigation";

const FALLBACK_SEARCHES: TopSearch[] = [
  { query: "portaria anvisa", count: 342 },
  { query: "decreto presidencial 2002", count: 281 },
  { query: "edital licitação", count: 256 },
  { query: "redistribuição servidores", count: 198 },
  { query: "nomeação cargo", count: 164 },
];

const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [analytics, setAnalytics] = useState<AnalyticsResponse | null>(null);
  const [topSearches, setTopSearches] = useState<TopSearch[]>([]);
  const [examples, setExamples] = useState<SearchExample[]>([]);
  const [recentDocs, setRecentDocs] = useState<RecentDocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [placeholderIndex, setPlaceholderIndex] = useState(0);

  useEffect(() => {
    Promise.allSettled([getStats(), getTopSearches(), getSearchExamples(), getAnalytics()])
      .then(([statsResult, topResult, examplesResult, analyticsResult]) => {
        if (statsResult.status === "fulfilled") setStats(statsResult.value);
        if (topResult.status === "fulfilled") setTopSearches(topResult.value?.slice(0, 8) || []);
        if (examplesResult.status === "fulfilled") setExamples(examplesResult.value?.slice(0, 6) || []);
        if (analyticsResult.status === "fulfilled") setAnalytics(analyticsResult.value);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const syncRecentDocs = () => setRecentDocs(getRecentDocuments());
    syncRecentDocs();
    window.addEventListener("focus", syncRecentDocs);
    window.addEventListener("storage", syncRecentDocs);
    return () => {
      window.removeEventListener("focus", syncRecentDocs);
      window.removeEventListener("storage", syncRecentDocs);
    };
  }, []);

  useEffect(() => {
    if (!examples.length) return;
    const timer = window.setInterval(() => {
      setPlaceholderIndex((current) => (current + 1) % examples.length);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [examples]);

  const placeholder = useMemo(() => {
    if (!examples.length) return "Pesquisar atos, órgãos, períodos e seções...";
    return examples[placeholderIndex]?.query || "Pesquisar atos, órgãos, períodos e seções...";
  }, [examples, placeholderIndex]);

  const searchChips = useMemo(
    () => (topSearches.length ? topSearches.slice(0, 5) : FALLBACK_SEARCHES),
    [topSearches]
  );
  const latestDocuments = useMemo(() => analytics?.latest_documents || [], [analytics?.latest_documents]);
  const topOrgans = useMemo(() => analytics?.top_organs.slice(0, 5) || [], [analytics?.top_organs]);
  const sectionTotals = useMemo(() => analytics?.section_totals || [], [analytics?.section_totals]);
  const leadingTypes = useMemo(
    () => analytics?.top_types_monthly.series.slice(0, 4) || [],
    [analytics?.top_types_monthly.series]
  );

  const formatRelative = (value?: string) => {
    if (!value) return "Sem data";
    const diff = Date.now() - new Date(value).getTime();
    const hours = Math.max(0, Math.floor(diff / (1000 * 60 * 60)));
    if (hours < 1) return "há instantes";
    if (hours < 24) return `há ${hours}h`;
    try {
      return new Date(value).toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric" });
    } catch {
      return value;
    }
  };

  const formatMonth = (value?: string | null) => {
    if (!value) return "Sem período";
    try {
      return new Date(value).toLocaleDateString("pt-BR", { month: "short", year: "numeric" });
    } catch {
      return value;
    }
  };

  const metricCards = useMemo(
    () => [
      {
        label: "Publicações indexadas",
        value: analytics?.overview.total_documents ? analytics.overview.total_documents.toLocaleString("pt-BR") : "0",
        accent: stats?.cluster_status ? `Cluster ${String(stats.cluster_status).toUpperCase()}` : "Corpus ativo",
        accentTone: stats?.cluster_status === "green" ? "text-emerald-400" : "text-text-secondary",
        series: analytics?.section_monthly.map((item) => item.total) || [0],
        color: "#7c6cf0",
      },
      {
        label: "Cobertura temporal",
        value: analytics?.overview.date_min && analytics?.overview.date_max
          ? `${new Date(analytics.overview.date_min).getFullYear()}–${new Date(analytics.overview.date_max).getFullYear()}`
          : "n/d",
        accent: analytics?.overview.tracked_months ? `${analytics.overview.tracked_months} meses em leitura` : "Sem série",
        accentTone: "text-text-secondary",
        series: analytics?.section_monthly.map((item) => item.do1 + item.do2) || [0],
        color: "#4b8bf5",
      },
      {
        label: "Órgãos rastreados",
        value: analytics?.overview.total_organs ? analytics.overview.total_organs.toLocaleString("pt-BR") : "0",
        accent: topOrgans[0] ? topOrgans[0].organ : "Sem ranking",
        accentTone: "text-text-secondary",
        series: topOrgans.map((item) => item.count) || [0],
        color: "#60a5fa",
      },
      {
        label: "Última atualização",
        value: stats?.last_updated
          ? new Date(stats.last_updated).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "2-digit" })
          : "n/d",
        accent: stats?.search_backend ? `Backend ${String(stats.search_backend).toUpperCase()}` : "Sem backend",
        accentTone: "text-emerald-400",
        series: leadingTypes.map((item) => item.total) || [0],
        color: "#a78bfa",
      },
    ],
    [analytics, leadingTypes, stats, topOrgans]
  );

  return (
    <div className="min-h-screen bg-background pb-24 md:pb-8">
      <main className="mx-auto max-w-[1120px] px-6 py-8 md:px-10 md:py-10">
        <header className="animate-fade-in">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-text-tertiary">Launchpad operacional</p>
              <h1 className="font-editorial mt-2 text-[2.7rem] leading-none text-foreground md:text-[4rem]">GABI · DOU</h1>
              <p className="mt-3 max-w-2xl text-base text-text-secondary">
                Busca, leitura e monitoramento do Diário Oficial da União ancorados no estado real do acervo.
              </p>
            </div>
            <div className="rounded-[24px] border border-white/8 bg-white/[0.03] px-4 py-3 text-right">
              <p className="text-[11px] uppercase tracking-[0.16em] text-text-tertiary">Janela observada</p>
              <p className="mt-2 text-lg text-foreground">
                {formatMonth(analytics?.overview.date_min)} → {formatMonth(analytics?.overview.date_max)}
              </p>
            </div>
          </div>
        </header>

        <section className="mt-8 animate-fade-in" style={{ animationDelay: "60ms" }}>
          <SearchBar autoFocus placeholder={placeholder} showShortcutHint />
        </section>

        <section className="mt-6 overflow-x-auto pb-1 animate-fade-in" style={{ animationDelay: "90ms" }}>
          <div className="flex min-w-max gap-2">
            {searchChips.map((term, index) => (
              <button
                key={term.query}
                onClick={() => navigate(`/search?q=${encodeURIComponent(term.query)}`)}
                className="inline-flex min-h-[40px] items-center gap-1.5 rounded-full border border-white/8 bg-white/[0.03] px-4 text-sm text-foreground transition-all hover:border-primary/20 hover:bg-white/[0.05] focus-ring animate-float"
                style={{
                  animationDelay: `${index * 40}ms`,
                  ["--float-amplitude" as string]: `${(index % 2 === 0 ? -1 : 1) * (1 + index * 0.15)}px`,
                  ["--float-duration" as string]: `${4.5 + index * 0.35}s`,
                }}
              >
                <span>{term.query}</span>
                {term.count ? <span className="text-text-tertiary">({term.count})</span> : null}
              </button>
            ))}
          </div>
        </section>

        <section className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {loading
            ? [1, 2, 3, 4].map((index) => (
                <div key={index} className="rounded-[22px] border border-white/8 bg-card p-5">
                  <SkeletonBlock className="mb-3 h-4 w-24" />
                  <SkeletonBlock className="mb-4 h-8 w-32" />
                  <SkeletonBlock className="h-16 w-full" />
                </div>
              ))
            : metricCards.map((item) => (
                <MetricCard key={item.label} {...item} />
              ))}
        </section>

        <section className="mt-8 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="reader-surface rounded-[28px] px-6 py-6 animate-fade-in" style={{ animationDelay: "120ms" }}>
            <SectionHeader icon={<Icons.document className="h-3.5 w-3.5" />} title="Publicações mais recentes" />
            <div className="mt-4 space-y-3">
              {latestDocuments.length > 0 ? latestDocuments.map((doc, index) => (
                <button
                  key={doc.id}
                  onClick={() => navigateToDocument(navigate, doc.id, "analytics-latest")}
                  className="w-full rounded-[22px] border border-white/8 bg-white/[0.03] px-4 py-4 text-left transition-all hover:border-primary/18 hover:bg-white/[0.05] focus-ring animate-lift"
                  style={{ animationDelay: `${index * 50}ms` }}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <SectionBadge section={doc.section} />
                        {doc.pub_date ? (
                          <span className="text-xs text-text-tertiary">
                            {new Date(doc.pub_date).toLocaleDateString("pt-BR")}
                          </span>
                        ) : null}
                        {doc.art_type ? (
                          <span className="rounded-full border border-white/8 px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] text-text-tertiary">
                            {doc.art_type}
                          </span>
                        ) : null}
                      </div>
                      <p className="font-editorial text-[1.25rem] leading-tight text-foreground">{doc.title}</p>
                      <p className="mt-2 text-sm text-text-secondary line-clamp-2">
                        {doc.snippet || doc.issuing_organ || "Documento recente disponível para leitura."}
                      </p>
                    </div>
                    <Icons.chevronRight className="mt-1 h-4 w-4 shrink-0 text-text-tertiary" />
                  </div>
                </button>
              )) : (
                <EmptyState icon={<Icons.document className="h-10 w-10" />} title="Sem publicações recentes" description="O backend ainda não retornou documentos recentes para o launchpad." />
              )}
            </div>
          </div>

          <div className="space-y-4">
            <OperationalPanel
              title="Pulso por seção"
              subtitle="Participação acumulada do corpus"
              content={sectionTotals.length > 0 ? (
                <div className="space-y-3">
                  {sectionTotals.map((item) => (
                    <BarRow
                      key={item.section}
                      label={formatSectionLabel(item.section)}
                      value={item.count}
                      max={sectionTotals[0]?.count || item.count}
                    />
                  ))}
                </div>
              ) : (
                <EmptyPanelText text="Sem distribuição por seção disponível." />
              )}
            />

            <OperationalPanel
              title="Órgãos líderes"
              subtitle="Volume agregado de publicações"
              content={topOrgans.length > 0 ? (
                <div className="space-y-3">
                  {topOrgans.map((item) => (
                    <BarRow key={item.organ} label={item.organ} value={item.count} max={topOrgans[0]?.count || item.count} />
                  ))}
                </div>
              ) : (
                <EmptyPanelText text="Sem ranking de órgãos disponível." />
              )}
            />
          </div>
        </section>

        <section className="mt-8 grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
          <div className="reader-surface rounded-[28px] px-6 py-6 animate-fade-in" style={{ animationDelay: "150ms" }}>
            <SectionHeader icon={<Icons.clock className="h-3.5 w-3.5" />} title="Vistos recentemente" />
            <div className="mt-4">
              {recentDocs.length > 0 ? (
                <div className="space-y-3">
                  {recentDocs.map((doc, index) => (
                    <button
                      key={doc.id}
                      onClick={() => navigateToDocument(navigate, doc.id, "recent-document")}
                      className="flex w-full items-start justify-between gap-3 rounded-[18px] border border-white/8 bg-white/[0.03] px-4 py-4 text-left transition-all hover:border-primary/18 hover:bg-white/[0.05] focus-ring animate-slide-in-right animate-lift"
                      style={{ animationDelay: `${index * 50}ms` }}
                    >
                      <div className="min-w-0">
                        <div className="mb-2 flex items-center gap-2">
                          {doc.section ? <SectionBadge section={doc.section} /> : null}
                          <span className="text-xs text-text-tertiary">{formatRelative(doc.viewedAt)}</span>
                        </div>
                        <p className="text-sm font-semibold text-foreground line-clamp-2">{doc.title}</p>
                        <p className="mt-1 text-xs text-text-secondary line-clamp-2">
                          {doc.snippet || doc.issuingOrgan || "Documento visitado recentemente na base."}
                        </p>
                      </div>
                      <Icons.chevronRight className="mt-1 h-4 w-4 shrink-0 text-text-tertiary" />
                    </button>
                  ))}
                </div>
              ) : (
                <EmptyState
                  icon={<Icons.search className="h-10 w-10" />}
                  title="Sem histórico local"
                  description="Abra documentos a partir da busca ou dos painéis operacionais para montar seu histórico de leitura."
                />
              )}
            </div>
          </div>

          <div className="reader-surface rounded-[28px] px-6 py-6 animate-fade-in" style={{ animationDelay: "180ms" }}>
            <SectionHeader icon={<Icons.analytics className="h-3.5 w-3.5" />} title="Tipos líderes observados" />
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              {leadingTypes.length > 0 ? leadingTypes.map((item) => (
                <div key={item.key} className="rounded-[22px] border border-white/8 bg-white/[0.03] px-4 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-[11px] uppercase tracking-[0.16em] text-text-tertiary">{item.label}</p>
                      <p className="mt-2 font-mono text-2xl text-foreground">{item.total.toLocaleString("pt-BR")}</p>
                    </div>
                    <Sparkline series={item.points} color="#a78bfa" />
                  </div>
                </div>
              )) : (
                <EmptyPanelText text="Sem séries de tipos disponíveis." />
              )}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
};

const MetricCard: React.FC<{
  label: string;
  value: string;
  accent: string;
  accentTone: string;
  series: number[];
  color: string;
}> = ({ label, value, accent, accentTone, series, color }) => (
  <div className="rounded-[22px] border border-white/8 bg-[linear-gradient(180deg,rgba(18,20,32,0.92),rgba(10,12,22,0.98))] px-4 py-4 animate-spring-in animate-lift">
    <div className="mb-3 flex items-center justify-between gap-3">
      <span className="text-[11px] uppercase tracking-[0.16em] text-text-tertiary">{label}</span>
      <span className={`text-sm ${accentTone}`}>{accent}</span>
    </div>
    <div className="flex items-end justify-between gap-3">
      <p className="font-mono text-[2rem] font-semibold text-foreground">{value}</p>
      <Sparkline series={series} color={color} />
    </div>
  </div>
);

const Sparkline: React.FC<{ series: number[]; color: string }> = ({ series, color }) => {
  const safeSeries = series.length > 1 ? series : [0, ...(series[0] != null ? [series[0]] : [0])];
  const max = Math.max(...safeSeries);
  const min = Math.min(...safeSeries);
  const range = Math.max(1, max - min);
  const points = safeSeries
    .map((value, index) => {
      const x = (index / Math.max(1, safeSeries.length - 1)) * 120;
      const y = 44 - ((value - min) / range) * 28;
      return `${index === 0 ? "M" : "L"}${x},${y}`;
    })
    .join(" ");

  return (
    <svg viewBox="0 0 120 48" className="h-12 w-[120px]">
      <path d={points} fill="none" stroke={color} strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
};

const SectionHeader: React.FC<{ icon: React.ReactNode; title: string }> = ({ icon, title }) => (
  <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.22em] text-text-tertiary">
    {icon}
    {title}
  </div>
);

const OperationalPanel: React.FC<{ title: string; subtitle: string; content: React.ReactNode }> = ({ title, subtitle, content }) => (
  <div className="reader-surface rounded-[28px] px-6 py-6 animate-fade-in">
    <p className="text-[11px] uppercase tracking-[0.16em] text-text-tertiary">{title}</p>
    <p className="mt-2 text-sm text-text-secondary">{subtitle}</p>
    <div className="mt-4">{content}</div>
  </div>
);

const BarRow: React.FC<{ label: string; value: number; max: number }> = ({ label, value, max }) => (
  <div>
    <div className="mb-1 flex items-center justify-between gap-3">
      <span className="truncate text-sm text-foreground">{label}</span>
      <span className="shrink-0 text-xs text-text-tertiary">{value.toLocaleString("pt-BR")}</span>
    </div>
    <div className="h-2 overflow-hidden rounded-full bg-white/[0.05]">
      <div
        className="h-full rounded-full bg-[linear-gradient(90deg,hsl(var(--primary)),hsl(var(--accent)))]"
        style={{ width: `${Math.max(8, (value / Math.max(1, max)) * 100)}%` }}
      />
    </div>
  </div>
);

const EmptyState: React.FC<{ icon: React.ReactNode; title: string; description: string }> = ({ icon, title, description }) => (
  <div className="flex min-h-[180px] flex-col items-center justify-center text-center">
    <div className="mb-4 text-text-tertiary">{icon}</div>
    <p className="font-editorial text-2xl text-foreground">{title}</p>
    <p className="mt-2 max-w-md text-sm text-text-secondary">{description}</p>
  </div>
);

const EmptyPanelText: React.FC<{ text: string }> = ({ text }) => (
  <p className="text-sm text-text-secondary">{text}</p>
);

function formatSectionLabel(value: string) {
  const normalized = String(value || "").toLowerCase();
  if (normalized === "do1") return "Seção 1";
  if (normalized === "do2") return "Seção 2";
  if (normalized === "do3") return "Seção 3";
  if (normalized === "do1e" || normalized === "e") return "Extra";
  return value || "Sem seção";
}

export default HomePage;
